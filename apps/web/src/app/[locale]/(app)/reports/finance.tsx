"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Card } from "@/components/ui/card";
import { fieldClass, primaryButton, secondaryButton } from "@/components/ui/pos-form";
import { formatBDT, formatQuantity } from "@/lib/format";
import type { FinanceReport, Reconciliation } from "@/types";
import { FetchStatus, Field, Pager, useRemote, value } from "../inventory/operations/shared";

const groups = {
  sales: ["gross_sales", "discounts", "customer_returns", "net_sales"],
  payments: ["collections", "refunds", "pending_refunds", "outstanding_dues"],
  suppliers: ["supplier_payables", "supplier_credits", "supplier_receivables", "supplier_refunds"],
  loyalty: ["loyalty_issued", "loyalty_redeemed", "loyalty_reversed", "loyalty_restored"],
} as const;
const areas = ["invoice", "customer_due", "refund", "loyalty", "supplier", "product", "batch", "allocation", "lot", "valuation"];

export function FinancePanel() {
  const t = useTranslations("returns");
  const locale = useLocale();
  const [report, setReport] = useState(true);
  const [query, setQuery] = useState("");
  const [area, setArea] = useState("");
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const financial = useRemote<FinanceReport>(report ? "reports/financial" + query : null);
  const check = useRemote<Reconciliation>(!report ? "reports/reconciliation?" + new URLSearchParams({
    ...(area ? { area } : {}), offset: String(offset), limit: "25",
  }) : null, revision);
  return (
    <Card className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {([["financial", true], ["reconciliation", false]] as const).map(([key, selected]) =>
          <button key={key} type="button" aria-pressed={report === selected} className={report === selected ? primaryButton : secondaryButton}
            onClick={() => setReport(selected)}>{t(key)}</button>
        )}
      </div>
      {report ? <>
        <form className="flex flex-wrap items-end gap-2" onSubmit={(event) => {
          event.preventDefault();
          const data = new FormData(event.currentTarget);
          setQuery("?" + new URLSearchParams({ start: value(data, "start"), end: value(data, "end") }));
        }}>
          {financial.data && <div className="grid flex-1 basis-56 grid-cols-1 gap-2 sm:grid-cols-2">
            <Field name="start" label={t("startDate")} kind="date" required value={financial.data.start} />
            <Field name="end" label={t("endDate")} kind="date" required value={financial.data.end} />
          </div>}
          {financial.data && <button className={secondaryButton}>{t("updatePeriod")}</button>}
        </form>
        <FetchStatus loading={financial.loading} error={financial.error} />
        {!financial.data && query && <button type="button" className={secondaryButton} onClick={() => setQuery("")}>{t("resetPeriod")}</button>}
        {financial.data && <div className="grid gap-3 xl:grid-cols-2">
          {Object.entries(groups).map(([group, fields]) => <section key={group} className="space-y-2 rounded-lg border border-[var(--color-border)] p-3">
            <h2 className="text-sm font-semibold">{t("groups." + group)}</h2>
            <dl className="grid grid-cols-2 gap-3 text-sm">
              {fields.map((field) => <div key={field} className="min-w-0">
                <dt>{t("metrics." + field)}</dt>
                <dd className="break-words font-semibold tabular-nums">{group === "loyalty"
                  ? new Intl.NumberFormat(locale === "bn" ? "bn-BD-u-nu-latn" : "en-BD").format(Number(financial.data?.[field]))
                  : formatBDT(financial.data?.[field])}</dd>
              </div>)}
            </dl>
          </section>)}
        </div>}
      </> : <>
        <p className="text-sm">{t("reconciliationHint")}</p>
        <div className="flex flex-wrap items-end gap-2">
          <label className="grid flex-1 basis-44 gap-1 text-sm font-medium">{t("area")}
            <select className={fieldClass} aria-label={t("area")} value={area} onChange={(e) => { setArea(e.target.value); setOffset(0); }}>
              <option value="">{t("allAreas")}</option>
              {areas.map((name) => <option key={name} value={name}>{t("areas." + name)}</option>)}
            </select>
          </label>
          <button type="button" className={secondaryButton} onClick={() => setRevision((n) => n + 1)}>{t("runReconciliation")}</button>
        </div>
        <FetchStatus loading={check.loading} error={check.error} />
        {check.data && <>
          <p className="text-sm font-semibold" role="status">{check.data.total
            ? t("differences", { count: check.data.total }) : t("balanced")}</p>
          {check.data.items.map((row) => <article key={row.entity_id + row.check} className="space-y-2 rounded-lg border border-[var(--color-border)] p-3 text-sm">
            <p className="font-semibold">{t("areas." + row.area)} · {t.has("checks." + row.check) ? t("checks." + row.check) : row.check}</p>
            <p className="break-all font-mono text-xs">{row.entity_id}</p>
            <p>{t("comparison", { expected: formatQuantity(row.expected), actual: formatQuantity(row.actual) })}</p>
          </article>)}
          <Pager {...check.data} offset={offset} setOffset={setOffset} />
        </>}
      </>}
    </Card>
  );
}
