"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Card } from "@/components/ui/card";
import { fieldClass, secondaryButton } from "@/components/ui/pos-form";
import { formatBDT, formatQuantity, localizedName } from "@/lib/format";
import type { InventoryPurchase, Paginated, PurchaseCredits, SupplierCreditNote } from "@/types";
import { FetchStatus, Field, Form, useRemote, useWrite, value, quantity, WriteStatus } from "./shared";

export function PurchaseCreditsPanel({ purchase, canWrite, refreshPurchase }: {
  purchase: InventoryPurchase; canWrite: boolean; refreshPurchase: () => void;
}) {
  const t = useTranslations("returns");
  const locale = useLocale();
  const [open, setOpen] = useState(false);
  const [revision, setRevision] = useState(0);
  const [action, setAction] = useState("");
  const refresh = () => { setRevision((n) => n + 1); refreshPurchase(); };
  const state = useWrite(refresh);
  const path = "purchases/" + purchase.id;
  const view = useRemote<PurchaseCredits>(open ? path + "/credits" : null, revision);
  const available = view.data?.shipments.filter((row) => !row.credit_note_id && Number(row.cost) > 0) ?? [];
  return (
    <section className="space-y-3">
      <button type="button" className={secondaryButton} aria-expanded={open} onClick={() => setOpen(!open)}>{t("supplierTitle")}</button>
      {open && <>
        <FetchStatus loading={view.loading} error={view.error} />
        {view.data && <>
          <p className="text-sm">{t("supplierPayable")} <strong>{formatBDT(view.data.payable, locale)}</strong></p>
          {canWrite && <div className="flex flex-wrap gap-2">
            {view.data.lots.length > 0 && <button type="button" className={secondaryButton} aria-pressed={action === "ship"}
              onClick={() => setAction(action === "ship" ? "" : "ship")}>{t("sendToSupplier")}</button>}
            {available.length > 0 && <button type="button" className={secondaryButton} aria-pressed={action === "credit"}
              onClick={() => setAction(action === "credit" ? "" : "credit")}>{t("createCredit")}</button>}
          </div>}
          {canWrite && action === "ship" && view.data.lots.length > 0 && <Form busy={state.busy} submit={t("recordShipment")} onSubmit={async (data) => {
            const lines = view.data?.lots.flatMap((lot) => {
              const qty = quantity(data, lot.lot_id);
              return qty && Number(qty) !== 0 ? [{ lot_id: lot.lot_id, quantity: qty }] : [];
            }) ?? [];
            if (await state.send(path + "/supplier-returns", { lines, reason: value(data, "reason") })) setAction("");
          }}>
            <div className="grid gap-2 sm:grid-cols-2">
              {view.data.lots.map((lot) => <Field key={lot.lot_id} name={lot.lot_id} kind="decimal" label={t("lotQty", {
                name: [localizedName(lot.product, lot.name_bn, locale), lot.batch_number, lot.lot_id.slice(0, 8)].filter(Boolean).join(" · "), qty: formatQuantity(lot.movable, locale),
              })} />)}
            </div>
            <Field name="reason" label={t("reason")} required />
          </Form>}
          {canWrite && action === "credit" && available.length > 0 && <Form busy={state.busy} submit={t("saveCredit")} onSubmit={async (data) => {
            if (await state.send(path + "/credits", {
              shipment_id: value(data, "shipment"), reference: value(data, "ref"), reason: value(data, "reason"), amount: quantity(data, "amount"),
            })) setAction("");
          }}>
            <label className="grid gap-1 text-sm font-medium">{t("shipment")}
              <select name="shipment" aria-label={t("shipment")} className={fieldClass} required>
                {available.map((row) => <option key={row.id} value={row.id}>{row.id.slice(0, 8)} · {formatQuantity(row.quantity, locale)} · {formatBDT(row.cost, locale)}</option>)}
              </select>
            </label>
            <div className="grid gap-2 sm:grid-cols-3">
              <Field name="ref" label={t("creditReference")} required />
              <Field name="amount" label={t("amount")} kind="decimal" required />
              <Field name="reason" label={t("reason")} required />
            </div>
          </Form>}
          <WriteStatus state={state} />
          {view.data.notes.map((note) => <Note key={note.id} note={note} purchase={purchase} canWrite={canWrite} refresh={refresh} />)}
          {!view.data.notes.length && <p className="text-sm">{t("noCredits")}</p>}
        </>}
      </>}
    </section>
  );
}

function Note({ note, purchase, canWrite, refresh }: {
  note: SupplierCreditNote; purchase: InventoryPurchase; canWrite: boolean; refresh: () => void;
}) {
  const t = useTranslations("returns");
  const locale = useLocale();
  const [action, setAction] = useState("");
  const [query, setQuery] = useState("");
  const state = useWrite(refresh);
  const path = "suppliers/" + note.supplier_id + "/credits/" + note.id;
  const orders = useRemote<Paginated<InventoryPurchase>>(action === "apply" ? "purchases?" + new URLSearchParams({
    supplier_id: note.supplier_id, limit: "50", q: query,
  }) : null);
  const posted = orders.data?.items.filter((row) => Number(row.outstanding) > 0 && row.id !== purchase.id) ?? [];
  if (Number(purchase.outstanding) > 0) posted.unshift(purchase);
  return (
    <Card className="space-y-3">
      <h3 className="break-words font-semibold">{t("creditNote")} · {note.reference}</h3>
      <p className="break-words text-sm">{note.reason}</p>
      <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
        {([["amount", note.amount], ["applied", note.applied], ["receivedRefund", note.refunded], ["availableCredit", note.available]] as const)
          .map(([label, amount]) => <div key={label}><dt>{t(label)}</dt><dd className="font-semibold">{formatBDT(amount, locale)}</dd></div>)}
      </dl>
      {canWrite && Number(note.available) > 0 && <>
        <div className="flex flex-wrap gap-2">
          {["apply", "refund"].map((key) => <button type="button" key={key} className={secondaryButton} aria-pressed={action === key}
            onClick={() => setAction(action === key ? "" : key)}>{t(key === "apply" ? "applyCredit" : "recordSupplierRefund")}</button>)}
        </div>
        {action === "apply" && <Form busy={state.busy} submit={t("applyCredit")} onSubmit={async (data) => {
          if (await state.send(path + "/applications", { purchase_id: value(data, "purchase"), amount: quantity(data, "amount") })) setAction("");
        }}>
          <label className="grid gap-1 text-sm font-medium">{t("findPurchase")}
            <input type="search" className={fieldClass} value={query} onChange={(e) => setQuery(e.target.value)} />
          </label>
          <FetchStatus loading={orders.loading} error={orders.error} />
          <label className="grid gap-1 text-sm font-medium">{t("purchase")}
            <select name="purchase" aria-label={t("purchase")} className={fieldClass} required>
              <option value="">{t("selectPurchase")}</option>
              {posted.map((row) => <option key={row.id} value={row.id}>{row.supplier_invoice_number || row.purchase_number} · {formatBDT(row.outstanding, locale)}</option>)}
            </select>
          </label>
          <Field name="amount" label={t("amount")} kind="decimal" required />
        </Form>}
        {action === "refund" && <Form busy={state.busy} submit={t("recordSupplierRefund")} onSubmit={async (data) => {
          if (await state.send(path + "/refunds", { method: value(data, "method"), amount: quantity(data, "amount"), reference: value(data, "reference") })) setAction("");
        }}>
          <p className="text-sm">{t("confirmSupplierMoney")}</p>
          <div className="grid gap-2 sm:grid-cols-3">
            <label className="grid gap-1 text-sm font-medium">{t("refundMethod")}
              <select name="method" aria-label={t("refundMethod")} className={fieldClass} required>
                {["cash", "bkash", "nagad", "bank"].map((method) => <option key={method} value={method}>{t("methods." + method)}</option>)}
              </select>
            </label>
            <Field name="amount" label={t("amount")} kind="decimal" required />
            <Field name="reference" label={t("transferReference")} required />
          </div>
        </Form>}
      </>}
      {(note.entries ?? []).filter((entry) => ["credit_application", "refund"].includes(entry.kind)).map((entry) =>
        <p key={entry.id} className="break-words text-sm">{t(entry.kind === "refund" ? "receivedRefund" : "applied")} {formatBDT(Math.abs(Number(entry.amount)), locale)}
          {entry.reference ? " · " + entry.reference : ""}</p>
      )}
      <WriteStatus state={state} />
    </Card>
  );
}
