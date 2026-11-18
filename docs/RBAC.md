# ShopFlow permission matrix (Phase 2B)

Single source of truth: `apps/api/app/core/permissions.py`. Tests in
`tests/test_rbac.py` assert these boundaries over real HTTP.

## Roles

| Permission | OWNER | MANAGER | CASHIER |
|---|:---:|:---:|:---:|
| `sales:read` — list invoices/customers | ✓ | ✓ | ✓ (scoped) |
| `sales:write` — finalize a bill | ✓ | ✓ | ✓ (assigned counters) |
| `catalog:read` — products/categories | ✓ | ✓ | ✓ |
| `catalog:write` — edit catalog/pricing | ✓ | ✓ | — |
| `customers:read` | ✓ | ✓ | ✓ |
| `customers:write` | ✓ | ✓ | — |
| `loyalty:read` | ✓ | ✓ | ✓ |
| `loyalty:write` — rules/redemptions | ✓ | ✓ | — |
| `reports:read` — operational/financial | ✓ | ✓ | — |
| `counters:manage` — activate/deactivate | ✓ | — | — |
| `employees:manage` — staff admin | ✓ | grant-able | — |
| `settings:write` — shop config | ✓ | — | — |
| `audit:read` — audit log | ✓ | — | — |

## Counter authorization

`user_counters` assigns employees to counters. `Principal.assigned_counter_ids`:

* `null` → **unrestricted** (owner, manager) — may bill at any active counter.
* a set → **restricted** (cashier) — may only bill at an assigned counter.

Enforcement is server-side:

* `POST /invoices` → `assert_counter_allowed` rejects a `counter_id` the caller
  is not assigned to (403), independent of anything the client sends.
* `GET /invoices` → restricted callers see only their own counters' history.

## Session lifecycle

* `POST /auth/login` → mints a JWT (`jti`) + an `auth_sessions` row.
* `POST /auth/logout` → sets `revoked_at`; the token dies immediately.
* Disable / reset-password → revokes **all** of that user's sessions.
* Change password → revokes every *other* session.
* Both `get_principal` and `get_authenticated_principal` call
  `_session_is_live`, so a revoked/expired session fails reads and writes.
* Login is rate-limited (`login_rate_limit_*`) → `429` after the cap.
