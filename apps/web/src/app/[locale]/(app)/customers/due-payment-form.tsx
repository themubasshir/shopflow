"use client";

import { useRef, useState, type FormEvent } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "@/i18n/navigation";
import { ApiError, browserRequest, newIdempotencyKey } from "@/lib/api-client";
import { errorCode, fieldClass, minorUnits, primaryButton, secondaryButton } from "@/components/ui/pos-form";
import { formatBDT } from "@/lib/format";
import type { DuePaymentCreate, DuePaymentOut, InvoiceOut } from "@/types";

export function DuePaymentForm({ customerId, invoice }: { customerId: string; invoice: InvoiceOut }) {
  const t = useTranslations("customers");
  const locale = useLocale();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState<{ amount: string; outstanding: string } | null>(null);
  const inFlight = useRef(false);
  const attempt = useRef<{ key: string; body: DuePaymentCreate } | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (inFlight.current) return;
    setError("");
    if (!uncertain || !attempt.current) {
      const data = new FormData(event.currentTarget);
      const amount = minorUnits(String(data.get("amount")));
      if (amount === null || amount <= 0 || amount > (minorUnits(invoice.due_total) ?? 0)) {
        setError("overpayment");
        return;
      }
      attempt.current = {
        key: newIdempotencyKey(),
        body: {
          amount: (amount / 100).toFixed(2),
          method: data.get("method") as DuePaymentCreate["method"],
          reference: String(data.get("reference")).trim() || null,
        },
      };
    }
    inFlight.current = true;
    setSaving(true);
    try {
      const result = await browserRequest<DuePaymentOut>(`/api/customers/${customerId}/invoices/${invoice.id}/payments`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": attempt.current.key },
        body: JSON.stringify(attempt.current.body),
      });
      setSuccess({ amount: result.payment.amount, outstanding: result.outstanding_due });
      setUncertain(false);
      setOpen(false);
      router.refresh();
    } catch (err) {
      const unknownOutcome = !(err instanceof ApiError) || err.status >= 500;
      setUncertain(unknownOutcome);
      setError(unknownOutcome ? "retryPayment" : errorCode(err));
      if (err instanceof ApiError && err.code === "overpayment") router.refresh();
    } finally {
      inFlight.current = false;
      setSaving(false);
    }
  }

  return (
    <>
      {success && <p className="mt-2 text-sm text-[var(--color-primary-strong)]" role="status">{t("paymentRecorded", {
        amount: formatBDT(success.amount, locale), outstanding: formatBDT(success.outstanding, locale),
      })}</p>}
      {!open && Number(invoice.due_total) > 0 && (
        <button className={secondaryButton} onClick={() => { setError(""); setSuccess(null); setOpen(true); }}>{t("collect")}</button>
      )}
      {open && (
        <form onSubmit={submit} className="mt-3 space-y-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-primary-050)] p-3">
          <fieldset disabled={saving || uncertain} className="grid gap-3 sm:grid-cols-3">
            <label className="space-y-1 text-sm font-medium">
              <span>{t("amount")}</span>
              <input name="amount" inputMode="decimal" required defaultValue={invoice.due_total} className={fieldClass} aria-invalid={error === "overpayment"} aria-describedby={error === "overpayment" ? `due-error-${invoice.id}` : undefined} />
            </label>
            <label className="space-y-1 text-sm font-medium">
              <span>{t("method")}</span>
              <select name="method" className={fieldClass}>
                {(["cash", "bkash", "nagad"] as const).map((method) => <option key={method} value={method}>{t(`methods.${method}`)}</option>)}
              </select>
            </label>
            <label className="space-y-1 text-sm font-medium">
              <span>{t("reference")}</span>
              <input name="reference" maxLength={120} className={fieldClass} />
            </label>
          </fieldset>
          {error && <p id={`due-error-${invoice.id}`} role="alert" className="text-sm text-red-700">{t.has(`errors.${error}`) ? t(`errors.${error}`) : t("errors.unknown")}</p>}
          <div className="flex flex-wrap gap-2">
            <button className={primaryButton} disabled={saving}>{t(saving ? "saving" : uncertain ? "retry" : "recordPayment")}</button>
            {!uncertain && <button type="button" disabled={saving} className={secondaryButton} onClick={() => setOpen(false)}>{t("cancel")}</button>}
          </div>
        </form>
      )}
    </>
  );
}
