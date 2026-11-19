import { chromium, type Browser } from "playwright";
import { PDFDocument } from "pdf-lib";
import { paperWidthMm, printablePageRule, receiptContentHeight, receiptPageHeight } from "./paper";

let browserPromise: Promise<Browser> | undefined;
let activeRenders = 0;

function getBrowser() {
  browserPromise ??= chromium.launch({ timeout: 12_000 }).then((browser) => {
    browser.once("disconnected", () => { browserPromise = undefined; });
    return browser;
  }).catch((error: unknown) => {
    browserPromise = undefined;
    throw error;
  });
  return browserPromise;
}

/**
 * Normalize every sheet's page boxes to exact millimetres.
 *
 * Chromium rounds paper bounds to printer pixels, so the boxes are rewritten.
 * A receipt taller than one sheet is split at `height`, and only the last sheet
 * carries the remainder: Chromium fills a page from its top edge, so the
 * trailing blank is removed by raising the box's lower edge. Shrinking from the
 * origin instead would cut the *first* lines of that sheet and silently drop
 * rows from the printed receipt.
 */
export function normalizeSheetBoxes(pdf: PDFDocument, contentMm: number, heightMm: number) {
  const width = paperWidthMm * 72 / 25.4;
  for (const [index, sheet] of pdf.getPages().entries()) {
    const full = sheet.getSize().height;
    const remainder = Math.min(heightMm, Math.max(1, contentMm - index * heightMm)) * 72 / 25.4;
    const crop = remainder >= full - 0.5 ? 0 : full - remainder;
    sheet.setMediaBox(0, crop, width, full - crop);
    sheet.setCropBox(0, crop, width, full - crop);
  }
}

export async function renderReceiptPdf(markup: string, issuedAt: string | null) {
  if (activeRenders >= 4) throw new Error("Receipt PDF renderer is busy");
  activeRenders++;
  try {
    const browser = await getBrowser();
    const context = await browser.newContext({ serviceWorkers: "block", javaScriptEnabled: false });
    try {
      const page = await context.newPage();
      page.setDefaultTimeout(10_000);
      await page.route("**/*", (route) => route.abort());
      await page.emulateMedia({ media: "print" });
      await page.setContent(markup, { waitUntil: "load" });
      const pixels = await page.evaluate(async () => {
        await document.fonts.ready;
        return document.querySelector("main")!.getBoundingClientRect().height;
      });
      const content = receiptContentHeight(pixels);
      const height = receiptPageHeight(pixels);
      await page.locator("#print-page").evaluate((style, rule) => { style.textContent = rule; }, printablePageRule(height));
      const result = await page.pdf({ preferCSSPageSize: true, displayHeaderFooter: false });
      const pdf = await PDFDocument.load(result, { updateMetadata: false });
      const timestamp = new Date(issuedAt ?? 0);
      pdf.setCreationDate(timestamp);
      pdf.setModificationDate(timestamp);
      normalizeSheetBoxes(pdf, content, height);
      return await pdf.save();
    } finally {
      await context.close();
    }
  } finally {
    activeRenders--;
  }
}
