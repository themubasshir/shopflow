import assert from "node:assert/strict";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { chromium } from "playwright";

/**
 * Phase 2D-2 printer workflow, run in two phases around a real print-agent pass:
 *
 *   queue  — the owner routes two counters to one shared printer, registers a
 *            second printer through the UI, queues a calibration test page and
 *            a receipt.
 *   verify — after the agent printed both jobs, the queue shows them printed
 *            and an explicit reprint creates a NEW linked job.
 *
 * The caller runs the real `printagent` loop between the phases; nothing here
 * simulates the queue or fakes a printed page.
 */
const [origin, fixtureFile, resultFile, output, phase] = process.argv.slice(2);
assert.equal(new URL(origin).hostname, "127.0.0.1");
assert.ok(phase === "queue" || phase === "verify", "phase must be queue|verify");
const fixtures = JSON.parse(await readFile(fixtureFile, "utf-8"));
await mkdir(output, { recursive: true });

const browser = await chromium.launch();
const browserErrors = [];
const proofs = [];
const button = (page, name) => page.getByRole("button", { name, exact: true });
const label = (page, name) => page.getByLabel(name, { exact: true });
const messages = async (locale) =>
  JSON.parse(await readFile("src/messages/" + locale + ".json", "utf-8"));
const api = (page) => page.request;
const started = Date.now();
const step = (name) =>
  console.log(`[${((Date.now() - started) / 1000).toFixed(1)}s] ${phase}: ${name}`);

async function login(page, locale, t, user) {
  await page.goto(origin + "/" + locale + "/login");
  await label(page, t.email).fill(user + "@shopflow.dev");
  await label(page, t.password).fill("ShopFlow#Dev123");
  await button(page, t.signIn).click();
  await page.waitForURL(origin + "/" + locale);
}

async function capture(page, width, file, point) {
  if (point) await point.evaluate((element) => element.scrollIntoView({ block: "center" }));
  assert.deepEqual(
    await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]),
    [width, width],
    "horizontal overflow at " + width + "px",
  );
  await page.screenshot({ path: join(output, file), animations: "disabled" });
}

const printerCard = (page, name) => page.locator("[data-printer-id]", { hasText: name });

async function jobsFor(page, query) {
  const response = await api(page).get(
    origin + "/api/printing/jobs?" + new URLSearchParams(query),
  );
  assert.equal(response.status(), 200, await response.text());
  return response.json();
}

try {
  const en = await messages("en");
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    reducedMotion: "reduce",
  });
  const page = await context.newPage();
  page.setDefaultTimeout(20_000);
  page.setDefaultNavigationTimeout(30_000);
  page.on("pageerror", (error) => browserErrors.push(error.message));
  await login(page, "en", en.login, "owner");
  step("signed in as owner");
  const t = en.printers;
  const jobs = en.printJobs;

  if (phase === "queue") {
    await page.goto(origin + "/en/settings/printers");
    await page.getByRole("heading", { name: t.title, exact: true }).waitFor();
    await printerCard(page, fixtures.printer_name).waitFor();
    step("printer settings page ready");

    // Two counters routed to ONE printer: the shared-printer case. Each
    // assignment triggers a server refresh, so reload before the next one.
    for (const counter of fixtures.counters) {
      const select = page.getByLabel(t.assign + " " + counter.code, { exact: true });
      await select.waitFor();
      const saved = page.waitForResponse(
        (response) =>
          response.url().includes("/api/printing/counters/") &&
          response.request().method() === "PUT",
      );
      await select.selectOption(fixtures.printer_id);
      assert.equal((await saved).status(), 204);
      await page.reload();
      const routed = page.getByLabel(t.assign + " " + counter.code, { exact: true });
      await routed.waitFor();
      assert.equal(await routed.inputValue(), fixtures.printer_id);
      step("counter " + counter.code + " routed to the shared printer");
    }
    const assigned = await printerCard(page, fixtures.printer_name)
      .locator("dl > div")
      .last()
      .locator("dd")
      .textContent();
    for (const counter of fixtures.counters) {
      assert.ok(assigned.includes(counter.code), counter.code + " not routed to the printer");
    }
    step("shared printer lists " + assigned.trim());

    // A second printer registered through the UI: the token is shown exactly once.
    await button(page, t.add).click();
    const dialog = page.getByRole("dialog");
    await dialog.waitFor();
    await dialog.locator("#pf-name").fill(fixtures.second_printer_name);
    await dialog.locator("#pf-agent").fill(fixtures.second_agent_id);
    await dialog.locator("#pf-model").fill("Epson TM-T82X");
    await dialog.locator("#pf-host").fill("192.168.0.61");
    await dialog.locator("#pf-port").fill("9100");
    await dialog.locator("#pf-density").fill("6");
    await dialog.locator("#pf-feed").fill("120");
    await dialog.locator("#pf-lang").selectOption("bn");
    const created = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname.endsWith("/api/printing/printers") &&
        response.request().method() === "POST",
    );
    await button(page, t.create).click();
    const registered = await created;
    assert.equal(registered.status(), 201);
    const token = await dialog.getByText(/^[A-Za-z0-9_-]{40,}$/).first().textContent();
    assert.ok(token && token.length >= 40, "the agent token must be revealed once");
    proofs.push({ agent_token_issued_once: true, token_length: token.length });
    await button(page, t.done).click();
    await page.reload();
    await printerCard(page, fixtures.second_printer_name).waitFor();
    // The card's detail list starts with the agent id; assert on the whole list
    // so a new row order cannot silently turn this into a vacuous check.
    const details = await printerCard(page, fixtures.second_printer_name).locator("dl").textContent();
    assert.ok(details?.includes("Epson TM-T82X"), "hardware row must show the model");
    assert.ok(details?.includes("6/8"), "hardware row must show the density");
    assert.ok(details?.includes("120"), "hardware row must show the feed distance");
    step("second printer registered with its hardware profile, one-time token shown");

    // Calibration page for the shared printer: a queue job with no invoice.
    const testQueued = page.waitForResponse(
      (response) =>
        response.url().endsWith("/test-page") && response.request().method() === "POST",
    );
    await printerCard(page, fixtures.printer_name)
      .getByRole("button", { name: t.testPage, exact: true })
      .click();
    assert.equal((await testQueued).status(), 201);
    // Read the queue over the API rather than the click's own response: these
    // handlers refresh the server component, which can drop the response body.
    const testJob = (await jobsFor(page, { limit: 25 })).items.find(
      (job) => job.kind === "test_page",
    );
    assert.ok(testJob, "the calibration page should be queued");
    assert.equal(testJob.status, "pending");
    assert.equal(testJob.invoice_id, null);
    assert.equal(testJob.printer_id, fixtures.printer_id);
    step("calibration test page queued");

    // The saved invoice, queued to the shared printer.
    await page.goto(origin + "/en/invoices/" + fixtures.invoice);
    await button(page, jobs.sendToPrinter).waitFor();
    step("invoice page loaded");
    await page.getByLabel(jobs.printer, { exact: true }).selectOption(fixtures.printer_id);
    const queued = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname.endsWith("/api/printing/jobs") &&
        response.request().method() === "POST",
    );
    await button(page, jobs.sendToPrinter).click();
    assert.equal((await queued).status(), 201);
    const receiptJob = (await jobsFor(page, { invoice_id: fixtures.invoice, limit: 5 })).items[0];
    assert.equal(receiptJob.kind, "invoice");
    assert.equal(receiptJob.status, "pending");
    assert.equal(receiptJob.printer_id, fixtures.printer_id);
    step("receipt queued to the shared printer");
    // The enqueue handler reloads the page itself. Wait for the receipt preview
    // to finish rendering so the screenshot shows the receipt, not its
    // placeholder — the browser print button stays disabled until it is ready.
    await page.getByText(jobs.status.pending, { exact: true }).first().waitFor();
    const browserPrint = page.getByRole("button", { name: en.receipts.print, exact: true });
    for (let attempt = 0; attempt < 100; attempt += 1) {
      if (await browserPrint.isEnabled()) break;
      assert.ok(attempt < 99, "the receipt preview never finished rendering");
      await page.waitForTimeout(200);
    }
    await capture(page, 1440, "p2d2-invoice-1440.png");

    // Save the canonical PDF the agent will print. Reconciliation rasterizes
    // this exact document and compares it bit-for-bit with the ESC/POS stream
    // the agent produced, so "printed" means the same pixels, not just a job
    // row that says completed.
    const canonical = await api(page).get(
      origin + "/api/invoices/" + fixtures.invoice + "/receipt?format=pdf&lang=bilingual",
    );
    assert.equal(canonical.status(), 200);
    await writeFile(join(output, "canonical-invoice.pdf"), await canonical.body());
    proofs.push({ queue_phase: true });
  } else {
    // ---- verify -------------------------------------------------------------
    await page.goto(origin + "/en/settings/printers");
    await page.getByRole("heading", { name: t.title, exact: true }).waitFor();
    step("verify: settings page ready");
    // Scope the queue to this run's printer: older verification rows may still
    // be in the audit trail, and they are not what this run proved.
    const rows = page.locator("li", { hasText: fixtures.printer_name });
    // Both jobs (test page + receipt) were completed by the real agent.
    await rows.getByText(jobs.status.completed, { exact: true }).first().waitFor();
    assert.equal(
      await rows.getByText(jobs.status.completed, { exact: true }).count(),
      2,
      "the test page and the receipt should both be printed",
    );
    assert.equal(await rows.getByText(jobs.status.failed, { exact: true }).count(), 0);
    assert.equal(await rows.getByText(jobs.status.uncertain, { exact: true }).count(), 0);
    await capture(page, 1440, "p2d2-printers-1440.png");
    step("verify: both jobs completed, no failed or uncertain rows");

    // Explicit reprint: a NEW job for the same invoice, never a reopened one.
    const before = await jobsFor(page, { limit: 25 });
    const original = before.items.find(
      (job) =>
        job.printer_id === fixtures.printer_id &&
        job.kind === "invoice" &&
        job.status === "completed",
    );
    assert.ok(original, "the receipt should have been printed");
    const reprint = page.waitForResponse(
      (response) =>
        response.url().endsWith("/reprint") && response.request().method() === "POST",
    );
    await rows
      .filter({ has: page.getByText(jobs.receipt, { exact: true }) })
      .getByRole("button", { name: jobs.reprint, exact: true })
      .click();
    assert.equal((await reprint).status(), 201);
    const after = await jobsFor(page, { limit: 25 });
    const fresh = after.items.find((job) => before.items.every((item) => item.id !== job.id));
    assert.ok(fresh, "the explicit reprint must create a new job row");
    assert.equal(fresh.invoice_id, fixtures.invoice);
    assert.equal(fresh.reprint_of_job_id, original.id);
    assert.equal(fresh.status, "pending");
    assert.equal(fresh.printer_id, original.printer_id);
    await page.getByText(jobs.status.pending, { exact: true }).first().waitFor();
    step("verify: explicit reprint created a new linked job");
    proofs.push({ reprint_job: fresh.id, reprint_of: fresh.reprint_of_job_id });
  }

  // ---- Bangla, mobile -------------------------------------------------------
  const bn = await messages("bn");
  const mobile = await browser.newContext({
    viewport: { width: 375, height: 812 },
    isMobile: true,
    hasTouch: true,
    reducedMotion: "reduce",
  });
  await mobile.addCookies(await context.cookies());
  const bnPage = await mobile.newPage();
  bnPage.setDefaultTimeout(20_000);
  bnPage.setDefaultNavigationTimeout(30_000);
  bnPage.on("pageerror", (error) => browserErrors.push(error.message));
  await bnPage.goto(origin + "/bn/settings/printers");
  await bnPage.getByRole("heading", { name: bn.printers.title, exact: true }).waitFor();
  await printerCard(bnPage, fixtures.printer_name).waitFor();
  await bnPage.getByText(bn.printJobs.title, { exact: true }).waitFor();
  await capture(bnPage, 375, "p2d2-printers-bn-375.png");
  step("Bangla mobile layout captured");
  await mobile.close();

  assert.deepEqual(browserErrors, []);
  await context.close();
  await writeFile(resultFile, JSON.stringify({ phase, proofs }), "utf-8");
  console.log(
    "printing " +
      phase +
      " workflow passed: shared printer across counters, one-time agent token, " +
      "test page, queue, printed status, explicit reprint, English and Bangla layouts.",
  );
} finally {
  await browser.close();
}
