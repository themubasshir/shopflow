# Thermal printer hardware acceptance test

This procedure signs off one physical printer before a shop relies on it. It is written for a person standing next to the device with an owner login and a terminal that can reach both the API and the printer. Every step records what was *observed*, not what the software reported.

Phase 2D-2/2D-3 verification proves the queue, claim protocol, render grant, rasterization and ESC/POS stream are correct, and that the decoded stream matches the canonical PDF. That is evidence about **bytes**, not about paper. Only this test produces evidence that paper came out.

## Three kinds of "printed"

Keep these apart in every record. They are not interchangeable, and a green job row only ever proves the first two.

| State | Meaning | Where it is visible | What it does **not** prove |
|---|---|---|---|
| Transport completed | The agent opened a TCP connection to the printer and wrote the whole stream without an error | `print_jobs.status = completed`, agent exit log | That the device printed anything: a powered-off printer with a buffered port can accept bytes |
| Printer-confirmed delivery | The device acknowledged the data it received (job completed after the transport returned) | `completed_at` on the job, agent summary line | That the paper path, head, or cutter worked |
| Physical completion (uncertain or certain) | A human looked at the paper | This checklist | Anything, unless the row is signed |

The agent reports `failed` with `error_code = transport_uncertain` when the transport throws. The queue then shows `failed` or, if the lease expired mid-stream, `uncertain`. Neither state is ever auto-retried. A job is only reprinted by an explicit reprint action, which creates a **new** job referencing the old one.

## Pre-flight

Record these before touching the UI:

- Printer make and model: `______________________`
- Serial number: `______________________`
- Paper: width `____ mm` (80 mm nominal), roll diameter `____ mm`
- Connection: `network` (LAN host `____________`, port `______`) or `bluetooth` (gateway id `____________`)
- Printable dot width: `______` dots (576 for an 80 mm / 203 dpi head)
- DPI: `______` (203 or 300)
- Cutter: yes / no
- Firmware version: `______________________`

Confirm on the device's self-test page (usually hold FEED while powering on) that the dot width and DPI match what you are about to enter. A wrong dot width prints a scaled receipt; a wrong DPI prints a receipt at the wrong physical size.

## Registration

1. Sign in as owner and open **Settings → Printers**.
2. **Add printer**. Fill name, model, connection type, LAN host and port (or Bluetooth gateway id), paper width, printable dot width, DPI, density, feed distance, cutter, and default language.
3. Save. Copy the agent token from the one-time dialog; it is never shown again. Rotating the token later invalidates the old one immediately.
4. Assign the counters that share this printer. Two counters may share one device; that is the normal setup.
5. Start the agent on a host that can reach the printer:

   ```bash
   shopflow-print-agent run --agent-id <agent_id> --token <token> --api <api_base> --web <web_base>
   ```

**Pass:** the agent logs an authenticated poll and no errors. **Fail:** any `unauthenticated`, `forbidden`, or "printer has no network config" — fix the registration before continuing.

## Test cases

Run them in order. Do not skip a failing case; later cases assume the earlier ones.

### 1. Initial connection

| | |
|---|---|
| Steps | Owner → Printers → **Test page** on the new printer. Watch the agent log and the device. |
| Expected | One calibration page prints within a few seconds, full width, both languages if the default is bilingual. The job reaches `completed`. |
| Record | Job id `__________` · printed: yes / no · notes: |

If nothing prints but the job says `completed`, the transport reached *something* — check the host/IP and that no other service holds port 9100. The job is not proof of paper.

### 2. English receipt

| | |
|---|---|
| Steps | Set the printer's default language to English. Open a saved invoice → **Send to printer**. |
| Expected | The whole receipt prints: shop header, invoice number, counter, cashier, items, totals, payments, footer. No clipped characters at either margin. |
| Record | Invoice `__________` · job `__________` · margins clean: yes / no |

### 3. Bangla receipt

| | |
|---|---|
| Steps | Set the default language to Bangla. Reprint the same invoice. |
| Expected | Bengali conjuncts and the taka sign render correctly. Nothing is replaced by boxes, `?`, or a cut glyph. The receipt is the same height as the English one (±1 line). |
| Record | Job `__________` · glyphs correct: yes / no · notes |

Boxes or `?` mean the raster path was bypassed (character mode) or the PDF font was not embedded — stop and report, do not ship.

### 4. Bilingual receipt

| | |
|---|---|
| Steps | Set the default language to English + Bangla. Reprint the same invoice. |
| Expected | Each label has its Bangla line directly below it. Long values (counter name, cashier, customer) wrap inside the printable width; no line touches the paper edge. The masked phone number sits on its own line under the customer name. |
| Record | Job `__________` · no edge contact: yes / no · longest line ended at `____ mm` of the paper |

Measure the paper width with a ruler. Text ending within 1–2 mm of the edge is a failure; the body should sit inside a ~4 mm gutter on each side.

### 5. Long receipt (80 line items)

| | |
|---|---|
| Steps | Print an invoice with at least 80 line items, bilingual. |
| Expected | The receipt prints as one continuous strip (the raster pipeline stitches PDF pages). No repeated header, no blank gap in the middle, no truncation at the end. The last line is the footer/return policy. |
| Record | Job `__________` · length `____ mm` · continuous: yes / no |

A gap or a repeated header means the page split was not stitched — report the invoice id.

### 6. Paper margins and alignment

| | |
|---|---|
| Steps | Hold the printout against a ruler; check both long edges and the top/bottom of the text block. |
| Expected | Left and right gutters are equal within 1 mm. No character is cut vertically by the head width. Raster text is not stretched or squashed (dot width matches the head). |
| Record | Left `____ mm` · right `____ mm` · stretched: yes / no |

### 7. Print density

| | |
|---|---|
| Steps | Print the same bilingual receipt at density 2, 4 and 7 (Printers → edit → density → save → reprint). |
| Expected | Density 2 is noticeably lighter but every glyph still legible; 4 is the neutral level; 7 is darker without bleeding or smearing. Existing queued jobs keep the density they were queued with. |
| Record | Light legible: yes / no · dark clean: yes / no · chosen level: `____` |

### 8. Cutting

| | |
|---|---|
| Steps | With the cutter enabled, print three receipts in a row. Then disable the cutter and print one. |
| Expected | With the cutter: a clean partial cut, paper still attached by a small tab, no tearing into the text. Without: the feed advances but the paper is not cut. |
| Record | Cut clean: yes / no · feed distance adequate: yes / no · chosen feed: `____` dots |

### 9. Paper out

| | |
|---|---|
| Steps | Queue a receipt with the roll removed (or the cover open). Observe the job and the device LED. |
| Expected | The job does not stay `pending` forever and is never silently reprinted. Depending on the device it ends `failed` (transport error) or `uncertain` (stream accepted, no paper). The owner can see the error and choose **Reprint**, which creates a new job. |
| Record | Status `__________` · error code `__________` · reprint created a new job: yes / no |

### 10. Network disconnection

| | |
|---|---|
| Steps | Unplug the printer's network cable (or power it off) and queue a receipt. Wait for the agent to report. Reconnect. |
| Expected | The job fails within the transport timeout with a clear error; the queue shows it. Reconnecting does **not** print the old job automatically. A deliberate reprint prints exactly one copy. |
| Record | Status `__________` · auto-printed on reconnect: yes / no (must be no) |

### 11. Agent restart mid-print

| | |
|---|---|
| Steps | Queue a long (80-item) receipt, then kill the agent process (`Ctrl+C`) while the paper is still feeding. Restart the agent. |
| Expected | The claim lease expires. If the job had reached `printing`, it becomes `uncertain` — never `pending` — because the device may have printed it. The restarted agent does not reprint it. The owner reprints explicitly if needed. |
| Record | Final status `__________` (expected `uncertain`) · restarted agent reprinted automatically: yes / no (must be no) |

### 12. Duplicate-print prevention

| | |
|---|---|
| Steps | Print one receipt and confirm it appears once. Leave the agent running for two minutes with no new jobs. Then press **Reprint** once on the completed job. |
| Expected | One copy from the first print, no extra copies while idle, exactly one new copy from the reprint. The queue shows two jobs: the original (`completed`) and the reprint (new id, `reprint_of_job_id` set). |
| Record | Copies after first print `____` · idle copies `____` (must be 0) · copies after reprint `____` (must be 1) |

### 13. Reprint authorization

| | |
|---|---|
| Steps | As a cashier, try to reprint a receipt from a counter you are not assigned to. Then ask the owner to do it. |
| Expected | The cashier is refused (403/404, nothing queued). The owner can reprint; a new job is created and audited. Printing never recreates the invoice or changes stock, payments, dues or loyalty. |
| Record | Cashier refused: yes / no · owner reprint job `__________` · invoice totals unchanged: yes / no |

### 14. Printer reassignment

| | |
|---|---|
| Steps | With a job queued to printer A, assign the counter to printer B. Then queue a new receipt. |
| Expected | The queued job still prints on A (its printer is part of the job). Only the new receipt goes to B. Counter codes and invoice history are unchanged. |
| Record | Old job printer `______` · new job printer `______` |

### 15. Deactivated printer

| | |
|---|---|
| Steps | Disable the printer in the UI while the agent is running and a job is queued. |
| Expected | The agent stops claiming (its credential is refused) and the queued job stays `pending`. Re-enabling lets the same job print, once. |
| Record | Agent refused: yes / no · job preserved: yes / no · printed once after enable: yes / no |

## Bluetooth

Bluetooth transport is **not implemented**. Registering a Bluetooth printer stores the gateway identifier and device address so the hardware inventory is complete, but the agent refuses to drive it with a clear error. Do not record a Bluetooth printer as accepted until a gateway implementation exists and passes this same checklist.

## Sign-off

| Field | Value |
|---|---|
| Printer | |
| Tester | |
| Date | |
| Receipt evidence (photos or PDFs) | |
| Accepted / rejected | |
| Open issues | |

Attach: a photo of the bilingual printout, the calibration test page, and the job ids from cases 1–5. Without the photo, physical completion is unproven.
