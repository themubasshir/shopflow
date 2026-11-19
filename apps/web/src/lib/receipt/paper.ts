export const receiptLanguages = ["en", "bn", "bilingual"] as const;
export type ReceiptLanguage = typeof receiptLanguages[number];

export function receiptLanguage(value: string | null | undefined, fallback: ReceiptLanguage = "en"): ReceiptLanguage {
  return receiptLanguages.find((language) => language === value) ?? fallback;
}

export const paperWidthMm = 80;
export const cssPixelsPerMm = 96 / 25.4;

export function receiptPageHeight(pixelHeight: number) {
  const height = Math.max(30, Math.ceil(pixelHeight / cssPixelsPerMm) + 2);
  return height <= 4800 ? height : 250;
}

export function printablePageRule(heightMm: number) {
  return `@page { size: ${paperWidthMm}mm ${heightMm}mm; margin: 0; }`;
}
