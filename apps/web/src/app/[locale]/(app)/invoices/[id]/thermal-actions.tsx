"use client";

import { useState } from "react";
import { Printer, RotateCcw } from "lucide-react";
import { useTranslations } from "next-intl";
import { Badge } from "@/components/ui/badge";
import { secondaryButton } from "@/components/ui/pos-form";
import type { PrintJobOut, PrinterOut } from "@/types";

/**
 * Thermal queue controls for one invoice: send it to a counter printer, and
 * show whether the job is still queued, printed, or failed. A failed or
 * uncertain job can be retried/reprinted explicitly — the queue never retries
 * on its own, and printing never touches the invoice record.
 */
export function ThermalActions({
  invoiceId,
  printers,
  jobs,
}: {
  invoiceId: string;
  printers: PrinterOut[];
  jobs: PrintJobOut[];
}) {
  const t = useTranslations("printJobs");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [printerId, setPrinterId] = useState(
    printers.find((p) => p.counter_ids.length > 0)?.id ?? printers[0]?.id ?? "",
  );

  async function enqueue() {
    if (pending) return;
    setPending(true);
    setError(null);
    try {
      const res = await fetch("/api/printing/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          invoice_id: invoiceId,
          printer_id: printerId || null,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setError(body.code ?? "unknown");
        return;
      }
      window.location.reload();
    } catch {
      setError("network");
    } finally {
      setPending(false);
    }
  }

  async function reprint(job: PrintJobOut) {
    setPending(true);
    setError(null);
    try {
      const res = await fetch(`/api/printing/jobs/${job.id}/reprint`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setError(body.code ?? "unknown");
        return;
      }
      window.location.reload();
    } catch {
      setError("network");
    } finally {
      setPending(false);
    }
  }

  const latest = jobs[0];

  if (printers.length === 0) {
    return (
      <p className="text-sm text-[var(--color-muted-foreground)]">{t("noPrinters")}</p>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-end gap-2">
        {printers.length > 1 ? (
          <label className="grid gap-1 text-sm font-medium" htmlFor="print-job-printer">
            {t("printer")}
            <select
              id="print-job-printer"
              aria-label={t("printer")}
              className="min-h-11 rounded-lg border border-[var(--color-border)] bg-white px-3 text-base"
              value={printerId}
              onChange={(event) => setPrinterId(event.target.value)}
            >
              {printers.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <button
          type="button"
          onClick={() => void enqueue()}
          disabled={pending}
          className={secondaryButton}
        >
          <Printer size={18} aria-hidden="true" />
          {pending ? t("sending") : t("sendToPrinter")}
        </button>
        {latest && (latest.status === "failed" || latest.status === "uncertain") ? (
          <button
            type="button"
            onClick={() => void reprint(latest)}
            disabled={pending}
            className={secondaryButton}
          >
            <RotateCcw size={18} aria-hidden="true" />
            {t("reprint")}
          </button>
        ) : null}
      </div>
      {latest ? (
        <p className="flex flex-wrap items-center gap-2 text-xs text-[var(--color-muted-foreground)]">
          <Badge
            variant={
              latest.status === "completed"
                ? "success"
                : latest.status === "failed" || latest.status === "uncertain"
                  ? "danger"
                  : "warning"
            }
          >
            {t(`status.${latest.status}`)}
          </Badge>
          {latest.error_code ? <span>{latest.error_code}</span> : null}
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="text-sm text-red-700">
          {t(`errors.${error}` as never)}
        </p>
      ) : null}
    </div>
  );
}
