# Phase 2D-2 shared thermal printing

The shop can now send a saved invoice to one of several thermal printers over the network. The owner registers printers, routes counters to them, and a standalone local print agent claims queued jobs and streams ESC/POS to the device. The browser print and PDF download fallbacks from Phase 2D-1 remain available unchanged.

## What a shop configures

Owners register printers in **Settings → Printers**. Each printer carries a display name, transport type, host agent identifier, paper width, printable dot width, DPI, cutter capability, enabled status and a default receipt language. Many counters can share one printer, and a printer can serve many counters. Counters are assigned per counter row, so the owner decides which counters share a device. A counter with no assigned printer falls back to the shop's single enabled printer when only one exists. Counter codes are never renumbered, and historical print jobs keep their counter reference even after reassignment.

The owner can register a second printer through the management screen. Its agent credential is shown exactly once at creation; after that it is hidden and a token rotation issues a new one.

## Queue design

Printing is a first-class, append-only queue in PostgreSQL (`print_jobs`). A job is one physical print of one saved invoice, or a calibration test page (`kind = 'test_page'`). Fields: job id, invoice id (nullable), printer id, requesting user, counter id, receipt language, status, attempt count, created/completed timestamps, an error code and a sanitized error message. A job that is an explicit reprint records the prior job in `reprint_of_job_id`.

The queue is authoritative and strictly FIFO per printer. An agent claims the oldest pending job under a lease using `SELECT … FOR UPDATE SKIP LOCKED`, so two concurrent agents can never pull the same row. A claim that expires without a report returns the job to pending unless the agent had already moved it to `printing`, in which case the physical outcome is unknown and the job becomes `uncertain`. Uncertain jobs are never auto-reprinted; an intentional reprint creates a new job that references the invoice and the completed one. Job creation, retry, cancel and reprint are audited.

## Rendering

Receipts reuse the single deterministic 80 mm PDF engine from Phase 2D-1 — there is no second invoice template or calculation path. The agent fetches the canonical PDF for the saved invoice, rasterizes it with PyMuPDF to a grayscale pixmap calibrated to the printer's exact printable dot width, converts it to 1-bit monochrome packed MSB-first, and streams it as `GS v 0` raster bands followed by a feed and a partial cut when the device supports it. Bengali glyph shaping is preserved because the embedded PDF font is rasterized by MuPDF; no Unicode is ever sent to the printer, so the device only ever receives bitmaps. Printer width calibration and long-receipt strip banding are covered by the test suite.

## Agent architecture

`apps/agent` is a standalone `printagent` package (not `app`) so it never collides with the API's `app` package on `sys.path`. It has two CLI modes:

- `run` — the real agent. It authenticates with its own credential (independent of any cashier session), claims the oldest pending job for its printer, exchanges the job's one-time document token for a short-lived single-purpose render grant, fetches the canonical PDF from the web render route, rasterizes and streams ESC/POS to the transport, then reports printing → completed or a sanitized error.
- `simulate` — the same claim → render → raster → stream → report loop with an in-memory transport that records every byte, so the whole pipeline is exercised without hardware.

The agent polls the API with outbound, authenticated requests; it never listens on an inbound socket, so no raw printer port is exposed publicly. Each agent is scoped to its registered printer, and every claimed job is re-validated server-side before a document grant is issued.

## Transport support

Only the **network (Wi-Fi/LAN)** transport is implemented today, using raw TCP port 9100 — the de-facto ESC/POS socket. `BluetoothTransport` is a declared placeholder that raises a clear error until a dedicated Android-compatible host/gateway implementation and a real device test exist. The transport interface is separate from the queue and renderer, so Bluetooth can be added later without changing them. No Bluetooth capability is claimed without real hardware evidence.

## Security

- Agent authentication is independent of cashier sessions: each printer has an `agent_id` plus an argon2-hashed token that is revealed once at registration or rotation.
- An agent is scoped to its own printer; it cannot claim another printer's jobs or another shop's jobs.
- The agent never receives an arbitrary URL. It sends a one-time document token for a claimed job and receives a short-lived, single-purpose `type="render"` JWT bound to that job and invoice (or to a test page). The web layer renders via the one canonical route only.
- `PrinterOut` exposes no token and no transport `config`, so the credential never reaches staff-facing JSON.
- Every job creation, retry, cancellation and reprint is audited. Error messages stored on jobs are sanitized; no customer financial records are written to logs.

## API

Endpoints are under `/api/v1`. Staff enqueue receipts and test pages; owners manage printers and counter assignments.

| Endpoints | Operations |
|---|---|
| `GET/POST /printing/printers`, `PUT /printing/printers/{id}` | Register and edit printers |
| `POST /printing/printers/{id}/rotate-token`, `POST /printing/printers/{id}/test-page` | Issue a new agent credential, queue a calibration page |
| `PUT /printing/counters/{id}/printer` | Assign a counter to a printer (or none) |
| `GET/POST /printing/jobs`, `GET /printing/jobs/{id}` | List and enqueue print jobs |
| `POST /printing/jobs/{id}/{retry,reprint,cancel}` | Explicit recovery actions on a job |
| `POST /print/agent/{config,claim,document,report}` | Agent-facing claim, render-grant and outcome endpoints |

## Migrations

Alembic revision `04a62d5abb9c` adds `printers`, `counter_printers` and `print_jobs`, with a `kind` column on jobs (`invoice` | `test_page`), a nullable `invoice_id`, a `reprint_of_job_id` self-reference, and CHECK constraints enforcing that invoice jobs carry an invoice and test-page jobs do not. `shopflow_test` is migrated to `04a62d5abb9c`; `shopflow_dev` remains at `92eeb64fd2a9` and was not modified.

## Verification

Run the PostgreSQL pytest suite, build the frontend, then run `../../scripts/verify_printing.py` from the API directory with the API virtual environment's Python and `PYTHONPATH` set. The runner verifies the connected database is `shopflow_test`, clears printers left by earlier runs, starts loopback-only API and web servers, exercises the two-phase browser workflow, runs the real `printagent simulate` between phases, decodes the captured ESC/POS stream back to a bitmap, and reconciles everything against PostgreSQL.

| Check | Result |
|---|---|
| Full PostgreSQL suite on `shopflow_test` | 176 passed, including shared-printer FIFO, concurrent-claim protection, lease expiry, failed and uncertain jobs, explicit reprint, read-only financial safety, Bangla rasterization, width calibration and long-strip banding |
| Printing pytest module | 29 passed |
| Static and build checks | Ruff `check` and `format --check` clean; OpenAPI contract regeneration purely additive (no routes or schemas removed); TypeScript, ESLint (`--max-warnings=0`) and the Next.js production build passed |
| Browser printing workflow | English at 1440 px and Bangla at 375 px passed with no horizontal overflow |
| End-to-end print pipeline | The real agent claimed 2 queued jobs, completed both, and produced an ESC/POS stream decoded to a 576-dot-wide, 1269-dot-tall bitmap with a partial cut — **bit-identical to the canonical invoice PDF** over all 1269 rows |
| Migration round-trip | `04a62d5abb9c` downgrades to `f8bcc76b2f43` dropping all three tables, then re-applies with `kind` NOT NULL, nullable `invoice_id` and all five CHECK constraints |
| Earlier-phase regression | Receipt (4 viewports, 80-line receipt), returns (both locales, zero scoped discrepancies) and purchasing (both locales) browser suites all pass against the modified invoice and settings pages |

The captured stream (`escpos-stream.bin`) decodes to `printed-page.png`, which preserves Bengali shaping and is the physical-printing evidence available without a device.

| Screenshots | Printer management | Invoice queue | Bangla mobile | Decoded print |
|---|---|---|---|---|
| English desktop | [Printers + queue](screenshots/p2d2-printers-1440.png) | [Receipt queued](screenshots/p2d2-invoice-1440.png) | — | [Printed page](screenshots/printed-page.png) |
| Bangla mobile | [Printers](screenshots/p2d2-printers-bn-375.png) | — | — | — |

## Limitations and the hardware test checklist

The verification above proves the queue, claim protocol, render grant, rasterization and byte stream are correct, and that the printed page is bit-identical to the canonical document. It does **not** prove a physical printer works — the simulated transport records bytes instead of reaching a device.

Before a shop relies on a real printer, complete this checklist:

1. Register a real printer with its actual host/IP, port 9100, paper width and dot width, and rotate its agent token once through the UI.
2. Run `shopflow-print-agent run --agent-id <id> --token <token> --api <api> --web <web>` on a host that can reach both the API and the printer.
3. Send a **Test page** and confirm the physical page prints fully and cuts.
4. Send a saved invoice and confirm the full receipt prints without clipping and with correct Bengali glyphs.
5. Test with the printer off / unplugged to confirm the job reports `uncertain` or `failed` and is never silently reprinted.
6. Confirm a `bluetooth`-type printer reports a clear "not implemented" error until the dedicated host transport is built and device-tested.
