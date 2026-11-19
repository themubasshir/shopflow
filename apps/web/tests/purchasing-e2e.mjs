import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { chromium } from "playwright";

const [origin, fixtureFile, resultFile, output] = process.argv.slice(2);
assert.match(origin ?? "", /^http:\/\/127\.0\.0\.1:\d+$/);
const fixtures = JSON.parse(await readFile(fixtureFile, "utf-8"));
await mkdir(output, { recursive: true });
const browser = await chromium.launch();
const proof = [];
const browserErrors = [];
const button = (page, name) => page.getByRole("button", { name, exact: true });
const label = (page, name) => page.getByLabel(name, { exact: true });

async function login(context, locale, t, user) {
  const page = await context.newPage();
  page.on("pageerror", (error) => browserErrors.push(error.message));
  await page.goto(origin + "/" + locale + "/login");
  await label(page, t.email).fill(user + "@shopflow.dev");
  await label(page, t.password).fill("ShopFlow#Dev123");
  await button(page, t.signIn).click();
  await page.waitForURL(origin + "/" + locale);
  return page;
}
async function response(page, postfix, method, action) {
  const result = page.waitForResponse((r) => new URL(r.url()).pathname.endsWith(postfix) && r.request().method() === method);
  await action();
  const received = await result;
  assert.ok(received.ok(), await received.text());
  return received.json();
}
async function overflow(page, width) {
  assert.deepEqual(await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]), [width, width]);
}

try {
  for (const item of fixtures) {
    const { locale, width } = item;
    const t = JSON.parse(await readFile("src/messages/" + locale + ".json", "utf-8"));
    const ops = t.inventoryOps;
    const options = { viewport: { width, height: width === 375 ? 850 : 1050 }, isMobile: width === 375,
      hasTouch: width === 375, reducedMotion: "reduce" };
    const operator = await browser.newContext(options);
    const page = await login(operator, locale, t.login, "manager");
    await page.goto(origin + "/" + locale + "/inventory");
    await page.getByRole("link", { name: ops.title, exact: true }).click();
    await page.waitForURL(origin + "/" + locale + "/inventory/operations");
    await button(page, ops.suppliers).click();
    await button(page, ops.addSupplier).click();
    const signature = randomUUID().slice(0, 6);
    const supplierName = "Aster Distribution " + signature;
    const localName = "অ্যাস্টার সরবরাহ " + signature;
    await label(page, ops.supplierName).fill(supplierName);
    await label(page, ops.banglaName).fill(localName);
    await label(page, ops.phone).fill("01700000000");
    await label(page, ops.address).fill("Dhaka");
    await label(page, ops.findProduct).fill(item.sku);
    await page.locator(`select:has(option[value="${item.product}"])`).selectOption(item.product);
    await button(page, ops.linkProduct).click();
    const supplier = await response(page, "/suppliers", "POST", () => button(page, ops.saveSupplier).click());
    assert.deepEqual(supplier.product_ids, [item.product]);

    await button(page, ops.purchases).click();
    await button(page, ops.createPurchase).click();
    await page.locator('select[name="supplier"]').selectOption(supplier.id);
    const reference = "E-INV-" + signature.toUpperCase();
    const batch = "ASTER-" + signature.toUpperCase();
    await label(page, ops.supplierReference).fill(reference);
    await label(page, ops.discount).fill(locale === "bn" ? "৩" : "3");
    await label(page, ops.findProduct).fill(item.sku);
    await page.locator(`select:has(option[value="${item.product}"])`).selectOption(item.product);
    await label(page, ops.quantity).fill(locale === "bn" ? "৩" : "3");
    await label(page, ops.unitCost).fill(locale === "bn" ? "২৫" : "25");
    await label(page, ops.batchNumber).fill(batch);
    await label(page, ops.expiry).fill(item.expiry);
    await label(page, ops.manufacture).fill(item.manufacture);
    const order = await response(page, "/purchases", "POST", () => button(page, ops.saveDraft).click());
    assert.equal(order.status, "draft");
    await page.getByRole("heading", { name: reference, exact: true }).waitFor();
    await button(page, ops.action.receive).click();
    await page.getByLabel(new RegExp(ops.receivingQuantity)).fill("2");
    const partial = await response(page, "/receive", "POST", () => button(page, ops.confirm).click());
    assert.equal(partial.status, "partially_received");
    await page.getByText(ops.purchaseStatus.partially_received, { exact: true }).first().waitFor();
    await overflow(page, width);
    await page.screenshot({ path: join(output, `p2e-${locale}-${width}-receiving.png`), animations: "disabled" });
    await button(page, ops.action.receive).click();
    await page.getByLabel(new RegExp(ops.receivingQuantity)).fill("1");
    const received = await response(page, "/receive", "POST", () => button(page, ops.confirm).click());
    assert.equal(received.status, "received");
    await button(page, ops.action.payments).click();
    await label(page, ops.amount).fill("20");
    const paid = await response(page, "/payments", "POST", () => button(page, ops.confirm).click());
    assert.equal(Number(paid.outstanding), 52);

    await button(page, ops.batches).click();
    await label(page, ops.searchBatch).fill(batch);
    await button(page, ops.search).click();
    await page.locator('select:has(option[value="30"])').selectOption("30");
    await page.getByText(batch, { exact: true }).waitFor();
    await overflow(page, width);
    await page.screenshot({ path: join(output, `p2e-${locale}-${width}-batches.png`), animations: "disabled" });

    const cashier = await browser.newContext(options);
    const till = await login(cashier, locale, t.login, "cashier1");
    const blocked = await cashier.request.get(origin + "/api/inventory-ops/purchases");
    assert.equal(blocked.status(), 403);
    await till.goto(origin + "/" + locale + "/billing");
    await label(till, t.billing.searchProducts).fill(item.sku);
    await till.locator(`[data-sku="${item.sku}"]`).click();
    await button(till, t.billing.finalize).click();
    const invoice = await response(till, "/api/billing/invoices", "POST", () => button(till, t.billing.confirm).click());
    await till.getByRole("link", { name: t.receipts.open, exact: true }).click();
    await till.frameLocator("iframe[title]").getByText(new RegExp(batch)).waitFor();
    proof.push({ ...item, purchase: order.id, invoice: invoice.id, batch });
    console.log(locale + " " + width + "px: purchasing, batch view and cashier FEFO checkout passed");
    await operator.close();
    await cashier.close();
  }
  assert.deepEqual(browserErrors, []);
  await writeFile(resultFile, JSON.stringify(proof));
} finally {
  await browser.close();
}
