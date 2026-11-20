# Phase 3C — Continuous automatic MedEx catalog import

Status: **machinery committed + verified; collection running with auto-promotion.**
Commits `c005b24` (bulk promotion + separation) and `809576f` (continuous auto-import).

## What changed

The MedEx pipeline no longer waits for the full crawl to finish before
medicines reach ShopFlow's catalog. For every detail page the collector
successfully fetches and validates:

1. English fields are extracted and the raw payload preserved in
   `medicine_catalog_staging` (audit/recovery).
2. The row is deduplicated on the stable MedEx `external_id` +
   `medicine_key` matching rules.
3. A bounded `promote_batch` sweep promotes it **immediately** if it
   classifies `ready` — inside the same per-detail checkpoint, so progress is
   saved continuously and the run resumes cleanly after interrupt.

`run_import` accepts `auto_promote` + a system `principal` (built from the
seeded owner for the offline collector). A promote error is logged and
skipped — it never kills the collector. Throttling and single-concurrency
request budget are unchanged.

## Classification gates auto-import

| Class | Action |
|---|---|
| `ready` | → zero-stock, unpriced `MED-{brand}-{source_id}` product |
| `imported` / `duplicate` | skipped — never overwrites manual edits |
| `ambiguous` | pending fuzzy match → held in review |
| `invalid` | missing brand / invalid parse → held in review |
| `non_medicine` | glucometer/test-strip/lancet devices → held in review |

Every imported product: `stock_on_hand=0`, base `selling_price=0` (unset),
no batches, no stock movements, no purchase cost, MedEx price on
`medicine_details.mrp` only. `medicine_details.source='medex'` records
provenance.

## Catalog vs billing separation

- `GET /catalog/products?sellable=true` → stock>0 AND base price>0 (billing
  uses this — imported unpriced/unstocked medicines can never be sold).
- `?view=in_stock|out_of_stock|missing_price|medicine` for the catalog
  workspace; Products page has a matching filter strip.
- Imported medicines are searchable in catalog/purchasing but excluded from
  the till until stocked + priced.

## Search at scale

Additive migration `a1b2c3d4e5f6` adds pg_trgm GIN indexes on
`products.name_en/name_bn/sku` and staging `brand/generic/manufacturer`, so
the `LIKE '%q%'` search stays indexed over ~25k rows. Measured: **2–9 ms**
substring search at 4k seeded rows.

## Verification

- 67 already-staged pilot records auto-promoted → **67 MED-* products**, all
  zero stock / zero sellable price / zero batches / zero movements; 17
  price-free records keep `mrp` null rather than inventing a price.
- Integrity: invoices=75, suppliers=1, customers=3, loyalty_accounts=2,
  supplier/customer ledgers — all unchanged.
- **245 backend tests pass** (12 bulk-promotion + 2 search-perf new); ruff,
  tsc, eslint clean.

## Remaining

- Full catalog collection is running (run `b4787dee`, resumable); the final
  totals + reconciliation report follow when the crawl completes.
