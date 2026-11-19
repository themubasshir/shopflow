# Phase 2D-1 thermal receipts

## Flow

Bill finalization continues to use the existing checkout transaction. It also stores the receipt identity, item labels, order and sale-time loyalty balance inside that transaction. The billing success screen links to the saved invoice. Staff can also find it by invoice number from Billing → Invoice history or open it from a customer’s invoice history.

FastAPI reads the canonical receipt from PostgreSQL in one statement. Next.js uses one standalone HTML template for the browser preview, the browser print dialog and the server-rendered PDF. The print document contains the receipt alone. English, Bangla and compact bilingual modes use the same stored values. Bilingual mode places the alternate name or label alongside or below the primary one.

Printed receipts use black text on white, tabular numbers, full-width wrapping item names, and right-aligned amounts. Units, line discounts, batch numbers and expiry dates appear when the invoice has those details. The roll is 80 mm wide and the owner can configure 58–76 mm of printable content. Amounts are formatted from persisted Decimal strings and each line uses its saved quantity, unit price and line total.

## Invoice snapshots and legacy data

| Data | Source |
|---|---|
| Shop branding, width, default language, cashier, counter and customer labels | Sale-time invoice snapshot |
| Item names and selling units | Sale-time line snapshot with original row order |
| Medicine batch and expiry | Snapshot captured when a matching medicine batch is recorded on the invoice line |
| Invoice amounts, discounts, tax, payment methods and current dues | Persisted invoice and payment records |
| Closing loyalty points | Latest invoice-linked immutable loyalty transaction, with the stored checkout balance as fallback |
| Void and refund status | Saved lifecycle status, plus void timestamp when recorded |

Alembic revisions `6fd2b56f1403` and `2f374de4f27c` preserve existing invoices. Migration recovers saved customer names and balances from historical checkout results when available. It freezes the shop’s migration-time branding and available linked batch details with a visible legacy note. Missing historical labels, unit names and phone numbers remain blank. The original invoice descriptions, prices and totals remain authoritative.

A reprint stays reproducible after catalog, customer and shop edits. A later due collection legitimately changes collected and outstanding totals. An invoice-linked award after settlement can update the printed closing points. The PDF stays byte-stable for the same receipt and language on the same renderer version.

## Endpoints and access

| Method and path | Purpose |
|---|---|
| `GET /api/v1/invoices?printable=true&q=…` | Search the existing counter-scoped invoice history |
| `GET /api/v1/invoices/{invoice_id}/receipt` | Saved invoice detail and canonical receipt JSON |
| `GET /api/invoices/{id}/receipt?lang=en` | Authenticated, standalone HTML preview |
| `GET /api/invoices/{id}/receipt?lang=bn&format=pdf` | Authenticated PDF attachment |
| `GET/PUT /api/v1/settings/receipts` | Owner receipt settings |
| `PUT /api/settings/receipts` | Same-origin settings update through the web app |

Receipt endpoints require a live staff session and `sales:read`. Invoice lookups use the caller’s shop and enforce assigned counters for cashiers. Settings require the owner role and `settings:write`. Printed customer identity is limited to names and masked mobile digits. References, email and addresses stay out of the receipt. The template escapes settings and item text and the HTML endpoint serves a restrictive Content Security Policy. Preview, download and reprint are read-only. They have no checkout, stock, payment, due or loyalty side effects.

## PDF engine and font

The Node.js route uses the installed Playwright Chromium runtime. Chromium renders the same authenticated template with its print media rules, with no external resource requests. It measures the laid-out content to choose page height and wraps long item names. The server serves PDFs with browser-generated headers and footers off. A small pdf-lib pass normalizes each page box to exactly 80 mm and fixes the metadata timestamps to the invoice date. Normal receipts use a single dynamic-length page. Receipts beyond the 4,800 mm single-page cutoff use 250 mm pages with item blocks kept together where possible. The server reuses one browser process and caps concurrent renders at four.

The bundled [Noto Sans Bengali](https://github.com/google/fonts/tree/main/ofl/notosansbengali) regular and bold faces are static instances of the upstream variable font, distributed under the SIL Open Font License. The HTML and PDF render path embed the local font, including Bengali shaping and the taka sign. There is no external font fetch in the receipt renderer.

Run `npx playwright install chromium` from `apps/web` on a new host. On Linux, install Chromium’s system dependencies using the matching Playwright tooling. Keep the bundled font with the Next.js server files. Apply both Alembic migrations before starting the API. Receipt settings writes use the existing production `SHOPFLOW_WEB_ORIGIN` configuration.

## Checks

Run the full API suite against `shopflow_test`, then the browser suite separately because the auth regression tests revoke seeded staff sessions. After `npm run build`, run `python ../../scripts/verify_receipts.py` from `apps/api` with the API virtual environment and `PYTHONPATH` set. The runner starts loopback-only API and web servers, checks the connected database name, and writes evidence to `.local/receipt-evidence` by default.

| Gate | Result |
|---|---|
| Baseline PostgreSQL suite | 112 passed |
| Full suite after both migrations on `shopflow_test` | 119 passed |
| Ruff lint and changed Python file formatting | Passed |
| TypeScript, ESLint and Next.js production build | Passed |
| Playwright on the production build | Passed at 375, 414, 768 and 1440 px |
| PDF dimensions, embedded fonts and deterministic download | Passed |
| Independent Poppler raster and pypdf checks | Passed |

The browser suite covers a real cashier checkout, a search and reprint of the same invoice, English, Bangla and bilingual previews, owner settings, and a partial-payment receipt with a fractional grocery quantity and a long medicine name. The PDF checks verified 80 mm width and dynamic heights of 143 mm, 202 mm and 2,181 mm. The long bilingual sample contains 80 line items and one page. Poppler images were checked for glyphs, alignment and clipping, including the beginning, middle and end of the long receipt.

- [English mobile preview](screenshots/p2d1-en-375.png)
- [Bangla mobile preview](screenshots/p2d1-bn-414.png)
- [Bilingual tablet preview](screenshots/p2d1-bilingual-768.png)
- [English desktop preview](screenshots/p2d1-en-1440.png)
- [English PDF](../output/pdf/shopflow-receipt-en.pdf)
- [Bangla PDF](../output/pdf/shopflow-receipt-bn.pdf)
- [80-line bilingual PDF](../output/pdf/shopflow-receipt-bilingual-long.pdf)

## Limitations and Phase 2D-2

Existing checkout records invoice-level tax totals and applied discounts. Separate manual or rounding adjustments and refund tender details have no persisted source in the current schema. Receipts show the recorded financial fields and lifecycle state. Checkout currently leaves the medicine batch unset unless a sale line has an explicit batch assignment.

Browser print drivers control margins, head/tail feeds, paper length and scaling. The downloaded PDF carries exact page dimensions. Browser printing uses the receipt-only document and requests its paper size. Physical drivers may apply their own page settings. Firmware Unicode support is device-specific.

For Phase 2D-2, begin with a local print agent or supported printer SDK. Register the printer per counter and save its calibrated printable dot width, DPI and cut capability. Render each receipt to a monochrome image at that resolution so Bangla shaping stays intact across firmware. Send printer-model-supported raster bands and verify margins, cutter, paper-out recovery and long receipts on physical devices. Keep print job retries separate from billing and deduplicate each queued job. [Epson raster graphics reference](https://download4.epson.biz/sec_pubs/pos/reference_en/escpos/gs_lparen_cl_fn112.html)
