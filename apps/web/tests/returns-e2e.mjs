import assert from "node:assert/strict";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { chromium } from "playwright";

const [origin, fixtureFile, resultFile, output] = process.argv.slice(2);
assert.equal(new URL(origin).hostname, "127.0.0.1");
const fixtures = JSON.parse(await readFile(fixtureFile, "utf-8"));
await mkdir(output, { recursive: true });
const browser = await chromium.launch();
const proofs = [];
const browserErrors = [];
const button = (page, name) => page.getByRole("button", { name, exact: true });
const label = (page, name) => page.getByLabel(name, { exact: true });

async function login(page, locale, t, user) {
  await page.goto(origin + "/" + locale + "/login");
  await label(page, t.email).fill(user + "@shopflow.dev");
  await label(page, t.password).fill("ShopFlow#Dev123");
  await button(page, t.signIn).click();
  await page.waitForURL(origin + "/" + locale);
}
async function response(page, suffix, method, action) {
  const request = page.waitForResponse((r) => new URL(r.url()).pathname.endsWith(suffix) && r.request().method() === method);
  await action();
  const received = await request;
  assert.ok(received.ok(), await received.text());
  return received.json();
}
async function capture(page, width, file, point) {
  if (point) await point.evaluate((element) => element.scrollIntoView({ block: "center" }));
  assert.deepEqual(await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]), [width, width]);
  await page.screenshot({ path: join(output, file), animations: "disabled" });
}

try {
  for (const item of fixtures) {
    const { locale, width, batch, invoice, purchase, purchase_reference: reference } = item;
    const screenshot = "p2f-" + locale + "-" + width + "-";
    const messages = JSON.parse(await readFile("src/messages/" + locale + ".json", "utf-8"));
    const t = messages.returns;
    const ops = messages.inventoryOps;
    const context = await browser.newContext({
      viewport: { width, height: width === 375 ? 850 : 1050 },
      isMobile: width === 375, hasTouch: width === 375, reducedMotion: "reduce",
    });
    const page = await context.newPage();
    page.on("pageerror", (error) => browserErrors.push(error.message));
    await login(page, locale, messages.login, "manager");
    await page.goto(origin + "/" + locale + "/invoices/" + invoice);
    await page.frameLocator("iframe[title]").getByText(new RegExp(batch)).waitFor();
    await response(page, "/returns", "GET", () => button(page, t.title).click());
    const quantityLabel = t.quantityFor.replace("{name}", (locale === "en" ? item.product_en : item.product_bn) + " · " + batch);
    await label(page, quantityLabel).fill(locale === "bn" ? "১" : "1");
    await label(page, t.reason).fill(locale === "bn" ? "ক্রেতা একটি ওষুধ ফেরত দিয়েছেন" : "Customer returned one medicine unit");
    await label(page, t.refundMethod).selectOption("bkash");
    const returned = await response(page, "/returns", "POST", () => button(page, t.submit).click());
    assert.equal(Number(returned.amount), 200);
    assert.equal(Number(returned.due_reduction), 100);
    assert.equal(Number(returned.refund_amount), 100);
    assert.equal(returned.redeemed_restored, 100);
    assert.ok(returned.lines[0].held);
    assert.equal(returned.refund_status, "pending");
    const pending = page.getByText(t.status.pending, { exact: true });
    await pending.waitFor();
    await capture(page, width, screenshot + "refund-pending.png", pending);
    await label(page, t.transferReference).fill("CUSTOMER-" + batch);
    const completed = await response(page, "/refund", "POST", () => button(page, t.complete).click());
    assert.equal(completed.refund_status, "completed");
    await page.getByText(t.status.completed, { exact: true }).waitFor();

    await page.goto(origin + "/" + locale + "/inventory/operations");
    await label(page, ops.searchPurchase).fill(reference);
    await button(page, ops.search).click();
    const purchaseCard = page.getByText(reference, { exact: true }).locator("../..");
    await button(purchaseCard, ops.viewPurchase).click();
    await page.getByRole("heading", { name: reference, exact: true }).waitFor();
    await response(page, "/credits", "GET", () => button(page, t.supplierTitle).click());
    await button(page, t.sendToSupplier).click();
    await page.getByLabel(new RegExp(batch)).fill("1");
    await label(page, t.reason).fill(locale === "bn" ? "সরবরাহকারী একটি পণ্য ফেরত নিয়েছেন" : "Supplier accepted one receipt unit");
    const shipment = await response(page, "/supplier-returns", "POST", () => button(page, t.recordShipment).click());
    assert.equal(Number(shipment.cost), 50);
    await button(page, t.createCredit).click();
    await label(page, t.creditReference).fill("CREDIT-" + batch);
    await label(page, t.amount).fill("50");
    await label(page, t.reason).fill(locale === "bn" ? "সরবরাহকারীর ক্রেডিট নোট" : "Supplier credit approved");
    const note = await response(page, "/credits", "POST", () => button(page, t.saveCredit).click());
    assert.equal(Number(note.available), 50);
    await button(page, t.applyCredit).click();
    await label(page, t.purchase).selectOption(purchase);
    await label(page, t.amount).fill("30");
    const applied = await response(page, "/applications", "POST", () =>
      page.locator("form").getByRole("button", { name: t.applyCredit, exact: true }).click());
    assert.equal(Number(applied.available), 20);
    await button(page, t.recordSupplierRefund).click();
    await label(page, t.refundMethod).selectOption("bank");
    await label(page, t.amount).fill("10");
    await label(page, t.transferReference).fill("SUPPLIER-" + batch);
    const refund = await response(page, "/refunds", "POST", () =>
      page.locator("form").getByRole("button", { name: t.recordSupplierRefund, exact: true }).click());
    assert.equal(Number(refund.available), 10);
    const supplierRefund = page.getByText("SUPPLIER-" + batch, { exact: false });
    await supplierRefund.waitFor();
    await capture(page, width, screenshot + "supplier-credit.png", supplierRefund);

    await page.goto(origin + "/" + locale + "/reports");
    await page.getByText(t.metrics.net_sales, { exact: true }).waitFor();
    await page.getByText(t.metrics.collections, { exact: true }).waitFor();
    await capture(page, width, screenshot + "financial.png");
    const reconciliation = await response(page, "/reconciliation", "GET", () => button(page, t.reconciliation).click());
    assert.ok(Number.isInteger(reconciliation.total));
    await page.getByText(reconciliation.total ? t.differences.replace("{count}", String(reconciliation.total)) : t.balanced, { exact: true }).waitFor();
    await capture(page, width, screenshot + "reconciliation.png");
    const verified = await context.request.get(origin + "/api/inventory-ops/reports/reconciliation?" + new URLSearchParams({ entity_id: invoice }));
    assert.equal(verified.status(), 200);
    assert.equal((await verified.json()).total, 0);
    const cashier = await browser.newContext();
    const till = await cashier.newPage();
    await login(till, locale, messages.login, "cashier1");
    assert.equal((await cashier.request.get(origin + "/api/inventory-ops/invoices/" + invoice + "/returns")).status(), 403);
    assert.equal((await cashier.request.get(origin + "/api/inventory-ops/reports/financial")).status(), 403);
    await cashier.close();
    await context.close();
    proofs.push({ ...item, return_id: returned.id, credit_id: note.id, shipment: shipment.id });
    console.log(locale + " " + width + "px: partial return, manual refund, supplier credit and reconciliation verified");
  }
  assert.deepEqual(browserErrors, []);
  await writeFile(resultFile, JSON.stringify(proofs));
} finally {
  await browser.close();
}
