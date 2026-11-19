import { readFile } from "node:fs/promises";
import { join } from "node:path";
import type { InvoiceReceipt } from "@/types";
import { receiptLabels } from "./labels";
import { paperWidthMm, printablePageRule, type ReceiptLanguage } from "./paper";

let fontData: Promise<string[]> | undefined;

function font() {
  fontData ??= Promise.all(["Regular", "Bold"].map(async (weight) =>
    (await readFile(join(process.cwd(), "src/lib/receipt/assets", "NotoSansBengali-" + weight + ".ttf"))).toString("base64")
  ))
    .catch((error: unknown) => { fontData = undefined; throw error; });
  return fontData;
}

const entities: Record<string, string> = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
function html(value: string) {
  return value.replace(/[&<>"']/g, (character) => entities[character]);
}

function bilingual(en: string | null | undefined, bn: string | null | undefined, language: ReceiptLanguage) {
  if (language === "bilingual" && en && bn && en !== bn) {
    return `${html(en)} <span lang="bn" class="translation">${html(bn)}</span>`;
  }
  return html((language === "bn" ? bn || en : en || bn) ?? "");
}

// Secondary detail (a masked phone, a counter code) belongs on its own line.
// Appending it inline after a block-level translation leaves the separator
// dangling at the start of a line, which reads like a truncated value.
function detail(value: string, meta: string | null | undefined) {
  return meta ? `${value}<span class="sub">${meta}</span>` : value;
}

function formatMoney(amount: string, currency: string) {
  const [whole, fraction = ""] = amount.split(".");
  const sign = whole.startsWith("-") ? "-" : "";
  const grouped = whole.replace(/^-/, "").replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const prefix = currency === "BDT" ? "৳" : `${currency} `;
  return html(`${sign}${prefix}${grouped}.${fraction.padEnd(2, "0")}`);
}

function nonzero(amount: string) {
  return /[1-9]/.test(amount);
}

function timestamp(value: string, timezone: string, language: ReceiptLanguage) {
  const options: Intl.DateTimeFormatOptions = {
    dateStyle: "medium", timeStyle: "short", timeZone: timezone,
  };
  const locale = language === "bn" ? "bn-BD-u-nu-latn" : "en-GB";
  try {
    return new Intl.DateTimeFormat(locale, options).format(new Date(value));
  } catch {
    return new Intl.DateTimeFormat(locale, { ...options, timeZone: "UTC" }).format(new Date(value));
  }
}

export async function receiptHtml(receipt: InvoiceReceipt, language: ReceiptLanguage) {
  const id = receipt.identity;
  const brand = id.branding;
  const labels = receiptLabels.en;
  const label = (key: keyof typeof labels) =>
    bilingual(labels[key], receiptLabels.bn[key], language);
  const money = (amount: string) => formatMoney(amount, id.currency);
  const pair = (name: string, value: string, options = "") =>
    `<div class="pair ${options}"><dt>${name}</dt><dd>${value}</dd></div>`;
  const optional = (name: keyof typeof labels, value: string | null | undefined) =>
    value ? pair(label(name), value) : "";
  const financial = (name: keyof typeof labels, value: string, always = false, classes = "number") =>
    always || nonzero(value) ? pair(label(name), money(value), classes) : "";
  const heading = bilingual(brand?.heading_en || labels.heading, brand?.heading_bn || receiptLabels.bn.heading, language);
  const shopName = bilingual(brand?.shop_name_en, brand?.shop_name_bn, language);
  const customerName = bilingual(id.customer_name, id.customer_name_bn, language);
  const counter = bilingual(id.counter_name_en, id.counter_name_bn, language);
  const customer = id.customer_phone_masked
    ? detail(customerName || "", html(id.customer_phone_masked))
    : customerName;
  const footer = bilingual(brand?.footer_en, brand?.footer_bn, language);
  const returns = bilingual(brand?.return_policy_en, brand?.return_policy_bn, language);
  const pageLanguage = language === "bn" ? "bn" : "en";
  const printWidth = Math.min(76, Math.max(58, brand?.printable_width_mm ?? 72));

  const lines = receipt.items.map((item) => {
    const storedQuantity = item.quantity.includes(".") ? item.quantity.replace(/0+$/, "").replace(/\.$/, "") : item.quantity;
    const unit = bilingual(item.unit_en, item.unit_bn, language);
    const batchLinks = item.batch_allocations?.map((batch) =>
      `<div class="meta">${label("batch")} ${html(batch.batch_number)} · ${label("expiry")} ${html(batch.expiry_date)} · ${html(batch.quantity.includes(".") ? batch.quantity.replace(/0+$/, "").replace(/\.$/, "") : batch.quantity)}</div>`
    ).join("");
    return `<li class="item">
      <div class="name">${bilingual(item.description, item.name_bn, language)}</div>
      ${batchLinks || (item.batch || item.expiry ? `<div class="meta">${item.batch ? label("batch") + " " + html(item.batch) : ""}${item.batch && item.expiry ? " · " : ""}${item.expiry ? label("expiry") + " " + html(item.expiry) : ""}</div>` : "")}
      <div class="line"><div><span class="quantity">${html(storedQuantity)}</span>${unit ? " " + unit : ""} × <span class="quantity">${money(item.unit_price)}</span></div><strong class="quantity">${money(item.line_total)}</strong></div>
      ${nonzero(item.line_discount) ? `<div class="meta">${label("line_discount")} ${money(item.line_discount)}</div>` : ""}
    </li>`;
  }).join("");
  const tenders = receipt.payments.map((entry) =>
    pair(Object.hasOwn(labels, entry.method) ? label(entry.method as keyof typeof labels) : html(entry.method),
      money(entry.amount), "number")
  ).join("");
  const showPoints = receipt.loyalty_points_balance !== null || receipt.loyalty_points_earned || receipt.loyalty_points_redeemed;
  const [regular, bold] = await font();

  return `<!doctype html>
<html lang="${pageLanguage}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>${html(receipt.invoice_number)}</title>
<style id="print-page">${printablePageRule(250)}</style>
<style>
@font-face{font-family:Receipt Noto;src:url(data:font/ttf;base64,${regular}) format("truetype");font-weight:400;font-display:block}
@font-face{font-family:Receipt Noto;src:url(data:font/ttf;base64,${bold}) format("truetype");font-weight:700;font-display:block}
*{box-sizing:border-box}
html,body{margin:0;padding:0;background:#fff;color:#000}
body{width:${paperWidthMm}mm;max-width:100%;margin:auto;font:450 3.05mm/1.47 "Receipt Noto",sans-serif}
main{width:${printWidth}mm;max-width:calc(100% - 2mm);margin:auto;padding:3.5mm 0;overflow-wrap:anywhere}
header,footer{text-align:center}
h1,h2,p,dl,dd,ol{margin:0}
h1{font-size:4.6mm;line-height:1.24;font-weight:760}
h2{font-size:3.65mm;line-height:1.33;font-weight:720}
header h2{margin-top:2mm}
strong,.name{font-weight:700}
.rule{border-top:.25mm dashed #000;margin-top:2mm;padding-top:1.6mm}
.terminal{border-top:.35mm solid #000;padding-top:1.2mm}
.pair,.line,.column-head{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:1.5mm;align-items:baseline}
/* Label/value rows: the label takes only the width its own text needs (capped at
   just over half the row) and the value grows into every remaining millimetre.
   A greedy full-width label track plus a capped value box is what squeezed
   bilingual values into a narrow right-aligned column; a value that keeps its
   max-content width instead starves the label, which is the same bug mirrored. */
.pair{display:flex;gap:1.5mm;align-items:baseline}
.pair>dt{flex:0 0 auto;max-width:52%}
.pair>:last-child{flex:1 1 0;min-width:0;text-align:right}
.sub{display:block;font-size:2.8mm}
.number dd,.quantity{font-variant-numeric:tabular-nums lining-nums;white-space:nowrap;max-width:none}
.item{padding:.9mm 0 1.15mm;break-inside:avoid}
.column-head{font-weight:740;border-bottom:.25mm solid #000;padding-bottom:.8mm}
ol{list-style:none;padding:0}
.name{white-space:pre-line}
.meta{font-size:2.8mm}
.translation{display:block}
.line .translation{display:inline}
.line .translation::before{content:" / "}
.brand-line,footer p{white-space:pre-line}
.total{font-size:3.65mm;font-weight:760}
.due{font-weight:720}
.status{border:.35mm solid #000;letter-spacing:.28mm;font-weight:800;margin-top:1.8mm;padding:.5mm}
.keep{break-inside:avoid}
footer p+p{margin-top:1.5mm}
@media print {html,body{max-width:none}body{width:${paperWidthMm}mm}main{max-width:none}}
</style></head>
<body><main data-receipt>
<header class="keep">
  ${shopName ? `<h1>${shopName}</h1>` : ""}
  ${brand?.address ? `<p class="brand-line">${html(brand.address)}</p>` : ""}
  ${brand?.phone ? `<p>${html(brand.phone)}</p>` : ""}
  ${brand?.trade_license ? `<p>${label("trade_license")} ${html(brand.trade_license)}</p>` : ""}
  ${brand?.tax_registration ? `<p>${label("tax_registration")} ${html(brand.tax_registration)}</p>` : ""}
  <h2>${heading}</h2>
  ${receipt.status === "finalized" ? "" : `<p class="status">${label(receipt.status)}</p>`}
</header>
<dl class="rule keep">
  ${pair(label("invoice"), `<strong>${html(receipt.invoice_number)}</strong>`)}
  ${optional("time", receipt.issued_at ? html(timestamp(receipt.issued_at, id.timezone, language)) : null)}
  ${optional("voided_at", receipt.voided_at ? html(timestamp(receipt.voided_at, id.timezone, language)) : null)}
  ${optional("counter", [id.counter_code && html(id.counter_code), counter].filter(Boolean).join(" · "))}
  ${optional("cashier", id.cashier && html(id.cashier))}
  ${optional("customer", customer)}
</dl>
<section class="rule">
  <div class="column-head"><span>${label("items")}</span><span>${label("amount")}</span></div>
  <ol>${lines}</ol>
</section>
<dl class="rule keep">
  ${financial("subtotal", receipt.subtotal, true)}
  ${financial("discount", receipt.discount_total)}
  ${financial("loyalty_discount", receipt.loyalty_discount)}
  ${financial("tax", receipt.tax_total)}
  ${financial("total", receipt.total, true, "number total terminal")}
</dl>
<section class="rule">
  ${tenders ? `<h2>${label("tender")}</h2><dl>${tenders}</dl>` : ""}
  <dl class="keep">${financial("paid", receipt.paid_total, true)}${financial("due", receipt.due_total, true, "number due")}</dl>
</section>
${showPoints ? `<dl class="rule keep">
  ${pair(label("points_redeemed"), String(receipt.loyalty_points_redeemed), "number")}
  ${pair(label("points_earned"), String(receipt.loyalty_points_earned), "number")}
  ${receipt.loyalty_points_balance === null ? "" : pair(label("points_balance"), String(receipt.loyalty_points_balance), "number")}
</dl>` : ""}
${footer || returns || id.source !== "sale" ? `<footer class="rule">
  ${footer ? `<p>${footer}</p>` : ""}
  ${returns ? `<p><strong>${label("return_policy")}</strong><br>${returns}</p>` : ""}
  ${id.source === "sale" ? "" : `<p class="meta">${label(id.source === "legacy_migration" ? "legacy" : "unavailable")}</p>`}
</footer>` : ""}
</main></body></html>`;
}
