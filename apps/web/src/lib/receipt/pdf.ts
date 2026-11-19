import { chromium, type Browser } from "playwright";
import { PDFDocument } from "pdf-lib";
import { paperWidthMm, printablePageRule, receiptPageHeight } from "./paper";

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
      const height = receiptPageHeight(pixels);
      await page.locator("#print-page").evaluate((style, rule) => { style.textContent = rule; }, printablePageRule(height));
      const result = await page.pdf({ preferCSSPageSize: true, displayHeaderFooter: false });
      const pdf = await PDFDocument.load(result, { updateMetadata: false });
      const timestamp = new Date(issuedAt ?? 0);
      pdf.setCreationDate(timestamp);
      pdf.setModificationDate(timestamp);
      for (const sheet of pdf.getPages()) {
        // Chromium rounds paper bounds to printer pixels. Normalize the PDF page boxes to exact millimetres.
        sheet.setSize(paperWidthMm * 72 / 25.4, height * 72 / 25.4);
      }
      return await pdf.save();
    } finally {
      await context.close();
    }
  } finally {
    activeRenders--;
  }
}
