"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Plus, X } from "lucide-react";
import { Card } from "@/components/ui/card";
import { PurchaseCreditsPanel } from "./credits";
import { Badge } from "@/components/ui/badge";
import { fieldClass, secondaryButton } from "@/components/ui/pos-form";
import { formatBDT, formatQuantity, localizedName } from "@/lib/format";
import type { InventoryPurchase, InventorySupplier, Paginated, ProductOut, InventoryUnit } from "@/types";
import { FetchStatus, Field, Form, Pager, ProductPicker, SearchBox, useRemote, useWrite, value, quantity, WriteStatus } from "./shared";

export function Purchases({ initial, revision, refresh, canWrite, selected, setSelected }: {
  initial: ProductOut[]; revision: number; refresh: () => void; canWrite: boolean;
  selected: string | null; setSelected: (value: string | null) => void;
}) {
  const t = useTranslations("inventoryOps");
  const locale = useLocale();
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [draft, setDraft] = useState(false);
  const orders = useRemote<Paginated<InventoryPurchase>>("purchases?" + new URLSearchParams({
    q: search, limit: "12", offset: String(offset),
  }), revision);
  const detail = useRemote<InventoryPurchase>(selected ? "purchases/" + selected : null, revision);

  return (
    <div className="space-y-3">
      <Card className="space-y-3">
        <SearchBox label={t("searchPurchase")} onSearch={(query) => { setSearch(query); setOffset(0); }} />
        {canWrite && <button className={secondaryButton} type="button" onClick={() => setDraft(!draft)}>
          <Plus size={16} aria-hidden="true" />{t(draft ? "close" : "createPurchase")}
        </button>}
      </Card>
      {draft && <Draft initial={initial} refresh={refresh} created={(id) => { setDraft(false); setSelected(id); }} />}
      <FetchStatus loading={detail.loading} error={detail.error} />
      {detail.data && <PurchaseDetail key={detail.data.id} purchase={detail.data} initial={initial} canWrite={canWrite}
        refresh={refresh} close={() => setSelected(null)} />}
      <FetchStatus loading={orders.loading} error={orders.error} empty={orders.data?.items.length === 0} />
      <div className="grid gap-3 lg:grid-cols-2">
        {orders.data?.items.map((order) => <Card key={order.id} className="space-y-2">
          <div className="flex flex-wrap justify-between gap-2">
            <strong className="break-all">{order.supplier_invoice_number || order.purchase_number}</strong>
            <Badge variant={order.status === "received" ? "success" : "outline"}>{t("purchaseStatus." + order.status)}</Badge>
          </div>
          {order.supplier_name && <p className="text-sm">{localizedName(order.supplier_name, order.supplier_name_bn, locale)}</p>}
          <p className="text-sm">{t("total")} <strong>{formatBDT(order.total, locale)}</strong></p>
          <button type="button" className={secondaryButton} onClick={() => setSelected(order.id)}>{t("viewPurchase")}</button>
        </Card>)}
      </div>
      {orders.data && <Pager {...orders.data} offset={offset} setOffset={setOffset} />}
    </div>
  );
}

function Draft({ initial, refresh, created }: {
  initial: ProductOut[]; refresh: () => void; created: (id: string) => void;
}) {
  const t = useTranslations("inventoryOps");
  const locale = useLocale();
  const state = useWrite(refresh);
  const [supplierQuery, setSupplierQuery] = useState("");
  const suppliers = useRemote<Paginated<InventorySupplier>>("suppliers?" + new URLSearchParams({
    active: "true", q: supplierQuery, limit: "40",
  }));
  const [rows, setRows] = useState([0]);
  const [next, setNext] = useState(1);

  return (
    <Card className="space-y-3">
      <h2 className="text-lg font-bold">{t("createPurchase")}</h2>
      <Form busy={state.busy} submit={t("saveDraft")} onSubmit={async (data) => {
        const saved = await state.send<InventoryPurchase>("purchases", {
          supplier_id: value(data, "supplier"), supplier_invoice_number: value(data, "reference") || null,
          discount_total: quantity(data, "discount") || "0",
          items: rows.map((id) => ({
            product_id: value(data, "product" + id), product_unit_id: value(data, "unit" + id) || null,
            quantity: quantity(data, "quantity" + id), unit_cost: quantity(data, "cost" + id),
            batch_number: value(data, "batch" + id) || null, expiry_date: value(data, "expiry" + id) || null,
            manufacture_date: value(data, "manufacture" + id) || null,
          })),
        });
        if (saved) created(saved.id);
      }}>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="grid gap-1 text-sm font-medium">{t("searchSupplier")}
            <input type="search" className={fieldClass} value={supplierQuery} onChange={(event) => setSupplierQuery(event.target.value)} />
          </label>
          <label className="grid gap-1 text-sm font-medium">{t("supplier")}
            <select name="supplier" className={fieldClass} required>
              <option value="">{t("selectSupplier")}</option>
              {suppliers.data?.items.map((row) => <option key={row.id} value={row.id}>{localizedName(row.name, row.name_bn, locale)}</option>)}
            </select>
          </label>
          <Field name="reference" label={t("supplierReference")} />
          <Field name="discount" label={t("discount")} kind="decimal" value="0" />
        </div>
        <FetchStatus loading={suppliers.loading} error={suppliers.error} empty={suppliers.data?.items.length === 0} />
        {rows.map((id) => <DraftLine key={id} id={id} initial={initial}
          remove={rows.length > 1 ? () => setRows(rows.filter((row) => row !== id)) : undefined} />)}
        <button type="button" className={secondaryButton} disabled={rows.length >= 100} onClick={() => { setRows([...rows, next]); setNext(next + 1); }}>
          <Plus size={16} aria-hidden="true" />{t("addLine")}
        </button>
      </Form>
      <WriteStatus state={state} />
    </Card>
  );
}

function DraftLine({ id, initial, remove }: { id: number; initial: ProductOut[]; remove?: () => void }) {
  const t = useTranslations("inventoryOps");
  const locale = useLocale();
  const [product, setProduct] = useState<ProductOut | null>(null);
  const units = useRemote<InventoryUnit[]>(product ? "inventory/products/" + product.id + "/units" : null);
  return (
    <Card className="space-y-2 bg-[var(--color-primary-050)]">
      {remove && <button className={secondaryButton} type="button" onClick={remove}><X size={16} aria-hidden="true" />{t("remove")}</button>}
      <ProductPicker initial={initial} product={product} onPick={setProduct} />
      <input type="hidden" name={"product" + id} value={product?.id ?? ""} />
      <div className="grid gap-2 sm:grid-cols-3">
        <label className="grid gap-1 text-sm font-medium">{t("unit")}
          <select name={"unit" + id} className={fieldClass} key={product?.id}>
            <option value="">{t("baseUnit")}</option>
            {units.data?.map((unit) => <option key={unit.id} value={unit.id}>{localizedName(unit.name, unit.name_bn, locale)}</option>)}
          </select>
        </label>
        <Field name={"quantity" + id} label={t("quantity")} kind="decimal" required />
        <Field name={"cost" + id} label={t("unitCost")} kind="decimal" required />
        {product?.is_medicine && <>
          <Field name={"batch" + id} label={t("batchNumber")} required />
          <Field name={"expiry" + id} label={t("expiry")} kind="date" required />
          <Field name={"manufacture" + id} label={t("manufacture")} kind="date" />
        </>}
      </div>
      <FetchStatus loading={units.loading} error={units.error} />
    </Card>
  );
}

function PurchaseDetail({ purchase, initial, canWrite, refresh, close }: {
  purchase: InventoryPurchase; initial: ProductOut[]; canWrite: boolean; refresh: () => void; close: () => void;
}) {
  const t = useTranslations("inventoryOps");
  const locale = useLocale();
  const [action, setAction] = useState("");
  const state = useWrite(refresh);
  const open = ["draft", "partially_received"].includes(purchase.status);
  const posted = ["received", "partially_received"].includes(purchase.status);
  const remaining = (item: InventoryPurchase["items"][number]) => {
    const base = Number(item.ordered_base);
    const orderQuantity = Number(item.quantity);
    return base > 0 ? Math.max(0, (base - Number(item.received_base)) / base * orderQuantity) : 0;
  };
  const itemName = (item: InventoryPurchase["items"][number]) => {
    const row = initial.find((p) => p.id === item.product_id);
    return localizedName(item.product_name ?? row?.name_en, item.product_name_bn ?? row?.name_bn, locale) || item.product_id;
  };
  const actions = [
    ...(open ? ["receive"] : []), ...(posted && Number(purchase.outstanding) > 0 ? ["payments"] : []),
    ...(purchase.status === "draft" ? ["cancel"] : []), ...(posted && Number(purchase.paid_total) === 0 ? ["reverse"] : []),
  ];

  return (
    <Card className="space-y-4">
      <div className="flex flex-wrap justify-between gap-2">
        <div className="min-w-0">
          <h2 className="break-all text-lg font-bold">{purchase.supplier_invoice_number || purchase.purchase_number}</h2>
          {purchase.supplier_name && <p className="text-sm">{localizedName(purchase.supplier_name, purchase.supplier_name_bn, locale)}</p>}
          <Badge variant={purchase.status === "received" ? "success" : "outline"}>{t("purchaseStatus." + purchase.status)}</Badge>
        </div>
        <button type="button" className={secondaryButton} onClick={close}>{t("close")}</button>
      </div>
      <dl className="grid grid-cols-2 gap-2 rounded-lg bg-[var(--color-primary-050)] p-3 text-sm sm:grid-cols-4">
        {([["total", purchase.total], ["received", purchase.received_total], ["paid", purchase.paid_total], ["outstanding", purchase.outstanding]] as const).map(([label, amount]) =>
          <div key={label}><dt>{t(label)}</dt><dd className="font-bold tabular-nums">{formatBDT(amount, locale)}</dd></div>
        )}
      </dl>
      <ul className="divide-y divide-[var(--color-border)]">
        {purchase.items.map((item) => <li key={item.id} className="space-y-1 py-2 text-sm">
          <p className="break-all font-medium">{itemName(item)}{item.batch_number ? " · " + item.batch_number : ""}</p>
          <p>{t("quantity")} {formatQuantity(item.quantity, locale)} {localizedName(item.unit_name, item.unit_name_bn, locale)} · {t("unitCost")} {formatBDT(item.unit_cost, locale)} · {t("remaining")} {formatQuantity(remaining(item), locale)}</p>
        </li>)}
      </ul>
      {canWrite && <div className="flex flex-wrap gap-2">
        {actions.map((key) => <button key={key} type="button" className={secondaryButton}
          aria-pressed={action === key} onClick={() => setAction(action === key ? "" : key)}>{t("action." + key)}</button>)}
      </div>}
      {canWrite && actions.includes(action) && <Form busy={state.busy} submit={t("confirm")} onSubmit={async (data) => {
        let request;
        if (action === "receive") {
          request = { items: purchase.items.map((item) => ({
            purchase_item_id: item.id, quantity: quantity(data, item.id),
          })).filter((line) => line.quantity && Number(line.quantity) !== 0) };
        } else if (action === "payments") {
          request = { amount: quantity(data, "amount"), method: value(data, "method"), reference: value(data, "reference") || null };
        } else {
          request = { reason: value(data, "reason") };
        }
        if (await state.send("purchases/" + purchase.id + "/" + action, request)) setAction("");
      }}>
        {action === "receive" && purchase.items.filter((item) => remaining(item) > 0).map((item) =>
          <Field key={item.id} name={item.id} label={t("receivingQuantity") + " · " + itemName(item)}
            value={remaining(item).toFixed(3).replace(/0+$/, "").replace(/\.$/, "")} kind="decimal" />
        )}
        {action === "payments" && <div className="grid gap-2 sm:grid-cols-3">
          <Field name="amount" label={t("amount")} value={purchase.outstanding} kind="decimal" required />
          <label className="grid gap-1 text-sm font-medium">{t("paymentMethod")}
            <select name="method" className={fieldClass}>{["cash", "bkash", "nagad", "bank"].map((method) =>
              <option key={method} value={method}>{t("method." + method)}</option>
            )}</select>
          </label>
          <Field name="reference" label={t("paymentReference")} />
        </div>}
        {(action === "cancel" || action === "reverse") && <Field name="reason" label={t("reason")} required />}
      </Form>}
      {posted && <PurchaseCreditsPanel purchase={purchase} canWrite={canWrite} refreshPurchase={refresh} />}
      <WriteStatus state={state} />
    </Card>
  );
}
