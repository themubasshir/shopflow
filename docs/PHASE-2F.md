# Phase 2F returns, refunds, and financial reconciliation

## Customer returns and tender

Use **Returns and refunds** on the saved invoice. An owner or manager with sales and inventory write access records the base-unit quantity for each original line and batch, the reason, and the stock disposition. Staff can return a full or partial quantity. The invoice, counter and customer come from the saved sale. The API rejects excess quantities, duplicate selections, and entries from another invoice or shop.

A return records the actor, time, immutable line amounts, and stock disposition. The original sale, discounts, invoice lines, tender records, and batch allocations stay in history. Returns reduce unpaid dues first. The existing customer statement records each reduction. The invoice's due projection, return credits, and gross collections reconcile to the original total. Completed and pending refunds both count against the amount collected.

Cash refunds complete on posting. bKash and Nagad create pending manual refund liabilities. Staff enter a unique payment reference for that shop and payment method after transferring the money separately. Confirmation is a second immutable record with its own actor and timestamp.

## Money and loyalty

Return amounts come from the saved invoice. Line discounts stay on their original lines. Invoice-level discounts are allocated across eligible lines first, then other lines. The loyalty discount is allocated across remaining eligible value. The service apportions stored amounts by cumulative share, rounded to cents in stable receipt order. A partial return posts the difference between the prior and new rounded values for the item. Legacy tax, where present, is apportioned by saved line value.

Restored redemptions use the cumulative returned share of the original loyalty discount. Whole points round down until later returns make up the remainder. Earn reversal uses the cumulative eligible value removed from the original award base and the original award count. When the retained sale becomes fully settled after a return, it earns on the retained eligible spend using the original saved policy. A reversal can make the account balance negative if previously earned points were spent on another invoice. Future awards reduce that deficit and normal redemption eligibility applies. Reversals and restored points append linked loyalty records and an audit event.

## Inventory and supplier credits

- Medicine defaults to quarantine in the original batch and, where known, original cost lot. Held quantities contribute to physical inventory and stock valuation and stay outside saleable stock. Direct restoration requires original stock traceability, staff verification, an active eligible batch, and expiry after the shop-local date.
- Damage and disposal post inbound and outbound movements with no net stock change. Held returns can be disposed of or staged and sent to the original supplier. Supplier staging requires an original purchase lot. A batch-wide quarantine flag does not release per-return held stock.
- Staff can send selected receipt lots back from the purchase view. Supplier credit notes cite a supplier document reference and an outgoing shipment on the original purchase. Each purchase and shipment supports one note. Its cap is the shipped share of the original lot cost, rounded down to cents per lot in the shipment.
- A new credit note creates a supplier refund receivable. Apply part or all of it to a payable from the same supplier or record money received with a cash, bKash, Nagad, or bank reference. Both operations draw from the same balance. Paired entries in the existing supplier ledger move credit to the target purchase. The original purchase amounts stay in history. Settlement uses the updated payable. Full reversal remains available for unpaid, uncredited purchases with intact, unheld lots.

## Reconciliation and permissions

Customer return processing reserves the idempotency key, locks the original customer where applicable, locks the invoice, locks product IDs in ascending order and their batches and lots, then locks the loyalty account. Confirmation locks the invoice. Supplier credit posting locks the purchase. Applications lock the credit note and then the target purchase. Refund receipts lock the credit note. Checkout and purchase intake continue to serialize stock on the product row. Failures roll back all linked ledgers and the idempotency reservation.

Financial reports show period sales and discounts, customer returns, net sales, collections, completed refunds, supplier credits and refunds, and loyalty events. Collections record when money arrived, including payments on older invoices. Customer dues, pending refunds, supplier payables, and supplier refund receivables are current balances. Date ranges use the shop timezone.

The reconciliation API is read-only. It compares invoice amounts and collections, customer dues and return credits, refund totals and confirmations, loyalty balances and return events, supplier balances and credit pairs, product and batch movements, sale and return allocations, lot quantities, and inventory valuation. It can filter by area and entity ID. Unambiguously traceable sale allocations can be compared against the exact batch movement. Authorization uses live sessions, original invoice scope, and elevated existing write permissions. Reports require unrestricted counter access.

## API

All paths are under `/api/v1`. Writes take `Idempotency-Key`.

| Method and path | Purpose |
|---|---|
| `GET/POST /invoices/{invoice_id}/returns` | Returnable quantities, return history, and new returns |
| `POST /invoices/{invoice_id}/returns/{return_id}/refund` | Confirm a pending manual refund |
| `POST /invoices/{invoice_id}/return-lines/{line_id}/disposition` | Dispose of or ship held stock |
| `POST /purchases/{purchase_id}/supplier-returns` | Ship original receipt lots |
| `GET/POST /purchases/{purchase_id}/credits` | List lots, shipments and credits, or record a credit |
| `POST /suppliers/{supplier_id}/credits/{note_id}/applications` | Apply credit to a same-supplier payable |
| `POST /suppliers/{supplier_id}/credits/{note_id}/refunds` | Record money received from a supplier |
| `GET /reports/financial` | Shop-local date-range financial report |
| `GET /reports/reconciliation` | Paginated discrepancy report |

## Migrations and limits

Alembic revision `de452fa8b713` adds append-only return, transfer confirmation, disposition, and supplier credit records, extends existing ledger links, and adds held-stock and due projections. It records historical loyalty opening balances for accounts whose complete history predates the ledger. `f8bcc76b2f43` scopes shipment credits to their purchases and indexes lot and batch movements. Rollback of posted changes requires a verified database backup.

Historical sales without exact stock provenance can be financially returned when invoice totals reconcile. The history flags their missing provenance, and staff handle the physical items separately. Legacy sales without a saved loyalty policy do not receive return-related point adjustments. Unknown lot costs remain unvalued. Payment-provider transfers, partial confirmations of a single refund, and spendable customer account credit are outside the current accounting model.

## Verification

Run the PostgreSQL pytest suite and build the frontend. From the API directory, run `../../scripts/verify_returns.py` with the API virtual environment's Python and `PYTHONPATH` set. The verifier checks the connected database is `shopflow_test`, starts loopback-only API and web servers, exercises both locales, and reconciles the resulting transactions directly in PostgreSQL.


| Check | Result |
|---|---|
| Baseline PostgreSQL suite | 129 passed |
| Full suite on shopflow_test | 140 passed |
| Static and build checks | Ruff for application, tests, scripts and new migrations, OpenAPI TypeScript generation, TypeScript, ESLint, and Next.js production build passed |
| Returns browser verification | English at 1440 px and Bangla at 375 px passed with no horizontal overflow |
| Thermal receipt regression | Four viewport workflows passed, with 80 mm PDFs, Bengali font embedding, deterministic reprints, and an 80-line receipt |
| Independent PostgreSQL reconciliation | Both browser workflows produced zero discrepancies across their invoice, return, loyalty account, product, batch, allocation, cost lot, purchase, and credit note |

For each browser workflow, the original ৳600 invoice retained ৳500 in recorded collections. A partial return of ৳200 reduced dues by ৳100, completed a ৳100 manually confirmed refund, restored 100 redeemed points, and awarded 4 points on the retained eligible spend. One unit went into quarantine at its original batch and lot. A separate ৳50 supplier credit applied ৳30 to the purchase payable and recorded ৳10 received, leaving ৳10 in available supplier credit.

The shop-wide reconciliation screenshots show 520 discrepancies in the shared test database at the time of capture. The report surfaced fixture and historical ledger differences without correcting them. The new transactions were verified against their own linked records.

| Screenshots | Return and pending refund | Supplier credit history | Financial report | Reconciliation |
|---|---|---|---|---|
| English desktop | [Return](screenshots/p2f-en-1440-refund-pending.png) | [Credit](screenshots/p2f-en-1440-supplier-credit.png) | [Report](screenshots/p2f-en-1440-financial.png) | [Discrepancies](screenshots/p2f-en-1440-reconciliation.png) |
| Bangla mobile | [Return](screenshots/p2f-bn-375-refund-pending.png) | [Credit](screenshots/p2f-bn-375-supplier-credit.png) | [Report](screenshots/p2f-bn-375-financial.png) | [Discrepancies](screenshots/p2f-bn-375-reconciliation.png) |
