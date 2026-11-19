# Phase 2D-3 receipt polish and hardware readiness

This phase fixes the bilingual receipt layout at its root cause, strengthens long-receipt handling, and prepares the real-printer integration surface: printer hardware profiles in the UI and API, a raster density/feed calibration, and a repeatable hardware acceptance procedure. All work is committed locally; nothing was deployed and no financial calculation changed.

## The clipped counter line — root cause

The reported defect was that the `C1 · Counter 1 / কাউন্টার ১` line looked clipped on the bilingual receipt. Measured against the committed canonical PDF, the Bangla value ended at 75.82 mm of ink — 4.18 mm clear of the paper edge — so **nothing was actually overflowing**. The real defect was in the label/value row layout:

```css
.pair{grid-template-columns:minmax(0,1fr) auto}   /* label is a greedy full-width track */
.pair>:last-child{text-align:right;max-width:43mm} /* value is a shrink-to-fit box, capped */
```

The label column claimed the whole 72 mm row regardless of its own text width, and the value column shrank to its contents and was capped at 43 mm. For a bilingual value — English line plus a block-level Bangla translation — that squeezed the value into a narrow right-aligned column where the Bangla wrapped hard against the label's invisible boundary, reading as truncation even though the glyphs were on the page.

The fix is flexbox, because neither grid nor a max-content flex basis expresses "shrink to text, capped":

```css
.pair{display:flex;gap:1.5mm;align-items:baseline}
.pair>dt{flex:0 0 auto;max-width:52%}           /* label: its own text width, never over half the row */
.pair>:last-child{flex:1 1 0;min-width:0;text-align:right} /* value: exactly the leftover width */
```

Two intermediate attempts failed for opposite reasons and the record is worth keeping. `minmax(0,52%)` makes the label a fixed 52%-wide track — the mirror image of the original defect. `flex:1 1 auto` on the value gives it a max-content basis, which starves the *label* on long-name receipts (the counter label wrapped mid-word, "Count/er"). `flex:1 1 0` makes the value own only the space the label leaves, which is correct in both directions.

Supporting layout changes: `detail()` now puts secondary metadata (masked phone, counter code) on its own `.sub` line instead of appending it inline after a block-level translation, where the separator used to dangle at the start of a line.

## Long receipts — the split-sheet bug

`verify_receipts.py` now prints a 200-item bilingual receipt. That exposed a real data-loss bug in `pdf.ts`: after Chromium paginates a receipt taller than one sheet, the normalization step resized every page's box from the PDF coordinate origin — the **lower-left** corner. Chromium lays content out top-down, so shrinking the last sheet from the origin cropped its *top* lines: 64 of 200 items (items 232–295) silently vanished from sheet 2, in a PDF that still looked plausible.

The fix is `normalizeSheetBoxes(pdf, contentMm, heightMm)`, which keeps each sheet's top edge and raises its lower edge by `crop = full − remainder`, on both MediaBox and CropBox. A probe confirmed Chromium itself paginates correctly to at least 20 000 mm of content at any page size — only the pdf-lib normalization dropped rows.

Also fixed: `receiptPageHeight` now caps at `receiptPageLimitMm = 4800` (Chromium and PDF both stop near 5080 mm). Previously an over-limit receipt silently fell back to a 250 mm page height, exploding a 200-item receipt into ~35 sheets instead of 2.

## Printer hardware profile

Printers now carry the fields a real deployment needs, on top of the Phase 2D-2 queue:

- `device_model` (free text, shown on the printer card), `density` (1–8, default 4), `feed_dots` (0–255, default 90), and a `capabilities` JSONB flag pair `{raster, character}`.
- `print_jobs` snapshots density and feed distance at enqueue time so a mid-flight profile edit never changes a queued job's bytes.
- `capabilities.raster = false` is refused: the agent's pipeline is raster-only, and registering a character-only device would claim a capability that does not exist. `capabilities.character` is recorded as information only.
- Density is implemented in the rasterizer as `density_threshold(level)`, mapping 1–8 to a bounded 80–200 threshold. **Level 4 reproduces the previous bytes exactly** — a test asserts `pdf_to_escpos(...)` with `density_threshold(4)` equals the default stream byte-for-byte. Lighter and darker levels produce provably different rasters at identical band geometry; feed distance only changes the `ESC d` parameter before the cut.
- The settings form collects model, connection, host/port or gateway id, dot width, DPI, cutter, density and feed. Connection config is validated per transport server-side; the UI only re-sends `config` when the operator retypes it.

## Verification

| Check | Result |
|---|---|
| Full PostgreSQL suite on `shopflow_test` | 186 passed, including 39 printing tests (hardware profile, density-threshold mapping, feed/density stream diffs, snapshots) |
| Static and build checks | Ruff `check` and `format --check` clean; TypeScript `tsc --noEmit`, ESLint `--max-warnings=0`, and the Next.js production build all pass |
| Receipt browser suite | 4 viewport workflows pass; exact 80 mm PDFs, embedded Bengali font, deterministic reprint |
| Layout guard | Asserts every `.pair` row: the label is no narrower than its own text cap (starved) and never over 52% of the row (greedy), the value owns all leftover width, and nothing leaves the 72 mm body. Re-running the suite with the pre-fix template restored makes the guard fail loudly on every `.pair` row — the check is proven sensitive, not decorative |
| Long-name stress | Live bilingual markup re-rendered with a long bilingual counter name, cashier name, and customer name: values wrap predictably inside the body, labels stay intact, `shopflow-receipt-long-names.pdf` is produced as evidence |
| PDF margin + split check | 1462 spans across 5 sheets in 4 receipts: max ink edge 76.08 mm inside the 76 mm printable limit; no sheet ends in a blank tail over 60 mm |
| Long receipt | 200 line items across 2 sheets (4800 mm + 3157 mm), every "Thermal sample NN" present exactly once, every sheet filled |
| Printing pipeline | 3 queued jobs (test page + 2 receipts) complete; explicit reprint linked to the original; ESC/POS decoded to a 576-dot, 1269-dot-tall bitmap — **bit-identical to the canonical invoice PDF** over all 1269 rows, partial cut, 4 raster bands |

| Evidence | |
|---|---|
| Counter/value rows after the fix | [p2d3-counter-row.png](screenshots/p2d3-counter-row.png) |
| Long bilingual names wrapping correctly | [p2d3-long-names.png](screenshots/p2d3-long-names.png) |
| Printer card with hardware profile | [p2d3-printers-1440.png](screenshots/p2d3-printers-1440.png) |
| Bilingual receipt, 768 px | [p2d3-bilingual-768.png](screenshots/p2d3-bilingual-768.png) |

## Hardware readiness

`docs/PRINTER-HARDWARE-TEST.md` is a repeatable 15-case acceptance procedure for signing off a physical device: initial connection, English/Bangla/bilingual receipts, the 80-item long receipt, margins, density sweep, cutting, paper-out, network drop mid-job, agent restart mid-job, duplicate-prevention, and reprint authorization. It keeps three states strictly apart — **transport completed** (bytes left the host), **printer-confirmed delivery** (the job completed), and **physical completion** (a human looked at paper) — because a green `print_jobs` row only ever proves the first two.

## Limitations

- No physical printer has been tested. The decoded ESC/POS stream is bit-identical to the canonical PDF, but that is evidence about bytes, not paper. The hardware checklist must be completed before a shop relies on a device.
- Bluetooth remains a declared placeholder that raises a clear error; only the network transport exists. The `bluetooth` gateway id field exists for registration forward-compatibility, not because Bluetooth printing works.
- Density is a raster threshold, not a printer darkness command — it changes which pixels burn, which is the honest raster analogue but can differ slightly from a device's built-in density setting.
- The `uncertain` job state still requires human judgement by design; nothing auto-reprints.
