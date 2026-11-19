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

async function inspectPdf(bytes, expectedPages = 1) {
  const pdf = await PDFDocument.load(bytes, { updateMetadata: false });
  assert.equal(pdf.getPageCount(), expectedPages);
  const { width, height } = pdf.getPage(0).getSize();
  assert.ok(Math.abs(width - expectedWidth) < 0.00001);
  const embedded = pdf.context.enumerateIndirectObjects().some(([, object]) =>
    object instanceof PDFDict && /NotoSansBengali/.test(String(object.get(PDFName.of("FontName"))))
      && (object.has(PDFName.of("FontFile2")) || object.has(PDFName.of("FontFile3"))),
  );
  assert.ok(embedded, "Expected the Bengali font program in the PDF");
  return { width, height, pages: pdf.getPageCount() };
}

async function download(page, buttonName, path) {
  const job = page.waitForEvent("download");
  await buttons(page, buttonName).click();
  const file = await job;
  assert.equal(await file.failure(), null);
  await file.saveAs(path);
  return readFile(path);
}

// Receipt layout guard, shared by the live preview and the long-name stress
// renders. Every label/value row must give the value all the width the label
// does not need, and nothing may leave the 72 mm body.
const layoutGuard = (main) => {
  const problems = [];
  const box = main.getBoundingClientRect();
  const round = (value) => Math.round(value * 10) / 10;
  // Natural (unwrapped) width of a node's own text, measured off-screen.
  const natural = (node) => {
    const probe = document.createElement("span");
    probe.setAttribute("style",
      "position:absolute;left:-9999px;top:0;visibility:hidden;white-space:nowrap");
    probe.innerHTML = node.innerHTML;
    main.appendChild(probe);
    const width = probe.getBoundingClientRect().width;
    probe.remove();
    return width;
  };
  for (const row of main.querySelectorAll(".pair")) {
    const label = row.querySelector("dt");
    const value = row.lastElementChild;
    if (!label || !value || label === value) continue;
    const rowWidth = row.getBoundingClientRect().width;
    const gap = parseFloat(getComputedStyle(row).columnGap) || 0;
    const labelWidth = label.getBoundingClientRect().width;
    const valueWidth = value.getBoundingClientRect().width;
    const free = rowWidth - labelWidth - gap;
    const labelText = label.textContent.trim().slice(0, 24);
    // The label gets its own text width, capped at just over half the row, and
    // its box must be at least that wide. A narrower box means the value starved
    // the label and it wrapped; a wider one means the label stole value space
    // (the original defect). Slight overshoot inside a still-capped box is fine.
    const allowance = Math.min(natural(label), rowWidth * 0.52);
    if (labelWidth < allowance - 1 || labelWidth > rowWidth * 0.52 + 1) {
      problems.push({ row: labelText, label: round(labelWidth), needs: round(allowance) });
    }
    // The value must own everything the label leaves.
    if (valueWidth < free - 1) {
      problems.push({ row: labelText, value: round(valueWidth), free: round(free) });
    }
  }
  for (const node of main.querySelectorAll("*")) {
    const rect = node.getBoundingClientRect();
    if (rect.right > box.right + 0.5 || rect.left < box.left - 0.5) {
      problems.push({ overflow: node.className || node.tagName, left: round(rect.left), right: round(rect.right) });
    }
  }
  return { problems, width: round(box.width) };
};

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
    // Layout guard: the label column must be only as wide as its own text, so the
    // value column gets every remaining millimetre. The old rule made the label a
    // greedy `1fr` track and capped the value box at 43 mm, which squeezed
    // bilingual translations into a narrow right-aligned column where Bengali
    // wrapped against the paper edge.
    const layout = await receipt.locator("[data-receipt]").evaluate(layoutGuard);
    assert.deepEqual(layout.problems, [], "Receipt layout squeezed or overflowing: " + JSON.stringify(layout));
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

  // Long-name stress: the real bilingual markup with the counter, cashier and
  // customer values replaced by realistically long bilingual names. This is the
  // shape the old layout broke — the value column collapsed to its English
  // width and the Bengali translation wrapped inside a narrow right-aligned box.
  const stressMarkup = await (await cashier.request.get(receiptUrl(rich.id, "bilingual"))).text();
  const stress = await browser.newPage();
  stress.on("pageerror", (error) => browserErrors.push(error.message));
  await stress.emulateMedia({ media: "print" });
  await stress.setContent(stressMarkup, { waitUntil: "load" });
  await stress.evaluate(() => document.fonts.ready);
  const stressed = await stress.evaluate(() => {
    const long = {
      Counter: [
        "C1 · Counter 1 · Front desk and wholesale collection point",
        "কাউন্টার ১ · সামনের ডেস্ক ও পাইকারি সংগ্রহ কেন্দ্র",
      ],
      Cashier: ["Jamal Hossain Ahmed Chowdhury", "জামাল হোসেন আহমেদ চৌধুরী"],
      Customer: ["Amina Rahman Siddiqua Khatun", "আমিনা রহমান সিদ্দিকা খাতুন"],
    };
    const applied = [];
    for (const [label, [english, bangla]] of Object.entries(long)) {
      const row = [...document.querySelectorAll(".pair")].find((candidate) =>
        candidate.querySelector("dt")?.textContent.trim().startsWith(label));
      if (!row) continue;
      const value = row.querySelector("dd");
      value.firstChild.textContent = english + " ";
      const translation = value.querySelector(".translation");
      if (translation) translation.textContent = bangla;
      const lineHeight = parseFloat(getComputedStyle(value).lineHeight) || 17;
      const banglaRects = translation ? [...translation.getClientRects()] : [];
      applied.push({
        label,
        lines: Math.round(value.getBoundingClientRect().height / lineHeight),
        right: Math.round(value.getBoundingClientRect().right * 10) / 10,
        banglaRight: banglaRects.length
          ? Math.round(Math.max(...banglaRects.map((rect) => rect.right)) * 10) / 10
          : null,
      });
    }
    return { applied, body: document.querySelector("main").getBoundingClientRect().right };
  });
  assert.deepEqual(stressed.applied.map((row) => row.label), ["Counter", "Cashier", "Customer"]);
  for (const row of stressed.applied) {
    assert.ok(row.right <= stressed.body + 0.5, row.label + " value left the receipt body");
    assert.ok(row.banglaRight === null || row.banglaRight <= stressed.body + 0.5,
      row.label + " Bangla value left the receipt body");
  }
  assert.ok(stressed.applied[0].lines > 1, "a long counter name must wrap, not be truncated");
  const stressLayout = await stress.locator("[data-receipt]").evaluate(layoutGuard);
  assert.deepEqual(stressLayout.problems, [],
    "Long-name receipt layout squeezed or overflowing: " + JSON.stringify(stressLayout));
  // Re-fit the print page after the substitution: the stylesheet height was
  // computed for the original names, so the taller content would spill onto a
  // second sheet. This mirrors what the PDF route does from the real DOM.
  await stress.evaluate(() => {
    const pxPerMm = 96 / 25.4;
    const content = Math.ceil(document.querySelector("main").getBoundingClientRect().height / pxPerMm) + 2;
    document.getElementById("print-page").textContent =
      "@page { size: 80mm " + content + "mm; margin: 0; }";
  });
  const stressPdf = await stress.pdf({ preferCSSPageSize: true, displayHeaderFooter: false });
  await writeFile(join(pdfs, "shopflow-receipt-long-names.pdf"), stressPdf);
  await stress.close();

  const large = await sale(owner, {    items: data.large.map((product) => ({ product_id: product, quantity: "1" })),
    payments: [{ method: "cash" }],
  });
  const longResponse = await cashier.request.get(receiptUrl(large.id, "bilingual", "pdf"));
  assert.equal(longResponse.status(), 200, await longResponse.text());
  const long = await longResponse.body();
  // A receipt taller than one sheet must split, not shrink to a fallback height.
  const sheets = await PDFDocument.load(long, { updateMetadata: false }).then((pdf) => pdf.getPageCount());
  const longSize = await inspectPdf(long, sheets);
  assert.ok(longSize.height > 1200);
  assert.ok(sheets >= 2, "an 80-item receipt should already exceed one sheet: " + sheets);
  await writeFile(join(pdfs, "shopflow-receipt-bilingual-long.pdf"), long);
  assert.deepEqual(browserErrors, []);
  console.log("4 viewport workflows passed. Exact 80 mm PDFs, embedded Bengali font, deterministic reprint.");
  console.log(
    "Long receipt: " + data.large.length + " lines, " + sheets + " sheet(s), " +
    (longSize.height * 25.4 / 72).toFixed(0) + " mm first sheet.",
  );
} finally {
  await browser.close();
}
