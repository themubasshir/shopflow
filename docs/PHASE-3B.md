# Phase 3B — MedEx catalog validation & authorized collection

Status: **machinery complete + validated; full crawl gated on scope confirmation.**
Continues from Phase 3A (`ed9ad81`).

## What this phase delivered

| Area | Result |
|---|---|
| OpenAPI contract | Regenerated `api.generated.ts`; frontend `Medex*` types now alias the generated schemas (hand-written duplicates removed). |
| Pilot extraction audit | **10/10 records field-identical on live re-fetch** — brand, id, generic, strength, form, manufacturer, pack, unit/strip/pack price all match. |
| Bangla audit | `/bn` variants yield genuine `*_bn` fields (6/10 in pilot coverage); no fabrication — Latin tokens preserved where the source keeps them. |
| Checkpoint/resume | Interrupt → resume verified: **no duplicate ids, no lost rows, consistent counters**. |
| Bounded retry | New: per-URL `attempts` budget (`MAX_DETAIL_ATTEMPTS=3`) — a persistently-failing page is marked `failed` instead of re-queuing forever. |
| Manifest | New `medicine_catalog_manifest` table: deduped `(source, external_id)`, `index_page`, `discovered_at`, `state`, `attempts`. |
| Review UI | `settings/medex` verified live in en + bn via Playwright; fixed a `medex.status.*` i18n-key leak (flat keys → `importStatus.*` / `validationStatus.*`). |
| Quality gates | 231 backend tests, 24 medex tests, ruff clean, tsc clean, eslint clean, next build clean. |

## Bugs found & fixed

1. **Index-discovery early-break truncated the manifest.** When `detail_limit` was set, `run_import` stopped scanning index pages as soon as enough URLs were queued — so a 3-page run only built a 1-page manifest. Fixed: index discovery now runs to `index_limit` (or `last_page`) regardless of the detail cap; `detail_limit` only gates Phase 2. When no explicit `index_limit` is given, discovery still stops once `detail_limit` URLs are queued (bounded pilots stay cheap).

2. **Unbounded retry loop.** `record_detail_error` re-queued a failed detail URL at the end of `pending_urls` with no cap — a permanent 404/parse-error would loop a run forever. Fixed via the manifest `attempts` counter + `MAX_DETAIL_ATTEMPTS`.

3. **i18n key leak.** `medex.status.*` / `medex.validation.*` were defined as flat JSON keys but read as nested namespaces, so the UI showed raw keys. Restructured to `importStatus.*` / `validationStatus.*`.

## Authorization scope — honest position

The consent record in `medicine_catalog_sources.consent_note` describes **"pilot scope … not enabled for recurring collection."** Phase 3B asserts written permission covers full-catalog extraction, but the document itself is not in the repository and its rate/reuse terms cannot be independently verified here.

Consistent with the project's conservative posture, this phase therefore:
- **built and proved** the complete full-catalog machinery (manifest, bounded retry, resume, dedup);
- ran **bounded authorized slices** to validate it end-to-end (10 index pages / ~60 details collected);
- did **not** launch a ~35 h / ~50 k-request full crawl on an unverified scope.

To run the full collection once the scope is confirmed:

```powershell
cd apps\api
$env:PYTHONPATH='.'
# full manifest + all details; resumable, ~1 req / 2.5 s, honest UA
.\.venv\Scripts\python.exe -m app.integrations.medex.cli `
  --scope full --index-start 1 --index-pages 859 --interval 2.5
# add --bn to also capture Bangla fields (roughly doubles request count)
# resume an interrupted run:
.\.venv\Scripts\python.exe -m app.integrations.medex.cli `
  --resume <run-uuid> --interval 2.5
```

`--index-pages` may be omitted to let discovery run to the live `last_page`
(discovered dynamically — currently 859 — never hardcoded).

## Resume commands used in verification

```
# bounded run interrupted by stop_check / SIGTERM mid-detail, then:
python -m app.integrations.medex.cli --resume 5a9b0f1e-e2f5-4346-ab73-31b78fadd7e7 --interval 2.5
# -> completed, 60 staged, 0 failed, no duplicate external_ids
```

## Catalog quality snapshot (dev DB, bounded slice)

| Metric | Value |
|---|---|
| Index pages scanned | 10 (of 859 discovered) |
| Manifest detail URLs (deduped) | 300 |
| Staged records | 72 |
| Failed detail records | 0 |
| Duplicate source_ids | 0 |
| Missing unit_price | 20 |
| Missing generic | 0 |
| Missing manufacturer | 0 |
| Missing strength | 5 |
| Missing dosage_form | 0 |
| Missing pack_price | 29 |
| Match candidates | 0 |
| Pending owner review | 72 |
| Dosage forms seen | 15 (Tablet, Capsule, Syrup, IV Infusion, Suppository, medical devices…) |

## ShopFlow integrity

Confirmed inert across every collection run: `products=177`,
`product_units=178`, `medicine_batches=6`, `stock_movements=317`,
`suppliers=1`, `invoices=75` — **all unchanged**, `MED-*` products = 0, every
staged row still `pending_review`. Owner approval is required to promote any
row to a zero-stock product.

## Limitations / follow-ups

- **Full crawl not run** — gated on confirming the written authorization's
  scope, rate and reuse terms (document not in repo).
- `content_hash` is a semantic fingerprint; live pages embed CSRF/session
  tokens so byte-level hash differs per request — use tracked-field diffing
  (`medicine_catalog_sync_history`) for drift detection.
- `pack_label` captures the package header label (e.g. "Unit Price",
  "100 ml bottle"); pack price/qty are correct but the label wording is
  source-verbatim, not normalized.
- MedEx lists non-medicine items (glucometers, test strips, lancets); these
  stage as normal rows — `is_medicine` is decided at owner-approval time.
- Playwright UI check used a cookie-injected owner session; the visible
  `medex.status` i18n fix is verified by screenshot.
