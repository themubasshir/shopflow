import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { paperWidthMm, printablePageRule, type ReceiptLanguage } from "./paper";

/**
 * Printer calibration page for the shared thermal printer.
 *
 * Rendered through the exact same HTML → PDF → raster path as a real receipt so
 * an owner can verify a freshly registered printer end-to-end: transport, DPI,
 * dot-width alignment, monochrome threshold and the cutter. It contains a
 * millimetre ruler, dot-grid bands, a Bangla shaping sample and solid fills —
 * nothing financial, so it is safe to print at any time.
 */

let fontData: Promise<string[]> | undefined;

function font() {
  fontData ??= Promise.all(
    ["Regular", "Bold"].map(async (weight) =>
      (
        await readFile(
          join(process.cwd(), "src/lib/receipt/assets", `NotoSansBengali-${weight}.ttf`),
        )
      ).toString("base64"),
    ),
  ).catch((error: unknown) => {
    fontData = undefined;
    throw error;
  });
  return fontData;
}

const copy = {
  en: {
    heading: "Printer test page",
    printer: "Printer",
    width: "Printable width",
    dots: "Dot width",
    dpi: "Resolution",
    date: "Printed at",
    ruler: "Width calibration — the bar must span the full paper width",
    scale: "Scale · 0–80 mm",
    grid: "1 mm grid · every 5th line heavier",
    bangla: "Bangla shaping",
    banglaSample: "বাংলা লেখা পরিষ্কারভাবে ছাপা হচ্ছে ৳ ১২৩৪.৫০",
    solid: "Solid black fill — should be fully inked, no banding",
    align: "Alignment",
    aligned: "Left edge ·· aligned ·· Right edge",
    cut: "If this line is visible the receipt was cut here",
  },
  bn: {
    heading: "প্রিন্টার পরীক্ষা পাতা",
    printer: "প্রিন্টার",
    width: "ছাপার প্রস্থ",
    dots: "ডট প্রস্থ",
    dpi: "রেজোলিউশন",
    date: "ছাপার সময়",
    ruler: "প্রস্থ মাপকাঠি — বারটি পুরো কাগজের প্রস্থ জুড়ে থাকতে হবে",
    scale: "স্কেল · ০–৮০ মিমি",
    grid: "১ মিমি গ্রিড · প্রতি ৫ম দাগ মোটা",
    bangla: "বাংলা লেখার আকৃতি",
    banglaSample: "বাংলা লেখা পরিষ্কারভাবে ছাপা হচ্ছে ৳ ১২৩৪.৫০",
    solid: "গাঢ় কালো অংশ — পুরোপুরি কালো হওয়া উচিত, ডোরাকাটা নয়",
    align: "সরলরেখা",
    aligned: "বাম প্রান্ত ·· সমান ·· ডান প্রান্ত",
    cut: "এই লাইনটি দেখা গেলে রসিদ এখানেই কাটা হয়েছে",
  },
};

function html(value: string) {
  return value.replace(
    /[&<>"']/g,
    (character) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character] ?? "",
  );
}

export interface TestPageOptions {
  language: ReceiptLanguage;
  printerName: string;
  paperWidthMm: number;
  dotsWidth: number;
  dpi: number;
  now?: Date;
}

export async function testPageHtml(options: TestPageOptions) {
  const language: ReceiptLanguage = options.language === "bilingual" ? "bilingual" : options.language;
  const en = copy.en;
  const bn = copy.bn;
  const line = (key: keyof typeof en) =>
    language === "bn"
      ? html(bn[key])
      : `${html(en[key])} <span lang="bn" class="translation">${html(bn[key])}</span>`;
  const text = (value: string) => html(value);
  const pageLanguage = language === "bn" ? "bn" : "en";
  const width = Math.min(76, Math.max(58, options.paperWidthMm - 8));
  const [regular, bold] = await font();
  const millimeters = Array.from({ length: 81 }, (_, index) => index);
  const ruler = millimeters
    .map(
      (mm) =>
        `<span class="tick${mm % 10 === 0 ? " major" : ""}" style="left:${(mm / 80) * 100}%"></span>`,
    )
    .join("");
  const scale = millimeters
    .filter((mm) => mm % 10 === 0)
    .map((mm) => `<span class="scalelabel" style="left:${(mm / 80) * 100}%">${mm}</span>`)
    .join("");
  const grid = Array.from({ length: 81 }, (_, index) => index)
    .map(
      (mm) =>
        `<span class="gridline${mm % 5 === 0 ? " heavy" : ""}" style="left:${(mm / 80) * 100}%"></span>`,
    )
    .join("");
  const timestamp = new Intl.DateTimeFormat(language === "bn" ? "bn-BD-u-nu-latn" : "en-GB", {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(options.now ?? new Date());

  return `<!doctype html>
<html lang="${pageLanguage}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Printer test page</title>
<style id="print-page">${printablePageRule(250)}</style>
<style>
@font-face{font-family:Receipt Noto;src:url(data:font/ttf;base64,${regular}) format("truetype");font-weight:400;font-display:block}
@font-face{font-family:Receipt Noto;src:url(data:font/ttf;base64,${bold}) format("truetype");font-weight:700;font-display:block}
*{box-sizing:border-box}
html,body{margin:0;padding:0;background:#fff;color:#000}
body{width:${paperWidthMm}mm;max-width:100%;margin:auto;font:450 3.05mm/1.45 "Receipt Noto",sans-serif}
main{width:${width}mm;max-width:calc(100% - 2mm);margin:auto;padding:3.5mm 0}
h1,h2,p,dl,dd{margin:0}
h1{font-size:4.6mm;line-height:1.24;font-weight:760;text-align:center}
h2{font-size:3.4mm;line-height:1.33;font-weight:720;margin-bottom:1mm}
strong{font-weight:700}
.translation{display:block;font-weight:450}
.rule{border-top:.25mm dashed #000;margin-top:2.2mm;padding-top:1.6mm}
.pair{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:1.5mm;align-items:baseline}
.pair dd{text-align:right;font-variant-numeric:tabular-nums}
.bar{position:relative;height:5mm;margin-top:.6mm;border:.25mm solid #000;overflow:hidden}
.bar .fill{position:absolute;inset:0;background:#000}
.ticks{position:relative;height:3.2mm;margin-top:.4mm;border-bottom:.25mm solid #000}
.tick{position:absolute;top:0;width:.2mm;height:1.6mm;background:#000}
.tick.major{height:3mm;width:.28mm}
.scale{position:relative;height:3.4mm;margin-top:.2mm;font-size:2.4mm}
.scalelabel{position:absolute;top:0;transform:translateX(-50%);font-variant-numeric:tabular-nums}
.grid{position:relative;height:12mm;margin-top:1mm;border:.25mm solid #000}
.gridline{position:absolute;top:0;bottom:0;width:.12mm;background:#000;opacity:.45}
.gridline.heavy{width:.25mm;opacity:1}
.solid{height:8mm;margin-top:1mm;background:#000}
.align{margin-top:1mm;font-size:2.8mm;text-align:center;border-left:.4mm solid #000;border-right:.4mm solid #000;padding:.6mm 0}
.bangla{font-size:3.6mm;line-height:1.5;margin-top:.6mm}
.cut{margin-top:2mm;font-size:2.7mm;text-align:center;border-top:.25mm dashed #000;padding-top:1mm}
</style></head>
<body><main data-receipt>
<header>
  <h1>${line("heading")}</h1>
</header>
<dl class="rule">
  <div class="pair"><dt>${line("printer")}</dt><dd>${text(options.printerName)}</dd></div>
  <div class="pair"><dt>${line("width")}</dt><dd>${options.paperWidthMm} mm</dd></div>
  <div class="pair"><dt>${line("dots")}</dt><dd>${options.dotsWidth} dots</dd></div>
  <div class="pair"><dt>${line("dpi")}</dt><dd>${options.dpi} dpi</dd></div>
  <div class="pair"><dt>${line("date")}</dt><dd>${text(timestamp)}</dd></div>
</dl>
<section class="rule">
  <h2>${line("ruler")}</h2>
  <div class="bar"><div class="fill"></div></div>
  <div class="ticks">${ruler}</div>
  <div class="scale">${scale}</div>
</section>
<section class="rule">
  <h2>${line("grid")}</h2>
  <div class="grid">${grid}</div>
</section>
<section class="rule">
  <h2>${line("bangla")}</h2>
  <p class="bangla" lang="bn">${html(bn.banglaSample)}</p>
</section>
<section class="rule">
  <h2>${line("solid")}</h2>
  <div class="solid"></div>
</section>
<section class="rule">
  <h2>${line("align")}</h2>
  <p class="align">${line("aligned")}</p>
</section>
<footer class="cut">${line("cut")}</footer>
</main></body></html>`;
}
