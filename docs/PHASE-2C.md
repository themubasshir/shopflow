# Phase 2C customer accounts, loyalty and dues

## Customer accounts

- The primary name is required and can be entered in English or Bangla. The optional Bangla name is preferred in the Bangla UI. Search matches both names and mobile numbers.
- New customers need a Bangladeshi mobile number. Local, international, formatted and Bangla-digit variants normalize to `+8801XXXXXXXXX`. The database enforces uniqueness within each shop, including inactive customers.
- Migration `c493c5806cb7` normalizes recognized legacy mobile numbers. Unrecognized or missing legacy values remain available in history. A collision between legacy numbers aborts the migration for manual account reconciliation.
- Deactivation prevents new sales for that customer. Profiles, invoices, points and payment history remain visible to authorized staff, and staff can still collect the customer's dues. Staff can reactivate the account.
- A credit limit of zero means unlimited. A positive limit caps total outstanding debt after the sale, across all counters. Lowering a limit leaves existing debt intact and can block new credit sales.

## Checkout and loyalty

- Existing `POST /api/v1/invoices` clients can keep omitting the new fields. `allow_due: true` explicitly enables an unpaid amount. `redeem_points` defaults to zero. An omitted amount on a single payment still covers the full server-calculated total. Explicit payments must use cash, bKash or Nagad. A due-only or fully redeemed zero-payable sale can send an empty payment array. Walk-ins and legacy customers without a mobile number cannot buy on credit.
- The API calculates prices and stock from the sellable units. A product and its category must both be eligible for loyalty. Line discounts reduce that line's eligible spend. An invoice-level discount reduces eligible spend first, down to zero. Redemption reduces the eligible amount again. The response's `discount_total` includes line and invoice discounts. `loyalty_discount` is separate.
- The account must open checkout with at least 300 points. It can redeem multiples of 100 up to the locked balance and remaining eligible amount, at ৳1 per point. Checkout measures the opening balance before awarding new points. A redemption above half the bill or covering the full bill is allowed if eligible. Points have no expiration.
- The v1 terms are fixed to the confirmed policy. Each qualifying invoice stores the effective rules, the matching active rule ID when one exists, and the eligible amount after manual discounts and redemption. Settlement uses the saved values even after products, categories or configuration change.
- Every ৳100 of eligible net spending earns one whole point once the invoice is fully settled. Full payment qualifies at checkout. Partial payments earn once the final collection brings due to zero. Legacy invoices lack a sale-time snapshot and receive no additional award on settlement. Historical opening point balances can predate the transaction history.
- Redemption writes an applied redemption and a signed negative loyalty transaction. Earn entries are positive. PostgreSQL prevents updates, deletes and truncation of posted loyalty entries. Issuing returns and reversing their awards is future work. That workflow needs to record a reversal for the original award and define what happens if the points have already been spent.

## Due accounting

- Invoice lifecycle status remains `finalized` for a committed sale. Payment status is `paid` when due is zero, `partially_paid` when paid and due are positive, or `due` when the full amount is outstanding.
- The account statement uses signed, append-only `customer_ledger_entries`. Checkout posts the unpaid portion once as a positive entry. Each collection creates a payment and a negative entry for the same invoice. Payment history includes checkout tenders and collections. The statement records receivable movements, so fully paid checkout has no statement entry.
- The account balance is the database sum of ledger entries. The invoice stores its paid/due totals as a projection, checked against the invoice ledger at collection. PostgreSQL constrains new finalized invoices to `paid_total + due_total = total`. The migration carries forward each existing finalized customer invoice's unpaid amount.
- Collection is allocated to a specific invoice. A payment above its outstanding amount is rejected. There is no customer prepayment, credit balance, transfer or payment-gateway integration. Cash, bKash and Nagad entries are records of tender received by staff.

## API and access

| Endpoint under `/api/v1` | Purpose |
|---|---|
| `GET /customers?q=&active=&limit=&offset=` | Shop-scoped lookup by phone or name |
| `POST /customers`, `GET/PATCH /customers/{id}` | Create, view, edit, deactivate or reactivate |
| `GET /customers/{id}/invoices`, `/payments` | Paginated invoice and payment history |
| `GET /customers/{id}/balance`, `/statement` | Outstanding balance and paginated statement with running balance |
| `GET /customers/{id}/loyalty`, `/loyalty/transactions` | Current points and eligibility, and paginated point movements |
| `POST /customers/{id}/invoices/{invoice_id}/payments` | Invoice-specific due collection with `Idempotency-Key` |
| `POST /invoices` | Atomic stock, receipts, redemption and any new debt |
| `GET /loyalty/accounts` | Existing paginated loyalty overview, including optional Bangla name |

Customer writes require `customers:write`. Checkout requires `sales:write` and an allowed counter. Redemption also requires `loyalty:write`. Customer financial histories and statements require `reports:read` and unrestricted counter access, with the relevant customer, sales or loyalty read permission. Collection additionally requires `sales:write`. Cashiers can look up a customer's current points and accept full or credit checkout at assigned counters. Customer balances, credit limits, email addresses and histories are restricted. The unsigned demo fallback is opt-in for seeded demo shops in development and test, with read permissions only. Customer and invoice data endpoints require a live staff session.

Next.js checks the exact `Origin` on every browser API write, including login, logout and staff administration. Production requires `SHOPFLOW_WEB_ORIGIN` to match the public origin exactly, including scheme and any non-default port. Development can infer the local origin. The API uses bearer authentication for these operations. Non-development/test API startup rejects demo mode, debug mode and short or placeholder signing keys.

## Transaction order and retries

Both writes reserve the shop-local idempotency key first. PostgreSQL's unique index serializes requests using the same key. A replay returns the original response with the original invoice, item and payment IDs. Reusing a key with changed request details returns HTTP 409. Checkout and collection both update the response record before the same commit that posts their financial effects.

The global lock order is idempotency reservation, customer, existing invoice, product rows in ascending ID order, loyalty account, then the daily invoice number sequence. Each operation skips rows outside its scope. Checkout holds the customer lock while checking the credit limit. Collection holds it while validating the invoice and posting payment. The existing invoice number format and UTC date rollover are preserved. Posted receivable entries and point entries are append-only. The browser keeps the request key and exact payload while a checkout or collection is awaiting a retry. After a page reload, staff can check account history for the original operation.

## Migration and delivery

`c493c5806cb7` extends the existing Alembic chain. It adds customer Bangla names, a product eligibility flag, invoice loyalty snapshots, loyalty posting order and the receivables ledger, and updates invoice and signed-point constraints. New constraints on finalized invoice totals and discount limits apply to future writes. Historical invoices are preserved. The downgrade refuses to discard recorded Phase 2C loyalty or collection history.

Migrate with `alembic upgrade head` before running the updated API. Development verification uses PostgreSQL `shopflow_test`. See [verification results](TESTING.md#phase-2c--customer-accounts-loyalty-and-dues).
