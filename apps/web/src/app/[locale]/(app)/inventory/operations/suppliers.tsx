"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Plus, Pencil, X } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatBDT, formatDate, localizedName } from "@/lib/format";
import { secondaryButton } from "@/components/ui/pos-form";
import type { InventoryPurchase, InventorySupplier, Paginated, ProductOut, SupplierEntry } from "@/types";
import { FetchStatus, Field, Form, Pager, ProductPicker, SearchBox, useRemote, useWrite, value, WriteStatus } from "./shared";

export function Suppliers({ initial, revision, refresh, canWrite, openPurchase }: {
  initial: ProductOut[]; revision: number; refresh: () => void; canWrite: boolean;
  openPurchase: (id: string) => void;
}) {
  const t = useTranslations("inventoryOps");
  const locale = useLocale();
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [editor, setEditor] = useState<"new" | InventorySupplier | null>(null);
  const suppliers = useRemote<Paginated<InventorySupplier>>("suppliers?" + new URLSearchParams({
    q: query, limit: "12", offset: String(offset),
  }), revision);
  const detail = useRemote<InventorySupplier>(selected ? "suppliers/" + selected : null, revision);
  const orders = useRemote<Paginated<InventoryPurchase>>(selected ? "purchases?supplier_id=" + selected : null, revision);
  const [ledgerOffset, setLedgerOffset] = useState(0);
  const ledger = useRemote<Paginated<SupplierEntry>>(selected ? "suppliers/" + selected + "/ledger?offset=" + ledgerOffset : null, revision);

  return (
    <div className="space-y-3">
      <Card className="space-y-3">
        <SearchBox label={t("searchSupplier")} onSearch={(q) => { setOffset(0); setQuery(q); }} />
        {canWrite && <button className={secondaryButton} type="button" onClick={() => setEditor("new")}>
          <Plus size={16} aria-hidden="true" />{t("addSupplier")}
        </button>}
      </Card>
      {editor && <SupplierForm key={editor === "new" ? "new" : editor.id} supplier={editor === "new" ? undefined : editor}
        initial={initial} refresh={refresh} close={() => setEditor(null)} select={setSelected} />}
      <FetchStatus loading={suppliers.loading} error={suppliers.error} empty={suppliers.data?.items.length === 0} />
      <div className="grid gap-3 lg:grid-cols-2">
        {suppliers.data?.items.map((supplier) => (
          <Card key={supplier.id} className="grid gap-2">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <strong className="min-w-0 break-words">{localizedName(supplier.name, supplier.name_bn, locale)}</strong>
              <Badge variant={supplier.is_active ? "success" : "outline"}>{t(supplier.is_active ? "active" : "inactive")}</Badge>
            </div>
            {supplier.phone && <p className="text-sm">{supplier.phone}</p>}
            <p className="text-sm">{t("outstanding")} <strong className="tabular-nums">{formatBDT(supplier.balance)}</strong></p>
            <button type="button" className={secondaryButton + " justify-self-start"}
              aria-pressed={selected === supplier.id} onClick={() => { setSelected(supplier.id); setLedgerOffset(0); }}>{t("supplierHistory")}</button>
          </Card>
        ))}
      </div>
      {suppliers.data && <Pager {...suppliers.data} offset={offset} setOffset={setOffset} />}
      {selected && <Card className="space-y-4">
        <FetchStatus loading={detail.loading} error={detail.error} />
        {detail.data && <>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-lg font-bold">{localizedName(detail.data.name, detail.data.name_bn, locale)}</h2>
            {canWrite && <button className={secondaryButton} type="button" onClick={() => setEditor(detail.data ?? null)}>
              <Pencil size={16} aria-hidden="true" />{t("editSupplier")}
            </button>}
          </div>
          {detail.data.address && <p className="text-sm">{detail.data.address}</p>}
          <p className="text-sm">{t("associatedCount", { count: (detail.data.product_ids ?? []).length })}</p>
          <div className="grid gap-4 lg:grid-cols-2">
            <section className="space-y-2" aria-label={t("purchases")}>
              <h3 className="font-semibold">{t("purchases")}</h3>
              <FetchStatus loading={orders.loading} error={orders.error} empty={orders.data?.items.length === 0} />
              {orders.data?.items.map((order) => <div key={order.id} className="flex flex-wrap justify-between gap-2 border-b border-[var(--color-border)] pb-2">
                <span className="min-w-0 break-all text-sm">{order.supplier_invoice_number || order.purchase_number}</span>
                <button type="button" className={secondaryButton} onClick={() => openPurchase(order.id)}>{t("view")}</button>
              </div>)}
            </section>
            <section aria-label={t("ledger")} className="space-y-2">
              <h3 className="font-semibold">{t("ledger")}</h3>
              <FetchStatus loading={ledger.loading} error={ledger.error} empty={ledger.data?.items.length === 0} />
              {ledger.data?.items.map((entry) => <div key={entry.id} className="grid gap-1 border-b border-[var(--color-border)] pb-2 text-sm">
                <div className="flex flex-wrap justify-between gap-2"><span>{t("entry." + entry.kind)}</span><strong>{formatBDT(entry.amount)}</strong></div>
                <span className="text-[var(--color-muted-foreground)]">
                  {formatDate(entry.created_at, locale)}{entry.method ? " · " + t("method." + entry.method) : ""}
                </span>
                {entry.reference && <span className="break-all">{entry.reference}</span>}
              </div>)}
              {ledger.data && <Pager {...ledger.data} offset={ledgerOffset} setOffset={setLedgerOffset} />}
            </section>
          </div>
        </>}
      </Card>}
    </div>
  );
}

function SupplierForm({ supplier, initial, refresh, close, select }: {
  supplier?: InventorySupplier; initial: ProductOut[]; refresh: () => void;
  close: () => void; select: (id: string) => void;
}) {
  const t = useTranslations("inventoryOps");
  const locale = useLocale();
  const state = useWrite(refresh);
  const [linked, setLinked] = useState(() => (supplier?.product_ids ?? []).map((id) => ({
    id, label: initial.find((p) => p.id === id)?.sku ?? id,
  })));
  const [candidate, setCandidate] = useState<ProductOut | null>(null);

  return (
    <Card className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-bold">{t(supplier ? "editSupplier" : "addSupplier")}</h2>
        <button type="button" className={secondaryButton} onClick={close} disabled={state.busy}>{t("close")}</button>
      </div>
      <Form busy={state.busy} submit={t("saveSupplier")} onSubmit={async (data) => {
        const saved = await state.send<InventorySupplier>(supplier ? "suppliers/" + supplier.id : "suppliers", {
          name: value(data, "name"), name_bn: value(data, "name_bn") || null,
          phone: value(data, "phone") || null, address: value(data, "address") || null,
          is_active: value(data, "active") === "true", product_ids: linked.map((row) => row.id),
        }, supplier ? "PUT" : "POST");
        if (saved) { select(saved.id); close(); }
      }}>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field name="name" label={t("supplierName")} value={supplier?.name} required />
          <Field name="name_bn" label={t("banglaName")} value={supplier?.name_bn ?? ""} />
          <Field name="phone" label={t("phone")} value={supplier?.phone ?? ""} kind="tel" />
          <Field name="address" label={t("address")} value={supplier?.address ?? ""} />
          <label className="grid gap-1 text-sm font-medium">{t("status")}
            <select name="active" defaultValue={String(supplier?.is_active ?? true)} className="min-h-11 rounded-lg border border-[var(--color-border)] bg-white px-3">
              <option value="true">{t("active")}</option><option value="false">{t("inactive")}</option>
            </select>
          </label>
        </div>
        <div className="space-y-2">
          <h3 className="font-semibold">{t("associatedProducts")}</h3>
          <ProductPicker initial={initial} product={candidate} onPick={setCandidate} />
          <button type="button" className={secondaryButton} disabled={!candidate}
            onClick={() => {
              if (candidate && !linked.some((p) => p.id === candidate.id)) {
                setLinked([...linked, { id: candidate.id, label: localizedName(candidate.name_en, candidate.name_bn, locale) }]);
              }
              setCandidate(null);
            }}><Plus size={16} aria-hidden="true" />{t("linkProduct")}</button>
          <ul className="flex flex-wrap gap-2">
            {linked.map((row) => <li key={row.id}><button type="button" className={secondaryButton}
              aria-label={t("remove") + " " + row.label}
              onClick={() => setLinked(linked.filter((entry) => entry.id !== row.id))}>
              <X size={14} aria-hidden="true" /><span className="break-all">{row.label}</span>
            </button></li>)}
          </ul>
        </div>
      </Form>
      <WriteStatus state={state} />
    </Card>
  );
}
