"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Boxes, ClipboardList, History, Pill, Truck } from "lucide-react";
import { secondaryButton } from "@/components/ui/pos-form";
import type { ProductOut } from "@/types";
import { Suppliers } from "./suppliers";
import { Purchases } from "./purchases";
import { Batches, LowStock, Movements } from "./stock";

const tabs = [
  { key: "purchases", Icon: ClipboardList }, { key: "suppliers", Icon: Truck },
  { key: "batches", Icon: Pill }, { key: "movements", Icon: History }, { key: "low", Icon: Boxes },
] as const;

export function Operations({ initialProducts, canWrite }: { initialProducts: ProductOut[]; canWrite: boolean }) {
  const t = useTranslations("inventoryOps");
  const [view, setView] = useState<typeof tabs[number]["key"]>("purchases");
  const [revision, setRevision] = useState(0);
  const [purchase, setPurchase] = useState<string | null>(null);
  const [product, setProduct] = useState<ProductOut | null>(null);
  const props = { initial: initialProducts, canWrite, revision, refresh: () => setRevision((r) => r + 1) };

  return (
    <div className="space-y-3">
      <nav className="flex flex-wrap gap-2" aria-label={t("title")}>
        {tabs.map(({ key, Icon }) => <button key={key} type="button" aria-pressed={view === key}
          className={secondaryButton + " aria-pressed:border-[var(--color-primary)] aria-pressed:bg-[var(--color-primary-100)]"}
          onClick={() => setView(key)}><Icon size={16} aria-hidden="true" />{t(key)}</button>)}
      </nav>
      {view === "suppliers" && <Suppliers {...props} openPurchase={(id) => { setPurchase(id); setView("purchases"); }} />}
      {view === "purchases" && <Purchases {...props} selected={purchase} setSelected={setPurchase} />}
      {view === "batches" && <Batches {...props} />}
      {view === "movements" && <Movements {...props} product={product} setProduct={setProduct} />}
      {view === "low" && <LowStock revision={revision} select={(row) => { setProduct(row); setView("movements"); }} />}
    </div>
  );
}
