"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fieldClass, secondaryButton } from "@/components/ui/pos-form";
import { formatBDT, formatDate, formatQuantity, localizedName } from "@/lib/format";
import type { InventoryBatch, InventoryMovement, InventorySupplier, InventoryValue, Paginated, ProductOut } from "@/types";
import { FetchStatus, Field, Form, Pager, ProductPicker, SearchBox, useRemote, useWrite, value, quantity, WriteStatus } from "./shared";

type Props = { initial: ProductOut[]; revision: number; refresh: () => void; canWrite: boolean };

export function Batches({ revision, refresh, canWrite }: Props) {
  const t = useTranslations("inventoryOps");
  const locale = useLocale();
  const [search, setSearch] = useState("");
  const [window, setWindow] = useState("all");
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<InventoryBatch | null>(null);
  const rows = useRemote<Paginated<InventoryBatch>>("inventory/batches?" + new URLSearchParams({
    q: search, window, limit: "12", offset: String(offset),
  }), revision);
  const live = rows.data?.items.find((row) => row.id === selected?.id) ?? selected;
  const supplier = useRemote<InventorySupplier>(live?.supplier_id ? "suppliers/" + live.supplier_id : null, revision);

  return (
    <div className="space-y-3">
      <Card className="space-y-3">
        <SearchBox label={t("searchBatch")} onSearch={(q) => { setSearch(q); setOffset(0); }} />
        <label className="grid gap-1 text-sm font-medium sm:max-w-xs">{t("expiryWindow")}
          <select className={fieldClass} value={window} onChange={(event) => { setWindow(event.target.value); setOffset(0); }}>
            {["all", "30", "60", "90", "expired", "quarantined"].map((option) =>
              <option key={option} value={option}>{t("window." + option)}</option>
            )}
          </select>
        </label>
      </Card>
      {live && <Card className="space-y-3">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <h2 className="text-lg font-bold">{live.batch_number} · {localizedName(live.product_name, live.product_name_bn, locale)}</h2>
          <button type="button" className={secondaryButton} onClick={() => setSelected(null)}>{t("close")}</button>
        </div>
        <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
          <div><dt>{t("supplier")}</dt><dd className="font-semibold">{supplier.data ? localizedName(supplier.data.name, supplier.data.name_bn, locale) : "—"}</dd></div>
          <div><dt>{t("receivedDate")}</dt><dd className="font-semibold">{formatDate(live.received_at, locale)}</dd></div>
          <div><dt>{t("manufacture")}</dt><dd className="font-semibold">{live.manufacture_date ?? "—"}</dd></div>
          <div><dt>{t("expiry")}</dt><dd className="font-semibold">{live.expiry_date}</dd></div>
          <div><dt>{t("receivedQuantity")}</dt><dd className="font-semibold">{formatQuantity(live.quantity_received, locale)}</dd></div>
          <div><dt>{t("physical")}</dt><dd className="font-semibold">{formatQuantity(live.quantity_on_hand, locale)}</dd></div>
          <div><dt>{t("heldReturns")}</dt><dd className="font-semibold">{formatQuantity(live.held_quantity, locale)}</dd></div>
          <div><dt>{t("unitCost")}</dt><dd className="font-semibold">{live.purchase_cost === null ? "—" : formatBDT(live.purchase_cost, locale)}</dd></div>
          <div><dt>{t("sellingReference")}</dt><dd className="font-semibold">{live.price_reference === null ? "—" : formatBDT(live.price_reference, locale)}</dd></div>
        </dl>
        {canWrite && <BatchCommands batch={live} revision={revision} refresh={refresh} />}
      </Card>}
      <FetchStatus loading={rows.loading} error={rows.error} empty={rows.data?.items.length === 0} />
      <div className="grid gap-3 lg:grid-cols-2">
        {rows.data?.items.map((batch) => <Card key={batch.id} className="space-y-2">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <strong className="break-all">{batch.batch_number}</strong>
            <Badge variant={batch.status === "available" ? "success" : batch.status === "depleted" ? "outline" : "warning"}>{t("batchStatus." + batch.status)}</Badge>
          </div>
          <p className="text-sm">{localizedName(batch.product_name, batch.product_name_bn, locale)}</p>
          <p className="text-sm">{t("expiry")} {batch.expiry_date} · {t("physical")} <strong>{formatQuantity(batch.quantity_on_hand, locale)}</strong></p>
          <button type="button" className={secondaryButton} onClick={() => setSelected(batch)}>{t("viewBatch")}</button>
        </Card>)}
      </div>
      {rows.data && <Pager {...rows.data} offset={offset} setOffset={setOffset} />}
    </div>
  );
}

function BatchCommands({ batch, refresh, revision }: {
  batch: InventoryBatch; refresh: () => void; revision: number;
}) {
  const t = useTranslations("inventoryOps");
  const [command, setCommand] = useState("");
  const state = useWrite(refresh);
  const quarantine = batch.status === "quarantined";
  return (
    <div className="space-y-3 border-t border-[var(--color-border)] pt-3" data-revision={revision}>
      <div className="flex flex-wrap gap-2">
        {(!quarantine || batch.days_to_expiry > 0) && <button type="button" className={secondaryButton}
          onClick={() => setCommand(command === "state" ? "" : "state")}>{t(quarantine ? "release" : "quarantine")}</button>}
        {Number(batch.quantity_on_hand) > 0 &&
          <button type="button" className={secondaryButton} onClick={() => setCommand(command === "adjust" ? "" : "adjust")}>{t("adjustBatch")}</button>}
      </div>
      {command === "state" && <Form busy={state.busy} submit={t("confirm")} onSubmit={async (data) => {
        if (await state.send("inventory/batches/" + batch.id + "/state", { quarantined: !quarantine, reason: value(data, "reason") }, "PUT")) setCommand("");
      }}>
        <Field name="reason" label={t("reason")} required />
      </Form>}
      {command === "adjust" && <Adjustment key={batch.id} productId={batch.product_id} batch={batch} refresh={refresh} />}
      <WriteStatus state={state} />
    </div>
  );
}

export function Movements({ initial, revision, refresh, canWrite, product, setProduct }: Props & {
  product: ProductOut | null; setProduct: (p: ProductOut | null) => void;
}) {
  const t = useTranslations("inventoryOps");
  const locale = useLocale();
  const [offset, setOffset] = useState(0);
  const [editing, setEditing] = useState("");
  const rows = useRemote<Paginated<InventoryMovement>>("inventory/movements?" + new URLSearchParams({
    ...(product ? { product_id: product.id } : {}), limit: "18", offset: String(offset),
  }), revision);
  const totals = useRemote<InventoryValue>(product ? "inventory/products/" + product.id + "/valuation" : null, revision);
  const productName = (id: string) => {
    const known = product?.id === id ? product : initial.find((p) => p.id === id);
    return known ? localizedName(known.name_en, known.name_bn, locale) : id;
  };
  return (
    <div className="space-y-3">
      <Card className="space-y-3">
        <ProductPicker initial={initial} product={product} onPick={(next) => { setProduct(next); setOffset(0); setEditing(""); }} />
        <FetchStatus loading={totals.loading} error={totals.error} />
        {totals.data && <dl className="grid grid-cols-2 gap-2 rounded-lg bg-[var(--color-primary-050)] p-3 text-sm sm:grid-cols-3">
          {([["physical", totals.data.quantity_on_hand], ["heldReturns", totals.data.held_quantity], ["saleable", totals.data.available], ["ledgerStock", totals.data.ledger_quantity],
            ["valuation", formatBDT(totals.data.value, locale)], ["unvalued", totals.data.unvalued_quantity], ["threshold", totals.data.low_stock_threshold]] as const).map(([label, value]) =>
            <div key={label}><dt>{t(label)}</dt><dd className="font-semibold">{label === "valuation" ? value : formatQuantity(value, locale)}</dd></div>
          )}
        </dl>}
        {canWrite && product && <div className="flex flex-wrap gap-2">
          {!product.is_medicine && <button type="button" className={secondaryButton} onClick={() => setEditing(editing === "adjust" ? "" : "adjust")}>{t("adjust")}</button>}
          <button type="button" className={secondaryButton} onClick={() => setEditing(editing === "threshold" ? "" : "threshold")}>{t("changeThreshold")}</button>
        </div>}
        {canWrite && product && editing === "adjust" && <Adjustment key={product.id} productId={product.id} refresh={refresh} />}
        {canWrite && product && editing === "threshold" && <Threshold key={product.id} product={product} amount={totals.data?.low_stock_threshold} refresh={refresh} />}
      </Card>
      <FetchStatus loading={rows.loading} error={rows.error} empty={rows.data?.items.length === 0} />
      <div className="grid gap-3 lg:grid-cols-2">
        {rows.data?.items.map((move) => <Card key={move.id} className="space-y-1 text-sm">
          <div className="flex flex-wrap justify-between gap-2">
            <strong className="min-w-0 break-all">{productName(move.product_id)}</strong>
            <Badge variant={Number(move.quantity) > 0 ? "success" : "outline"}>{Number(move.quantity) > 0 ? "+" : ""}{formatQuantity(move.quantity, locale)}</Badge>
          </div>
          <p>{t("move." + move.movement_type)} · {formatDate(move.created_at, locale)}</p>
          {move.note && <p className="break-words text-[var(--color-muted-foreground)]">{move.note}</p>}
        </Card>)}
      </div>
      {rows.data && <Pager {...rows.data} offset={offset} setOffset={setOffset} />}
    </div>
  );
}

function Threshold({ product, amount, refresh }: { product: ProductOut; amount?: string; refresh: () => void }) {
  const t = useTranslations("inventoryOps");
  const state = useWrite(refresh);
  return <>
    <Form busy={state.busy} submit={t("confirm")} onSubmit={(data) => void state.send("inventory/products/" + product.id + "/threshold", {
      quantity: quantity(data, "quantity"),
    }, "PUT")}>
      <Field name="quantity" label={t("threshold")} kind="decimal" value={amount ?? product.low_stock_threshold} required />
    </Form>
    <WriteStatus state={state} />
  </>;
}

function Adjustment({ productId, batch, refresh }: {
  productId: string; batch?: InventoryBatch; refresh: () => void;
}) {
  const t = useTranslations("inventoryOps");
  const state = useWrite(refresh);
  const [action, setAction] = useState(batch ? "remove" : "add");
  const canDispose = batch && (batch.days_to_expiry <= 0 || batch.status === "quarantined");
  const actions = batch ? ["remove", "damage", ...(canDispose ? ["dispose", ...(batch.supplier_id ? ["supplier_return"] : [])] : [])] : ["add", "remove", "damage"];
  return <>
    <Form busy={state.busy} submit={t("confirm")} onSubmit={(data) => void state.send("inventory/adjustments", {
      product_id: productId, batch_id: batch?.id ?? null,
      action, quantity: quantity(data, "quantity"), unit_cost: quantity(data, "cost") || null,
      reason: value(data, "reason"),
    })}>
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="grid gap-1 text-sm font-medium">{t("adjustmentType")}
          <select className={fieldClass} value={action} onChange={(event) => setAction(event.target.value)}>
            {actions.map((option) => <option key={option} value={option}>{t("adjustment." + option)}</option>)}
          </select>
        </label>
        <Field name="quantity" label={t("baseQuantity")} kind="decimal" required />
        {action === "add" && <Field name="cost" label={t("unitCost")} kind="decimal" />}
        <Field name="reason" label={t("reason")} required />
      </div>
    </Form>
    <WriteStatus state={state} />
  </>;
}

export function LowStock({ revision, select }: { revision: number; select: (p: ProductOut) => void }) {
  const locale = useLocale();
  const t = useTranslations("inventoryOps");
  const [offset, setOffset] = useState(0);
  const products = useRemote<Paginated<ProductOut>>("catalog/products?low_stock_only=true&limit=18&offset=" + offset, revision);
  return (
    <div className="space-y-3">
      <FetchStatus loading={products.loading} error={products.error} empty={products.data?.items.length === 0} />
      <div className="grid gap-3 lg:grid-cols-2">
        {products.data?.items.map((row) => <Card key={row.id} className="space-y-2">
          <strong>{localizedName(row.name_en, row.name_bn, locale)}</strong>
          <p className="text-sm">{row.sku} · {t("saleable")} {formatQuantity(row.stock_on_hand, locale)} · {t("threshold")} {formatQuantity(row.low_stock_threshold, locale)}</p>
          <button className={secondaryButton} type="button" onClick={() => select(row)}>{t("movements")}</button>
        </Card>)}
      </div>
      {products.data && <Pager {...products.data} offset={offset} setOffset={setOffset} />}
    </div>
  );
}
