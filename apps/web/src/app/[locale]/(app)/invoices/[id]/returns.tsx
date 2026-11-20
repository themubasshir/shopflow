"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { RotateCcw } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { fieldClass, secondaryButton } from "@/components/ui/pos-form";
import { formatBDT, formatDate, formatQuantity, localizedName } from "@/lib/format";
import type { InvoiceReturns, ReturnHistory, ReturnChoice } from "@/types";
import { FetchStatus, Field, Form, useRemote, useWrite, value, quantity, WriteStatus } from "../../inventory/operations/shared";

const choiceKey = (row: ReturnChoice) => row.invoice_item_id + (row.batch_id ?? "");

export function ReturnPanel({ invoiceId, canWrite }: { invoiceId: string; canWrite: boolean }) {
  const t = useTranslations("returns");
  const locale = useLocale();
  const [open, setOpen] = useState(false);
  const [revision, setRevision] = useState(0);
  const refresh = () => setRevision((n) => n + 1);
  const path = "invoices/" + invoiceId;
  const info = useRemote<InvoiceReturns>(open ? path + "/returns" : null, revision);
  const returnData = info.data;
  const choices = returnData?.rows.filter((row) => Number(row.remaining) > 0) ?? [];

  return (
    <Card className="space-y-3" aria-label={t("title")}>
      <button type="button" className={secondaryButton} aria-expanded={open} onClick={() => setOpen(!open)}>
        <RotateCcw size={16} aria-hidden="true" />{t("title")}
      </button>
      {open && <>
        <FetchStatus loading={info.loading} error={info.error} />
        {returnData && <div className="space-y-4">
          <p className="text-sm">{t("outstanding")} <strong>{formatBDT(returnData.outstanding_due, locale)}</strong></p>
          {canWrite && choices.length > 0 && <RequestForm path={path} choices={choices} refresh={refresh} />}
          {!choices.length && <p className="text-sm">{t("noneRemaining")}</p>}
          <section className="space-y-3">
            <h2 className="text-lg font-bold">{t("history")}</h2>
            {!returnData.history.length && <p className="text-sm">{t("noHistory")}</p>}
            {returnData.history.map((row) => (
              <HistoryCard key={row.id} row={row} choices={returnData.rows} path={path} canWrite={canWrite} refresh={refresh} />
            ))}
          </section>
        </div>}
      </>}
    </Card>
  );
}

function RequestForm({ path, choices, refresh }: { path: string; choices: ReturnChoice[]; refresh: () => void }) {
  const t = useTranslations("returns");
  const state = useWrite(refresh);
  const [sequence, setSequence] = useState(0);
  const [warning, setWarning] = useState(false);
  const [method, setMethod] = useState("");
  return (
    <Form key={sequence} busy={state.busy} submit={t("submit")} onSubmit={async (data) => {
      const lines = choices.flatMap((row) => {
        const key = choiceKey(row);
        const qty = quantity(data, key);
        return qty && Number(qty) !== 0 ? [{
          invoice_item_id: row.invoice_item_id, batch_id: row.batch_id ?? null, quantity: qty,
          disposition: value(data, key + "status"), verified: data.has(key + "verified"),
        }] : [];
      });
      setWarning(!lines.length);
      if (!lines.length) return;
      const posted = await state.send<ReturnHistory>(path + "/returns", {
        lines, reason: value(data, "reason"), refund_method: method || null,
        cash_reference: value(data, "cashReference") || null,
      });
      if (posted) {
        setSequence((n) => n + 1);
        setMethod("");
      }
    }}>
      <p className="text-sm">{t("dueFirst")}</p>
      <div className="grid gap-3 xl:grid-cols-2">
        {choices.map((row) => <Choice key={choiceKey(row)} row={row} />)}
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <Field name="reason" label={t("reason")} required />
        <label className="grid gap-1 text-sm font-medium">
          {t("refundMethod")}
          <select name="method" aria-label={t("refundMethod")} className={fieldClass} value={method} onChange={(event) => setMethod(event.target.value)}>
            <option value="">{t("dueOnly")}</option>
            {["cash", "bkash", "nagad"].map((item) => <option key={item} value={item}>{t("methods." + item)}</option>)}
          </select>
        </label>
      </div>
      {method === "cash" && <Field name="cashReference" label={t("cashReference")} />}
      {(method === "bkash" || method === "nagad") && <p className="text-sm">{t("externalNotice")}</p>}
      {warning && <p role="alert" className="text-sm text-red-700">{t("selectQuantity")}</p>}
      <WriteStatus state={state} />
    </Form>
  );
}

function Choice({ row }: { row: ReturnChoice }) {
  const t = useTranslations("returns");
  const locale = useLocale();
  const [disposition, setDisposition] = useState(row.medicine ? "quarantine" : "damaged");
  const key = choiceKey(row);
  const name = localizedName(row.description, row.name_bn, locale);
  const label = row.batch_number ? name + " · " + row.batch_number : name;
  return (
    <div className="min-w-0 space-y-2 rounded-lg border border-[var(--color-border)] p-3">
      <h3 className="break-words text-sm font-semibold">{label}</h3>
      <p className="text-sm">{t("remaining", { qty: formatQuantity(row.remaining, locale), unit: t.has("units." + row.base_unit) ? t("units." + row.base_unit) : row.base_unit })}</p>
      {row.expiry_date && <p className="text-sm">{t("expiry")} {row.expiry_date}</p>}
      {row.medicine && !row.can_restore && <p className="text-sm text-red-700">{t("restorationBlocked")}</p>}
      <Field name={key} label={t("quantityFor", { name: label })} kind="decimal" />
      <label className="grid gap-1 text-sm font-medium">{t("disposition")}
        <select className={fieldClass} aria-label={t("disposition")} name={key + "status"} value={disposition}
          onChange={(event) => setDisposition(event.target.value)}>
          {["quarantine", "damaged", "disposal", ...(row.stock_traced ? ["supplier_staging"] : []), ...(row.can_restore ? ["sellable"] : [])].map((option) => (
            <option value={option} key={option}>{t("dispositions." + option)}</option>
          ))}
        </select>
      </label>
      {disposition === "sellable" && <label className="flex min-h-11 items-center gap-2 text-sm">
        <input name={key + "verified"} type="checkbox" className="h-5 w-5" />{t("verified")}
      </label>}
    </div>
  );
}

function HistoryCard({ row, choices, path, canWrite, refresh }: {
  row: ReturnHistory; choices: ReturnChoice[]; path: string; canWrite: boolean; refresh: () => void;
}) {
  const t = useTranslations("returns");
  const locale = useLocale();
  const state = useWrite(refresh);
  return (
    <article className="space-y-3 rounded-lg border border-[var(--color-border)] p-3">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="font-semibold">{formatBDT(row.amount, locale)} · {formatDate(row.created_at, locale)}</p>
          <p className="break-words text-sm">{row.reason}</p>
        </div>
        <Badge variant={row.refund_status === "completed" ? "success" : "outline"}>{t("status." + row.refund_status)}</Badge>
      </header>
      <dl className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
        {([
          ["dueReduction", formatBDT(row.due_reduction, locale)], ["refundAmount", formatBDT(row.refund_amount, locale)],
          ["pointsReversed", row.earned_reversed], ["pointsRestored", row.redeemed_restored],
        ] as const).map(([name, amount]) => <div key={name}><dt>{t(name)}</dt><dd className="font-semibold">{amount}</dd></div>)}
      </dl>
      {row.refund_method && <p className="break-words text-sm">{t("methods." + row.refund_method)}{row.refund_reference ? " · " + row.refund_reference : ""}</p>}
      {canWrite && row.refund_status === "pending" && <Form busy={state.busy} submit={t("complete")} onSubmit={(data) =>
        state.send(path + "/returns/" + row.id + "/refund", { reference: value(data, "reference") })}>
        <p className="text-sm">{t("confirmTransfer")}</p>
        <Field name="reference" label={t("transferReference")} required />
      </Form>}
      {(row.lines ?? []).map((line) => {
        const original = choices.find((item) => item.invoice_item_id === line.invoice_item_id && item.batch_id === line.batch_id);
        return <div className="space-y-2 border-t border-[var(--color-border)] pt-2 text-sm" key={line.id}>
          <p className="break-words font-medium">
            {formatQuantity(line.quantity, locale)} · {original ? localizedName(original.description, original.name_bn, locale) : ""}
            {original?.batch_number ? " · " + original.batch_number : ""}
          </p>
          <p>{t("dispositions." + line.disposition)}{line.stock_traced ? "" : " · " + t("noProvenance")}</p>
          {canWrite && line.held && <Form busy={state.busy} submit={t("resolveStock")} onSubmit={(data) =>
            state.send(path + "/return-lines/" + line.id + "/disposition", { action: value(data, "action"), reason: value(data, "reason") })}>
            <div className="grid gap-2 sm:grid-cols-2">
              <label className="grid gap-1 text-sm font-medium">{t("disposition")}
                <select className={fieldClass} name="action" aria-label={t("disposition")}>
                  <option value="dispose">{t("dispositions.disposal")}</option>
                  <option value="supplier_return">{t("sendToSupplier")}</option>
                </select>
              </label>
              <Field name="reason" label={t("reason")} required />
            </div>
          </Form>}
        </div>;
      })}
      <WriteStatus state={state} />
    </article>
  );
}
