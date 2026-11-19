export const receiptLanguages = ["en", "bn", "bilingual"] as const;
export type ReceiptLanguage = typeof receiptLanguages[number];

export function receiptLanguage(value: string | null | undefined, fallback: ReceiptLanguage = "en"): ReceiptLanguage {
  return receiptLanguages.find((language) => language === value) ?? fallback;
}

export const paperWidthMm = 80;
export const cssPixelsPerMm = 96 / 25.4;

/**
 * Tallest page a single PDF sheet may use. Chromium and the PDF format both
 * stop at 200 in (5080 mm), so anything longer is split at this boundary and
 * the raster pipeline stitches the sheets back into one continuous strip.
 */
export const receiptPageLimitMm = 4800;

/** Height of the rendered receipt content in millimetres. */
export function receiptContentHeight(pixelHeight: number) {
  return Math.max(30, Math.ceil(pixelHeight / cssPixelsPerMm) + 2);
}

/**
 * Page height for the print stylesheet. A receipt that fits on one sheet keeps
 * its exact dynamic height; a longer one uses several sheets of this height so
 * no content is dropped and no sheet exceeds the PDF limit.
 */
export function receiptPageHeight(pixelHeight: number) {
  return Math.min(receiptContentHeight(pixelHeight), receiptPageLimitMm);
}

export function printablePageRule(heightMm: number) {
  return `@page { size: ${paperWidthMm}mm ${heightMm}mm; margin: 0; }`;
}
