# Phase 2E purchasing and batch inventory

## Workflows and permissions

The Inventory operations workspace contains purchases, suppliers, medicine batches, stock movements and low-stock products in English and Bangla. Owners and managers can create, edit and deactivate suppliers, associate catalog products, look up supplier invoices, receive orders in installments and record cash, bKash, Nagad or bank payments. Supplier history remains available after deactivation. An already-open purchase can still receive stock for an inactive supplier.

Inventory operations and purchase costs require an authenticated session with `reports:read`. Every modification additionally requires `catalog:write`. Cashiers receive saleable stock counts through the catalog and use their existing counter-scoped billing permissions. Sensitive stock changes record the authenticated actor, action, reasons and references in the audit log and append stock movements for physical quantity changes. Supplier charges and payments are append-only.

## Purchase accounting

Drafts use the ordering unit and conversion factor at entry. Quantities support three decimal places with exact conversion to base units. Discrete products require whole base units. Line totals use decimal round-half-even. The supplier discount is allocated across lines by cumulative gross share, then across partial receipts by cumulative received quantity. The final receipt posts the exact order total including its share of the discount.

Stock and supplier payables post together only when an idempotent receiving transaction commits. Each receipt creates separately valued stock lots. The supplier ledger records a charge at receipt and a credit when staff record a payment against that purchase. Payment cannot exceed its posted outstanding amount. Active supplier references are unique per supplier after case and whitespace normalization. A cancelled or fully reversed purchase releases the supplier reference for a replacement entry.

Cancellation applies to drafts. Reversal of a received or partly received purchase is a compensating transaction that removes the original lots and reverses the supplier payable. Reversal requires an unpaid purchase with the full received quantities still present in the original lots. A reversal leaves the original movements, costs and purchase details available in history.

## Pharmacy, expiry and reconciliation

- Medicine availability comes from active, non-quarantined batches with positive stock and expiry strictly after today's date in the shop's timezone. For ShopFlow's default Asia/Dhaka shop, a batch stops being saleable at local midnight at the start of its printed expiry date.
- Checkout locks products and batches before allocating. The earliest expiry wins, with received timestamp and batch ID as deterministic tie-breakers. One invoice line can use several batches. The invoice stores exact base-unit allocations and batch and expiry snapshots for reprints and future returns. The saved price, receipt totals and loyalty rules retain their existing checkout behavior.
- Batch identity is scoped to the product. Repeated receipts can add to the same batch if the recorded manufacturer number, expiry and other known details agree. A different product can use the same manufacturer batch number. Stock receipts retain their own cost lots while the batch view shows its first recorded purchase cost and current base-unit selling-price reference.
- The expiry view offers cumulative 30-, 60- and 90-day windows, an expired filter and a quarantine filter. Quarantine immediately excludes inventory from sale. An expired batch cannot be released. Disposal and supplier returns require expired or quarantined stock and a reason. Supplier return removes physical stock and records the movement. A payment refund or supplier credit is a separate future workflow.
- Product physical stock equals the signed sum of product movements. Medicine physical stock also equals the sum of its batch balances, including stock held in quarantine. The public available-to-sell projection excludes blocked batches. Grocery stock uses the product balance, supports fractional quantities, and can be manually added, removed, or marked damaged. Lot-level consumption uses opening stock first, then FIFO within the chosen batch or grocery product. Valuation uses the remaining share of each known receipt or adjustment cost, and reports unvalued quantity separately. Physical valuation includes held stock until a disposition is posted.
- Low stock uses saleable quantity and the product's base-unit threshold. Updating a threshold and quarantining a batch are audited state changes.

## Locking and migrations

The lock order starts with the shop-local idempotency reservation, followed by the customer or purchasing parent record when relevant, product IDs in ascending order, then batch and stock lot rows under their product locks. Per-product batch writers serialize on the product row. Checkout allocates only after acquiring these locks, and then follows the existing loyalty and invoice number sequence. Purchase intake, settlement and reversal additionally serialize on the purchase row. Failed writes roll back stock, lots, payables, audit events and the idempotency reservation together.

Alembic revisions `7f58b276a2e0` and `bbf804720ca1` extend existing suppliers, purchases, batches, and stock movements. They add supplier-product associations, receipt cost lots, supplier ledger entries and immutable invoice batch allocations. The migration preserves existing invoices, preserves legacy batch counts, audits any medicine product count that differed from its batches, and appends opening reconciliation entries. Legacy supplier balances carry forward from received purchases. Existing historical quantities without reliable cost lots remain unvalued. Historical sales without recorded batch allocations keep their original receipts. Review legacy counts and duplicate supplier references against the source records before rolling out to a populated shop.

## API

Endpoints are under `/api/v1`. The authenticated web app proxies the same operations through `/api/inventory-ops`.

| Endpoints | Operations |
|---|---|
| `GET/POST /suppliers`, `GET/PUT /suppliers/{id}`, `GET /suppliers/{id}/ledger` | Search, edit, deactivate, track associations and supplier movements |
| `GET/POST /purchases`, `GET /purchases/{id}` | Search by order or supplier invoice and create drafts |
| `POST /purchases/{id}/{receive,payments,cancel,reverse}` | Idempotent receiving, supplier payment and compensation |
| `GET /inventory/batches`, `PUT /inventory/batches/{id}/state` | Expiry windows, batch detail, quarantine and release |
| `GET /inventory/movements`, `POST /inventory/adjustments` | Stock history, adjustments, damage, disposal and supplier returns |
| `GET /inventory/products/{id}/{units,valuation}`, `PUT /inventory/products/{id}/threshold` | Ordering units, valuation and low-stock control |
| `GET /catalog/products`, `GET /invoices/{id}/receipt` | Saleable catalog quantity and receipt batch snapshots |

## Verification

Run pytest against `shopflow_test`. After the Next.js production build, run `python ../../scripts/verify_purchasing.py` from the API directory with the API virtual environment and `PYTHONPATH` set. The runner verifies the database name, launches loopback servers, exercises two browser locales, and independently reconciles the resulting purchase, ledger, batch and receipt rows in PostgreSQL.

| Check | Result |
|---|---|
| Baseline PostgreSQL suite | 119 passed |
| Final PostgreSQL suite on `shopflow_test` | 129 passed, including expiry boundaries, rollback, receipt retries and concurrent checkout |
| Static and build checks | Ruff, OpenAPI contract generation, TypeScript, ESLint and Next.js production build passed |
| Purchasing browser check | English at 1440 px and Bangla at 375 px both passed. PostgreSQL confirmed 3 units received, 1 allocated to the saved invoice, 2 remaining and ৳52.00 payable in each workflow. |
| Receipt browser regression | Four viewport workflows passed, including 80 mm PDFs, Bengali font embedding, deterministic reprint and an 80-line stress receipt. |

Screenshots capture the partial-receipt state and the batch expiry list before checkout.

- English desktop [partial receipt](screenshots/p2e-en-1440-receiving.png) and [medicine batches](screenshots/p2e-en-1440-batches.png)
- Bangla mobile [partial receipt](screenshots/p2e-bn-375-receiving.png) and [medicine batches](screenshots/p2e-bn-375-batches.png)

## Remaining work

Known limitations include unvalued legacy stock, no automated gateway transfers or supplier refunds, and full purchase reversal only for unpaid, unused receipt lots. For the next phase, add supplier credit notes and payment refunds, partial purchase returns with explicit lot and financial links, and approved physical stocktakes.
