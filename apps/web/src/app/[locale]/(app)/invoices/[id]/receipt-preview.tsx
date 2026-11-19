"use client";

import { useCallback, useRef, useState } from "react";
import { Download, Printer, ReceiptText } from "lucide-react";
import { useTranslations } from "next-intl";
import { Card } from "@/components/ui/card";
import { fieldClass, primaryButton, secondaryButton } from "@/components/ui/pos-form";
import { printablePageRule, receiptLanguages, receiptPageHeight, type ReceiptLanguage } from "@/lib/receipt/paper";

export function ReceiptPreview({ id, number, initialLanguage }: {
  id: string;
  number: string;
  initialLanguage: ReceiptLanguage;
}) {
  const t = useTranslations("receipts");
  const iframe = useRef<HTMLIFrameElement>(null);
  const [language, setLanguage] = useState(initialLanguage);
  const [preview, setPreview] = useState<"loading" | "ready" | "failed">("loading");
  const [attempt, setAttempt] = useState(0);
  const [height, setHeight] = useState(150);
  const [downloading, setDownloading] = useState(false);
  const [actionError, setActionError] = useState<"downloadError" | "printError" | null>(null);
  const source = `/api/invoices/${id}/receipt?lang=${language}`;

  const prepare = useCallback(async (frame: HTMLIFrameElement) => {
    const document = frame.contentDocument;
    const main = document?.querySelector<HTMLElement>("[data-receipt]");
    if (!document || !main) {
      if (frame === iframe.current) setPreview("failed");
      return;
    }
    await document.fonts.ready;
    if (frame !== iframe.current) return;
    const contentHeight = main.getBoundingClientRect().height;
    setHeight(Math.ceil(contentHeight) + 2);
    setPreview("ready");
  }, []);

  const attach = useCallback((frame: HTMLIFrameElement | null) => {
    iframe.current = frame;
    const document = frame?.contentDocument;
    if (frame && document?.readyState === "complete" && document.URL !== "about:blank") {
      void prepare(frame);
    }
  }, [prepare]);

  function print() {
    setActionError(null);
    try {
      const frame = iframe.current;
      const main = frame?.contentDocument?.querySelector<HTMLElement>("[data-receipt]");
      const style = frame?.contentDocument?.getElementById("print-page");
      if (!main || !style || !frame?.contentWindow) throw new Error("Receipt frame is unavailable");
      style.textContent = printablePageRule(receiptPageHeight(main.getBoundingClientRect().height));
      frame.contentWindow.focus();
      frame.contentWindow.print();
    } catch {
      setActionError("printError");
    }
  }

  async function download() {
    setActionError(null);
    setDownloading(true);
    try {
      const response = await fetch(source + "&format=pdf", { cache: "no-store" });
      if (!response.ok) throw new Error("Receipt download failed");
      const objectUrl = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = number.replace(/[^A-Za-z0-9_-]+/g, "_") + "-" + language + ".pdf";
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    } catch {
      setActionError("downloadError");
    } finally {
      setDownloading(false);
    }
  }

  return (
    <>
      <Card className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
        <div className="flex items-center gap-3">
          <span className="grid size-11 shrink-0 place-items-center rounded-lg bg-[var(--color-primary-100)] text-[var(--color-primary-strong)]">
            <ReceiptText size={22} aria-hidden="true" />
          </span>
          <div>
            <h1 className="text-xl font-bold">{t("preview")}</h1>
            <p className="text-sm tabular-nums text-[var(--color-muted-foreground)]">{number}</p>
          </div>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <label className="grid w-full gap-1 text-sm font-medium sm:w-44" htmlFor="receipt-language">
            {t("language")}
            <select id="receipt-language" className={fieldClass} value={language} onChange={(event) => {
              const selected = event.target.value as ReceiptLanguage;
              if (selected === language) return;
              setLanguage(selected);
              setPreview("loading");
              setActionError(null);
            }}>
              {receiptLanguages.map((option) => <option key={option} value={option}>{t("languages." + option)}</option>)}
            </select>
          </label>
          <button type="button" className={primaryButton} onClick={print} disabled={preview !== "ready"}>
            <Printer size={18} aria-hidden="true" />{t("print")}
          </button>
          <button type="button" className={secondaryButton} onClick={download} disabled={downloading}>
            <Download size={18} aria-hidden="true" />{t(downloading ? "downloading" : "download")}
          </button>
        </div>
        {actionError && <p role="alert" className="text-sm text-red-700 lg:col-span-2">{t(actionError)}</p>}
      </Card>
      <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-muted)] p-2 sm:p-5">
        {preview === "loading" && <p role="status" className="py-3 text-center text-sm">{t("loading")}</p>}
        {preview === "failed" && (
          <div className="grid justify-items-center gap-2 py-4">
            <p role="alert" className="text-sm text-red-700">{t("loadError")}</p>
            <button type="button" className={secondaryButton} onClick={() => {
              setPreview("loading");
              setAttempt((previous) => previous + 1);
            }}>{t("retry")}</button>
          </div>
        )}
        <iframe key={source + attempt} ref={attach} src={source} title={t("preview")}
          onLoad={(event) => void prepare(event.currentTarget)} onError={() => setPreview("failed")}
          className="mx-auto block w-full max-w-[80mm] border-0 bg-white shadow-md"
          style={{ height }} hidden={preview === "failed"} />
      </div>
    </>
  );
}
