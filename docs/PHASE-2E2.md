# Phase 2E-2 product catalog management

Complete bilingual grocery + pharmacy product management: create, edit,
activate/deactivate, category management, multi-unit conversions, and a
transactional CSV/XLSX bulk import — all permission-gated by `catalog:write`.

## Model (no schema migration)

All catalogue fields already existed on `products`, `product_units`,
`categories` and `medicine_details`, so no Alembic migration was required.
`openpyxl>=3.1` was added to `pyproject.toml` for XLSX parsing.

## Endpoints (`/api/v1/catalog`)

| Method | Path | Permission | Purpose |
|---|---|---|---|
| GET | `/products` | `catalog:read` (all) | Search/list (name, SKU, barcode, Bangla, aliases) |
| GET | `/products/{id}` | `catalog:read` | Detail with units + medicine detail + `has_history` |
| POST | `/products` | `catalog:write` | Create grocery or medicine product (zero stock) |
| PUT | `/products/{id}` | `catalog:write` | Update catalogue fields + units |
| PATCH | `/products/{id}/state` | `catalog:write` | Activate / deactivate |
| DELETE | `/products/{id}` | `catalog:write` | Hard-delete only when no history |
| GET | `/categories/manage` | `catalog:write` | Full category list incl. inactive + product_count |
| POST | `/categories` | `catalog:write` | Create category |
| PUT | `/categories/{id}` | `catalog:write` | Update category (slug + cycle-checked parent) |
| POST | `/imports/preview` | `catalog:write` | Parse + validate file, classify rows |
| POST | `/imports/commit` | `catalog:write` | Transactionally insert approved rows |

Cashiers keep `catalog:read` for the billing search but have no `catalog:write`.

## Stock integrity

- `stock_on_hand` / `held_quantity` are written **only** by `post_stock` inside
  the stock-ledger transaction. Product create/update never touches them;
  `ProductWrite`/`ProductUpdate` don't even accept a stock field.
- New products always begin with `stock_on_hand = 0`. Stock enters via
  receiving (`/purchases/.../receive`) or audited `post_opening_stock` /
  `adjust_stock` — never through a product endpoint.
- Products with any `InvoiceItem` / `StockMovement` / `PurchaseItem` history
  cannot be hard-deleted (`has_history`); they deactivate instead, preserving
  the price/name snapshots already written onto `InvoiceItem.description`,
  `receipt_details` and `unit_price` at billing time.

## Units and conversions

Exactly one `ProductUnit` per product is `is_base` with `conversion_factor = 1`.
For discrete base units (`piece`, `pack`, `strip`, `box`, `bottle`, `sachet`,
`tablet`, `capsule`, `tab`, `cap`, `pcs`) a non-integral `conversion_factor`
is rejected — a strip→tablet ratio is only ever an explicitly configured whole
number, never assumed.

## Bulk import

1. `POST /imports/preview` (multipart `file`) → parse `.csv`/`.xlsx` (first
   worksheet, `data_only` — formulas resolve to cached values, macros dropped).
   Each row is validated into `ProductImportRowModel`, checked for within-file
   SKU/barcode duplicates and against the live catalog (sku → barcode → name),
   then classified `create` / `duplicate` / `invalid`.
2. `POST /imports/commit` with the approved rows. Commit **re-validates against
   the live catalog** (the preview is advisory): rows that now collide are
   `skipped_duplicate`, never overwritten; each row runs in its own savepoint
   so a bad row cannot abort the batch; one `audit_log` row records the totals.

File limits: `.csv`/`.xlsx`/`.xlsm` only, ≤ 2 MB, ≤ 5000 rows.

## UI (`/products`, owner/manager)

Tabbed bilingual workspace: **Products** (search, add/edit drawer with units +
pharmacy fields, activate/deactivate), **Categories** (create + list), and
**Import** (upload → preview table → approve rows → commit → result report +
CSV template download). Mobile bottom-sheet form, touch-friendly, field-level
errors, design-system tokens throughout. Sidebar "Products" item is gated by
`catalog:write`.

## Bug fix

`list_products` searched `Product.search_aliases.any(...)` which raises
`SADeprecationWarning`→error under the suite's `filterwarnings=error`. Rewritten
as a correlated `unnest(search_aliases)` `EXISTS`, restoring alias search.

## Verification

- `pytest`: **204 passed** on `shopflow_test` (186 baseline + 18 new catalog tests).
- Ruff clean; `tsc --noEmit` clean; `eslint --max-warnings=0` clean;
  `next build` succeeded (`/products` registered).
- `verify_receipts.py`: 4 viewport workflows passed (receipt/print regression).
- `products-e2e.mjs` Playwright: en+bn × desktop+mobile — product created via UI,
  listed via search, zero stock (screenshots in `.local/products-shots`).
- Live check: a new grocery product and a new medicine product are both found
  through `GET /catalog/products?q=` (the billing search) with `stock_on_hand`
  0.000 and `is_active` true.

## Remaining limitations

- `barcode`/`pack_size`/`search_aliases` can be set on update but not cleared
  back to null (`None` means "leave unchanged").
- Import creates products only — it never edits existing rows, batches, stock,
  or prices (by design).
- Import history is audit-log backed (`product.import_commit`); there is no
  dedicated import-run table, so the UI shows the live result report rather
  than a persisted history list.
