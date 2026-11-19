import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { chromium } from "playwright";
import { PDFDict, PDFDocument, PDFName } from "pdf-lib";

const [origin, fixtureFile, screenshots, pdfs] = process.argv.slice(2);
assert.match(origin ?? "", /^http:\/\/127\.0\.0\.1:\d+$/);
const data = JSON.parse(await readFile(fixtureFile, "utf8"));
await Promise.all([mkdir(screenshots, { recursive: true }), mkdir(pdfs, { recursive: true })]);

const browser = await chromium.launch();
const browserErrors = [];
const buttons = (page, name) => page.getByRole("button", { name, exact: true });
const expectedWidth = 80 * 72 / 25.4;

async function login(context, user) {
  const page = await context.newPage();
  page.on("pageerror", (error) => browserErrors.push(error.message));
  await page.goto(origin + "/en/login");
  await page.getByLabel("Email").fill(user + "@shopflow.dev");
  await page.getByLabel("Password").fill("ShopFlow#Dev123");
  await buttons(page, "Sign in").click();
  await page.waitForURL(origin + "/en");
  return page;
}

async function sale(context, body) {
  const response = await context.request.post(origin + "/api/billing/invoices", {
    headers: { Origin: origin, "Idempotency-Key": randomUUID() },
    data: { counter_id: data.counter, ...body },
  });
  assert.equal(response.status(), 201, await response.text());
  return response.json();
}

const receiptUrl = (id, language, format = "html") =>
  origin + "/api/invoices/" + id + "/receipt?lang=" + language + "&format=" + format;

async function inspectPdf(bytes) {
  const pdf = await PDFDocument.load(bytes, { updateMetadata: false });
  assert.equal(pdf.getPageCount(), 1);
  const { width, height } = pdf.getPage(0).getSize();
  assert.ok(Math.abs(width - expectedWidth) < 0.00001);
  const embedded = pdf.context.enumerateIndirectObjects().some(([, object]) =>
    object instanceof PDFDict && /NotoSansBengali/.test(String(object.get(PDFName.of("FontName"))))
      && (object.has(PDFName.of("FontFile2")) || object.has(PDFName.of("FontFile3"))),
  );
  assert.ok(embedded, "Expected the Bengali font program in the PDF");
  return { width, height };
}

async function download(page, buttonName, path) {
  const job = page.waitForEvent("download");
  await buttons(page, buttonName).click();
  const file = await job;
  assert.equal(await file.failure(), null);
  await file.saveAs(path);
  return readFile(path);
}

async function verifyPrint(page, label) {
  const frame = page.frames().find((child) => child.url().includes("/api/invoices/"));
  assert.ok(frame);
  await frame.evaluate(() => {
    window.print = () => { document.documentElement.dataset.printed = "yes"; };
  });
  await buttons(page, label).click();
  const printed = await frame.evaluate(() => ({
    called: document.documentElement.dataset.printed,
    pageRule: document.getElementById("print-page").textContent,
  }));
  assert.equal(printed.called, "yes");
  assert.match(printed.pageRule, /size: 80mm [0-9]+mm/);
}

try {
  const owner = await browser.newContext({ viewport: { width: 1440, height: 960 } });
  const ownerPage = await login(owner, "owner");
  await ownerPage.goto(origin + "/en/settings");
  await ownerPage.getByLabel("Shop name (English)").fill("ShopFlow Pharmacy & Grocery");
  await ownerPage.getByLabel("Shop name (Bangla)").fill("শপফ্লো ফার্মেসি ও মুদি");
  await ownerPage.getByLabel("Shop address").fill("Dhanmondi, Dhaka");
  await ownerPage.getByLabel("Contact phone").fill("+880 1700 000000");
  await ownerPage.getByLabel("Trade license number").fill("DEMO-TL-017");
  await ownerPage.getByLabel("Tax registration number").fill("DEMO-TAX-021");
  await ownerPage.getByLabel("Footer (English)").fill("Thank you for shopping with us.");
  await ownerPage.getByLabel("Footer (Bangla)").fill("আমাদের সঙ্গে কেনাকাটার জন্য ধন্যবাদ।");
  await ownerPage.getByLabel("Return policy (English)").fill("Please keep this receipt for returns.");
  await ownerPage.getByLabel("Return policy (Bangla)").fill("পণ্য ফেরতের জন্য রসিদটি সংরক্ষণ করুন।");
  await ownerPage.locator('select[name="preferred_language"]').selectOption("en");
  await ownerPage.getByLabel("Printable width (mm)").fill("72");
  await buttons(ownerPage, "Save receipt settings").click();
  await ownerPage.getByText("Receipt settings saved.", { exact: true }).waitFor();

  const cashier = await browser.newContext({
    viewport: { width: 375, height: 812 }, isMobile: true, hasTouch: true, reducedMotion: "reduce",
  });
  const page = await login(cashier, "cashier1");
  await page.goto(origin + "/en/billing");
  await page.getByRole("searchbox", { name: /Search products/ }).fill(data.goods_sku);
  await page.locator(`[data-sku="${data.goods_sku}"]`).click();
  await buttons(page, "Finalize Bill").click();
  const bill = page.waitForResponse((response) => response.url().endsWith("/api/billing/invoices"));
  await buttons(page, "Confirm invoice").click();
  const savedResponse = await bill;
  assert.equal(savedResponse.status(), 201, await savedResponse.text());
  const saved = await savedResponse.json();
  await page.getByRole("link", { name: "View receipt", exact: true }).click();
  await page.waitForURL(origin + "/en/invoices/" + saved.id);
  const preview = page.frameLocator("iframe[title]");
  await preview.getByText("Sales receipt", { exact: true }).waitFor();
  await buttons(page, "Print receipt").waitFor();
  await verifyPrint(page, "Print receipt");
  const small = await download(page, "Download PDF", join(pdfs, "shopflow-receipt-en.pdf"));
  const smallSize = await inspectPdf(small);
  const duplicate = await cashier.request.get(receiptUrl(saved.id, "en", "pdf"));
  assert.equal(duplicate.status(), 200, await duplicate.text());
  assert.deepEqual(await duplicate.body(), small, "PDF bytes changed for the same receipt");
  await page.screenshot({ path: join(screenshots, "p2d1-en-375.png"), animations: "disabled" });

  await page.getByRole("link", { name: "Invoice history", exact: true }).click();
  await page.getByLabel("Search by invoice number").fill(saved.invoice_number);
  await buttons(page, "Search").click();
  await page.waitForURL((url) => url.searchParams.get("q") === saved.invoice_number);
  await page.getByRole("link", { name: "Receipt preview", exact: true }).click();
  await preview.getByText(saved.invoice_number, { exact: true }).waitFor();
  const replay = await cashier.request.get(receiptUrl(saved.id, "en", "pdf"));
  assert.deepEqual(await replay.body(), small);

  const rich = await sale(owner, {
    customer_id: data.customer, items: [
      { product_id: data.goods, quantity: "1.250", line_discount: "0.05" },
      { product_id: data.medicine, quantity: "2" },
    ],
    discount_total: "8.00", redeem_points: 100, allow_due: true,
    payments: [{ method: "cash", amount: "30" }, { method: "bkash", amount: "50" }, { method: "nagad", amount: "45" }],
  });
  assert.equal(rich.payment_status, "partially_paid");
  const rendered = await cashier.request.get(receiptUrl(rich.id, "bn"));
  assert.equal(rendered.status(), 200);
  const markup = await rendered.text();
  assert.ok(!markup.includes(data.phone));
  assert.ok(markup.includes(data.phone.slice(-4)));
  const anonymous = await browser.newContext();
  assert.equal((await anonymous.request.get(receiptUrl(rich.id, "bn"))).status(), 401);
  await anonymous.close();
  for (const [width, locale, language, heading, printLabel, pdfLabel] of [
    [414, "bn", "bn", "বিক্রয় রসিদ", "রসিদ প্রিন্ট করুন", "PDF ডাউনলোড"],
    [768, "en", "bilingual", "বিক্রয় রসিদ", "Print receipt", "Download PDF"],
    [1440, "en", "en", "Sales receipt", "Print receipt", "Download PDF"],
  ]) {
    const context = await browser.newContext({
      viewport: { width, height: width < 768 ? 886 : 1000 },
      hasTouch: width < 1000, isMobile: width === 414, reducedMotion: "reduce",
    });
    await context.addCookies(await cashier.cookies());
    const scenario = await context.newPage();
    scenario.on("pageerror", (error) => browserErrors.push(error.message));
    await scenario.goto(origin + "/" + locale + "/invoices/" + rich.id);
    await scenario.locator("#receipt-language").selectOption(language);
    const receipt = scenario.frameLocator("iframe[title]");
    await receipt.getByText(heading, { exact: true }).waitFor();
    await receipt.locator(".item").last().waitFor();
    assert.equal(await receipt.locator(".item").count(), 2);
    assert.equal(await receipt.locator(".quantity").first().textContent(), "1.25");
    await verifyPrint(scenario, printLabel);
    assert.deepEqual(await scenario.evaluate(() => [
      document.documentElement.scrollWidth, window.innerWidth,
    ]), [width, width]);
    if (language === "bn") {
      const bytes = await download(scenario, pdfLabel, join(pdfs, "shopflow-receipt-bn.pdf"));
      assert.ok((await inspectPdf(bytes)).height > smallSize.height);
    }
    await scenario.screenshot({
      path: join(screenshots, `p2d1-${language}-${width}.png`), animations: "disabled",
    });
    await context.close();
  }

  const large = await sale(owner, {
    items: data.large.map((product) => ({ product_id: product, quantity: "1" })),
    payments: [{ method: "cash" }],
  });
  const longResponse = await cashier.request.get(receiptUrl(large.id, "bilingual", "pdf"));
  assert.equal(longResponse.status(), 200, await longResponse.text());
  const long = await longResponse.body();
  const longSize = await inspectPdf(long);
  assert.ok(longSize.height > 1200);
  await writeFile(join(pdfs, "shopflow-receipt-bilingual-long.pdf"), long);
  assert.deepEqual(browserErrors, []);
  console.log("4 viewport workflows passed. Exact 80 mm PDFs, embedded Bengali font, deterministic reprint.");
  console.log("Long receipt: " + data.large.length + " lines, " + (longSize.height * 25.4 / 72).toFixed(0) + " mm.");
} finally {
  await browser.close();
}
