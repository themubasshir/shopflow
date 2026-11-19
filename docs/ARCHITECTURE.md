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
  services/  pricing, customer accounts, billing, loyalty and receivables
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
  seeded manager’s read permissions on a demo shop. Demo access is opt-in in
  development and test. Customer and invoice APIs require a live session.
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
upstream. Next.js checks the public site Origin before browser API writes.

## Billing and collections (Phase 2C)

`POST /invoices` → `app/services/billing.finalize_invoice` runs one atomic
transaction. Either everything below commits, or nothing does:

1. Reserve the shop-local idempotency key before taking business locks. Save the response inside the transaction.
2. Lock the customer, product rows in ascending ID order, and loyalty account. Calculate prices and discounts from database values and validate stock and points.
3. Allocate the daily invoice number and post the invoice, tender, stock movements, redemption and any unpaid amount.
4. Credit the award when the invoice is fully settled. Outstanding invoices keep a snapshot of the applicable policy and eligible net spend.

Collections reserve the key, then lock the customer, invoice and loyalty account. The transaction posts a payment and an immutable ledger credit. Full settlement can award the original sale's points once.

Money uses PostgreSQL `NUMERIC(14,2)` and Python `Decimal`. See [Phase 2C](PHASE-2C.md) for rules, permissions, and the full lock order.

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
