# ShopFlow architecture — Phase 1

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
  services/  pure business rules (loyalty is the only one in Phase 1)
  api/       deps (auth principal) + v1 routers
```

## Request flow

```
Next.js [locale] page (server component)
   └─ fetch() → lib/api.ts (no-store, typed)
        └─ FastAPI router → sqlalchemy Session → PostgreSQL 17 shopflow_dev
```

* The frontend never opens a DB connection.
* Every response is a Pydantic schema → OpenAPI → `packages/contracts/api.generated.ts`.
* Errors bubble through `AppError` subclasses → consistent `{error, code, details}` JSON.

## Auth (Phase 1)

`deps.get_principal` returns a `Principal`:

* **Demo mode** (no `Authorization` header): the seeded manager on the
  seeded shop — enough for Phase 1 read APIs.
* **JWT mode**: `POST /auth/login` verifies argon2 hash and returns an
  HS256 token carrying `sub`, `shop_id`, `role`, `permissions[]`.

RBAC lives in `roles.permissions` (string array). `Principal.require()`
raises 403 for missing permissions.

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
* `audit_logs` + `idempotency_records` tables are in place for Phase 2
  write APIs (billing finalize, stock adjust, loyalty redeem).
