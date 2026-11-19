"use client";

import { useState } from "react";
import { RotateCcw, RefreshCw } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRouter } from "@/i18n/navigation";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { secondaryButton } from "@/components/ui/pos-form";
import { formatDate, formatTime } from "@/lib/format";
import type { PrintJobOut } from "@/types";
import type { Locale } from "@/i18n/config";

const statusVariant: Record<string, "success" | "warning" | "danger" | "outline" | "default"> = {
  pending: "warning",
  claimed: "default",
  printing: "default",
  completed: "success",
  failed: "danger",
  uncertain: "danger",
  cancelled: "outline",
};

export function JobsList({
  locale,
  jobs,
  printers,
}: {
  locale: Locale;
  jobs: PrintJobOut[];
  printers: { id: string; name: string }[];
}) {
  const t = useTranslations("printJobs");
  const router = useRouter();
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const printerName = (id: string) => printers.find((p) => p.id === id)?.name ?? "—";

  async function act(job: PrintJobOut, action: "retry" | "reprint" | "cancel") {
    if (pendingId) return;
    setPendingId(job.id);
    setError(null);
    try {
      const res = await fetch(`/api/printing/jobs/${job.id}/${action}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setError(body.code ?? "unknown");
        return;
      }
      router.refresh();
    } catch {
      setError("network");
    } finally {
      setPendingId(null);
    }
  }

  return (
    <Card>
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 text-base font-semibold">
          <RotateCcw size={17} aria-hidden="true" />
          {t("title")}
        </h2>
        <button
          type="button"
          onClick={() => router.refresh()}
          className={secondaryButton}
          aria-label={t("refresh")}
        >
          <RefreshCw size={16} aria-hidden="true" />
        </button>
      </div>
      {error ? (
        <p role="alert" className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm font-medium text-red-700">
          {t(`errors.${error}` as never)}
        </p>
      ) : null}
      {jobs.length === 0 ? (
        <EmptyState title={t("empty")} hint={t("emptyHint")} />
      ) : (
        <ul className="divide-y divide-[var(--color-border)]">
          {jobs.map((job) => (
            <li key={job.id} className="flex items-center justify-between gap-3 py-3">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="truncate text-sm font-semibold">
                    {job.kind === "test_page"
                      ? t("testPage")
                      : job.reprint_of_job_id
                        ? t("reprint")
                        : t("receipt")}
                  </span>
                  <Badge variant={statusVariant[job.status] ?? "outline"}>
                    {t(`status.${job.status}`)}
                  </Badge>
                  {job.attempts > 1 ? (
                    <Badge variant="outline">×{job.attempts}</Badge>
                  ) : null}
                </div>
                <p className="mt-0.5 truncate text-xs text-[var(--color-muted-foreground)]">
                  {printerName(job.printer_id)}
                  {" · "}
                  {formatDate(job.created_at, locale)} {formatTime(job.created_at, locale)}
                  {job.error_code ? ` · ${job.error_code}` : ""}
                </p>
                {job.error_message ? (
                  <p className="mt-0.5 truncate text-xs text-red-600" title={job.error_message}>
                    {job.error_message}
                  </p>
                ) : null}
              </div>
              <div className="flex shrink-0 gap-1">
                {job.status === "failed" || job.status === "cancelled" ? (
                  <button
                    type="button"
                    onClick={() => void act(job, "retry")}
                    disabled={pendingId === job.id}
                    className="min-h-[36px] rounded-lg px-2.5 text-xs font-semibold text-[var(--color-primary)] hover:bg-[var(--color-primary-100)] disabled:opacity-50"
                  >
                    {t("retry")}
                  </button>
                ) : null}
                {(job.status === "completed" || job.status === "uncertain" || job.kind === "test_page") ? (
                  <button
                    type="button"
                    onClick={() => void act(job, "reprint")}
                    disabled={pendingId === job.id}
                    className="min-h-[36px] rounded-lg px-2.5 text-xs font-semibold text-[var(--color-primary)] hover:bg-[var(--color-primary-100)] disabled:opacity-50"
                  >
                    {t("reprint")}
                  </button>
                ) : null}
                {job.status === "pending" || job.status === "failed" || job.status === "uncertain" ? (
                  <button
                    type="button"
                    onClick={() => void act(job, "cancel")}
                    disabled={pendingId === job.id}
                    className="min-h-[36px] rounded-lg px-2.5 text-xs font-semibold text-red-600 hover:bg-red-50 disabled:opacity-50"
                  >
                    {t("cancel")}
                  </button>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
