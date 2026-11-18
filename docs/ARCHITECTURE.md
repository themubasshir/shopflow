# ShopFlow architecture

## Modular monolith

ShopFlow is one deployable backend (FastAPI) and one deployable frontend
(Next.js) kept in a monorepo so contracts, seeds, and docs stay in sync.
The "modular" boundary is enforced inside `apps/api/app`: each business
area owns its models, schemas, router, and service functions.

```
app/
  core/      config, security (argon2 + JWT), typed errors
  db/        engine, session, Base + naming conventions
  models/    SQLAlchemy 2 models grouped by domain (shop/catalog/inventory/sales/loyalty/audit)
  schemas/   Pydantic request/response models
  services/  pure business rules + the billing transaction (loyalty, billing)
  api/       deps (auth principal) + v1 routers
```

## Request flow

Reads (server components):

```
Next.js [locale] page (server component)
   └─ fetch() → lib/api.ts (httpOnly cookie → Authorization, no-store, typed)
        └─ FastAPI router → sqlalchemy Session → PostgreSQL 17 shopflow_dev
```

Writes (browser → same-origin proxy → API):

```
billing-client.tsx (client component)
   └─ POST /api/billing/invoices  (Next route handler, same origin)
        └─ attaches Authorization from the httpOnly cookie
             └─ FastAPI POST /invoices → finalize_invoice() → PostgreSQL
```

* The frontend never opens a DB connection, and the browser never holds the JWT.
* Every response is a Pydantic schema → OpenAPI → `packages/contracts/api.generated.ts`.
* Errors bubble through `AppError` subclasses → consistent `{error, code, details}` JSON.
  FastAPI's own `HTTPException` and Pydantic `RequestValidationError` are normalized
  into the same envelope in `main.py`, so the UI can translate every failure by `code`.

## Auth

`deps.get_principal` returns a `Principal`:

* **Demo mode** (no `Authorization` header, `settings.demo_mode` on): the
  seeded manager on the seeded shop — read APIs only. Flipping `demo_mode`
  off makes every read require a token.
* **JWT mode**: `POST /auth/login` verifies argon2 hash and returns an
  HS256 token carrying `sub`, `shop_id`, `role`, `permissions[]`, `jti`.

### Sessions (Phase 2B)

Each login inserts an `auth_sessions` row keyed by the token's `jti`. JWTs
are self-contained, so this table is the server-side handle that lets
**logout** (`POST /auth/logout`) and **account disable** revoke a live token
immediately instead of trusting it until `exp`. Both `get_principal` and
`get_authenticated_principal` reject a token whose session is revoked or
expired (`_session_is_live`), so reads die on sign-out too.

`POST /auth/password` changes the caller's password and revokes every other
session. `POST /auth/login` is rate-limited by a sliding-window counter
(`login_rate_limit_*` settings) keyed on email+IP, returning `429`.

### RBAC (Phase 2B)

`app/core/permissions.py` is the single permission matrix for the three
roles — `owner` (all 13 permissions), `manager` (operations, no admin
grants), `cashier` (billing + lookup). `Principal.require()` raises 403.
Admin routers live in `employees.py` (`employees:manage`) and `counters.py`
(`counters:manage`).

### Counter authorization (Phase 2B)

`user_counters` assigns employees to checkout counters. `Principal.
assigned_counter_ids` is `None` for owner/manager (unrestricted) and a set
of allowed counters for cashiers. `assert_counter_allowed` runs inside
`POST /invoices`, so a client-sent `counter_id` is never trusted — a cashier
billing an unassigned counter gets 403. `GET /invoices` is likewise scoped
to assigned counters for restricted roles.

**Write endpoints use `get_authenticated_principal`**, which has no demo
fallback and re-verifies the user is active and the session is live. The web
app stores the token in an httpOnly, same-site cookie (`shopflow_token`) via
`POST /api/auth`; server components read it with `lib/session.ts`, and
writes go through `app/api/*` route handlers that attach `Authorization`
upstream.

## Billing transaction (Phase 2A)

`POST /invoices` → `app/services/billing.finalize_invoice` runs one atomic
transaction. Either everything below commits, or nothing does:

1. **Idempotency** — the `Idempotency-Key` header plus a request hash is stored
   in `idempotency_records`. Replaying the same key with the same payload returns
   the original invoice (200, `idempotent_replay: true`); the same key with a
   different payload is a 409 `idempotency_conflict`.
2. **Lock products in a deterministic order** — `SELECT product.id ... FOR UPDATE`
   ordered by id, so two concurrent bills touching the same products can never
   deadlock and stock can't be oversold.
3. **Price server-side** — line totals and invoice totals are computed from DB
   prices with `Decimal`. Client-supplied prices are never trusted.
4. **Allocate the invoice number** — `invoice_counters` (`shop_id`,
   `counter_date` YYMMDD, `last_seq`) is locked `FOR UPDATE` and incremented,
   producing `INV-YYMMDD-NNNN` with no gaps or duplicates.
5. **Deduct stock, write `stock_movements`, payments, loyalty earn** — customers
   earn `floor(eligible_amount / 100)` points once, after finalize; no redemption
   in Phase 2A.

`InsufficientStockError` (409 `insufficient_stock`) carries the requested and
available quantity in `details`; it is raised before any write, so a rejected
bill leaves stock, counters and loyalty untouched.

## Money & loyalty rules

* All money is `NUMERIC(14,2)`; quantities `NUMERIC(12,3)`; points are `INTEGER`.
* No floats anywhere in financial math (backend `Decimal`, frontend formats the string).
* Loyalty rules are a pure, unit-tested `LoyaltyPolicy` in
  `app/services/loyalty.py`:
  - 1 point per full BDT 100 of *eligible* spend (`category.loyalty_eligible`)
  - unlock at 300 pts, redeem in multiples of 100, 100 pts = BDT 100
  - same-invoice earn/redeem impossible (earn happens after finalize)
  - returns reverse earned points
* DB-side enforcement: CHECK constraints on `loyalty_accounts`
  (`lifetime_earned - lifetime_redeemed = points_balance`),
  `loyalty_redemptions` (points % 100 = 0), unique `invoice_id` on
  redemptions, and a partial unique index guaranteeing one active
  `loyalty_rules` row per shop.

## i18n

`next-intl` with a `[locale]` segment; `middleware.ts` (renamed `proxy.ts`
per Next 16 convention) keeps every route under `/en|/bn`. Messages live
in `src/messages/{en,bn}.json`. Product names carry both `name_en` and
`name_bn` plus a `search_aliases` array; `localizedName()` picks the right
one. Bangla uses **Noto Sans Bengali**; figures stay Latin digits for POS
legibility. `preferred_locale` is already on `users` for Phase 2.

## Security notes

* Secrets only in `.env` (gitignored). `SECRET_KEY` and the `shopflow_app`
  DB password were generated locally and are not in git.
* Argon2id hashing, timing-safe `verify_password` for unknown users.
* CORS is a whitelist; request IDs added per request for audit trails.
* `audit_logs` records every invoice write; `idempotency_records` makes the
  billing write replay-safe.
