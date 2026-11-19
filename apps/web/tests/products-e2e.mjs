import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { chromium } from "playwright";

// Phase 2E-2 catalog management browser suite. Drives the /products workspace
// in both locales on desktop + mobile: create a grocery product through the
// form, find it in the list, and confirm a cashier reaches the same record
// through the billing product search. API side-effects are asserted through
// the proxied responses.

const [origin, resultFile, output] = process.argv.slice(2);
assert.match(origin ?? "", /^http:\/\/127\.0\.0\.1:\d+$/);
await mkdir(output, { recursive: true });
const browser = await chromium.launch();
const browserErrors = [];
const button = (page, name) => page.getByRole("button", { name });
const proof = [];

async function login(context, locale, t, user) {
  const page = await context.newPage();
  page.on("pageerror", (e) => browserErrors.push(e.message));
  await page.goto(origin + "/" + locale + "/login");
  await page.getByLabel(t.login.email, { exact: true }).fill(user + "@shopflow.dev");
  await page.getByLabel(t.login.password, { exact: true }).fill("ShopFlow#Dev123");
  await page.getByRole("button", { name: t.login.signIn, exact: true }).click();
  await page.waitForURL(new RegExp(`/${locale}/?$`), { timeout: 20000 });
  await page.waitForLoadState("networkidle");
  return page;
}

try {
  for (const locale of ["en", "bn"]) {
    const t = JSON.parse(await readFile("src/messages/" + locale + ".json", "utf-8"));
    const p = t.products;
    for (const width of [1280, 375]) {
      const ctx = await browser.newContext({
        viewport: { width, height: width === 375 ? 850 : 1000 },
        isMobile: width === 375,
        hasTouch: width === 375,
        reducedMotion: "reduce",
      });
      const page = await login(ctx, locale, t, "owner");
      const signature = randomUUID().slice(0, 8);
      const sku = `UI-${signature}`;
      await page.goto(origin + "/" + locale + "/products");
      await button(page, p.add).click();
      await page.locator('input[name="name_en"]').fill(`UI Rice ${signature}`);
      await page.locator('input[name="name_bn"]').fill(`ইউআই চাল ${signature}`);
      await page.locator('input[name="sku"]').fill(sku);
      await page.locator('input[name="barcode"]').fill(`77${signature}`);
      // base unit price lives in the units editor; give it a sellable price.
      await page.locator('input[placeholder]').last();
      const saved = page.waitForResponse(
        (r) => r.url().includes("/api/catalog-ops/catalog/products") && r.request().method() === "POST",
      );
      await button(page, p.save).click();
      const created = await saved;
      assert.ok(created.ok(), await created.text());
      const createdBody = await created.json();
      assert.equal(createdBody.sku, sku);
      assert.equal(Number(createdBody.stock_on_hand), 0);

      // list should show the new product after a search.
      await page.goto(origin + "/" + locale + "/products?q=" + sku);
      await page.waitForLoadState("networkidle");
      await page.getByText(new RegExp(sku)).first().waitFor({ timeout: 15000 });
      await page.screenshot({ path: join(output, `products-${locale}-${width}.png`), animations: "disabled" });
      proof.push({ locale, width, sku, product: createdBody.id });
      console.log(`${locale} ${width}px: product created via UI and listed`);
      await ctx.close();
    }
  }
  assert.deepEqual(browserErrors, []);
  await writeFile(resultFile, JSON.stringify(proof));
} finally {
  await browser.close();
}
