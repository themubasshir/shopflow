"use client";

import { useMemo, useRef, useState, type FormEvent } from "react";
import { useTranslations } from "next-intl";
import { PackagePlus, Pencil, Power, PowerOff, Search, Trash2, Upload } from "lucide-react";
import { useRouter } from "@/i18n/navigation";
import { browserRequest, fieldErrors } from "@/lib/api-client";
import {
  errorCode,
  fieldClass,
  localDigits,
  primaryButton,
  secondaryButton,
} from "@/components/ui/pos-form";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { formatBDT, formatQuantity, localizedName } from "@/lib/format";
import type {
  CategoryManageOut,
  CategoryOut,
  ImportPreview,
  ImportReport,
  MedicineWrite,
  ProductDetailOut,
  ProductOut,
  ProductUnitWrite,
  ProductWrite,
} from "@/types";

type Tab = "products" | "categories" | "import";

export function ProductsClient({
  locale,
  canWrite,
  initialTab,
  initialQuery,
  products,
  categories,
  categoriesManage,
}: {
  locale: string;
  canWrite: boolean;
  initialTab: string;
  initialQuery: string;
  products: ProductOut[];
  categories: CategoryOut[];
  categoriesManage: CategoryManageOut[];
}) {
  const t = useTranslations("products");
  const router = useRouter();
  const [tab, setTab] = useState<Tab>(
    (["products", "categories", "import"] as const).includes(initialTab as Tab)
      ? (initialTab as Tab)
      : "products",
  );
  const [query, setQuery] = useState(initialQuery);
  const [editing, setEditing] = useState<ProductDetailOut | "new" | null>(null);

  function search(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    router.push(`/products?q=${encodeURIComponent(query)}`);
    router.refresh();
  }

  const tabs: { key: Tab; label: string; writeOnly?: boolean }[] = [
    { key: "products", label: t("title") },
    { key: "categories", label: t("categories.title"), writeOnly: true },
    { key: "import", label: t("import.title"), writeOnly: true },
  ];

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-[var(--color-ink)]">{t("title")}</h1>
          <p className="text-sm text-[var(--color-muted-foreground)]">{t("subtitle")}</p>
        </div>
        {canWrite && tab === "products" && (
          <button className={primaryButton} onClick={() => setEditing("new")}>
            <PackagePlus size={18} aria-hidden="true" />
            {t("add")}
          </button>
        )}
      </header>

      <div className="flex gap-1 rounded-lg border border-[var(--color-border)] bg-[var(--color-card)] p-1" role="tablist">
        {tabs.map((tabDef) => {
          if (tabDef.writeOnly && !canWrite) return null;
          const active = tab === tabDef.key;
          return (
            <button
              key={tabDef.key}
              role="tab"
              aria-selected={active}
              onClick={() => setTab(tabDef.key)}
              className={`min-h-10 flex-1 rounded-md px-3 text-sm font-semibold transition-colors ${
                active
                  ? "bg-[var(--color-primary)] text-white"
                  : "text-[var(--color-ink)] hover:bg-[var(--color-primary-100)]"
              }`}
            >
              {tabDef.label}
            </button>
          );
        })}
      </div>

      {tab === "products" && (
        <>
          <form onSubmit={search} className="flex gap-2">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t("search")}
              className={fieldClass}
              aria-label={t("search")}
            />
            <button className={secondaryButton} type="submit" aria-label={t("search")}>
              <Search size={18} aria-hidden="true" />
            </button>
          </form>

          {products.length === 0 ? (
            <EmptyState title={t("empty")} hint={t("emptyHint")} />
          ) : (
            <div className="overflow-hidden rounded-lg border border-[var(--color-border)] bg-[var(--color-card)]">
              <ul className="divide-y divide-[var(--color-border)]">
                {products.map((p) => (
                  <li key={p.id} className="flex items-center justify-between gap-3 px-4 py-3">
                    <div className="min-w-0">
                      <p className="truncate font-semibold text-[var(--color-ink)]">
                        {localizedName(p.name_en, p.name_bn, locale)}
                      </p>
                      <p className="text-xs text-[var(--color-muted-foreground)]">
                        {p.sku}
                        {p.barcode ? ` · ${p.barcode}` : ""}
                        {" · "}
                        {localizedName(p.category_name_en, p.category_name_bn, locale)}
                      </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-3">
                      <div className="text-right">
                        <p className="text-sm font-semibold">{formatBDT(p.price, locale)}</p>
                        <p className="text-xs text-[var(--color-muted-foreground)]">
                          {t("stock")}: {formatQuantity(p.stock_on_hand, locale)}
                        </p>
                      </div>
                      <Badge variant={p.is_medicine ? "warning" : "default"}>
                        {p.is_medicine ? t("medicine") : t("grocery")}
                      </Badge>
                      <Badge variant={p.is_active ? "success" : "danger"}>
                        {p.is_active ? t("active") : t("inactive")}
                      </Badge>
                      {canWrite && (
                        <button
                          className={secondaryButton}
                          onClick={() => loadProduct(p.id)}
                          aria-label={t("edit")}
                        >
                          <Pencil size={15} aria-hidden="true" />
                        </button>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}

      {tab === "categories" && canWrite && (
        <CategoriesTab categories={categoriesManage} />
      )}

      {tab === "import" && canWrite && <ImportTab />}

      {editing !== null && (
        <ProductForm
          detail={editing === "new" ? null : editing}
          categories={categories}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            router.refresh();
          }}
        />
      )}
    </div>
  );

  async function loadProduct(id: string) {
    const detail = await browserRequest<ProductDetailOut>(
      `/api/catalog-ops/catalog/products/${id}`,
    );
    setEditing(detail);
  }
}

/* -------------------------------------------------------------------------- */
/* Product create/edit form                                                    */
/* -------------------------------------------------------------------------- */

function ProductForm({
  detail,
  categories,
  onClose,
  onSaved,
}: {
  detail: ProductDetailOut | null;
  categories: CategoryOut[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const t = useTranslations("products");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [invalid, setInvalid] = useState<string[]>([]);
  const [isMedicine, setIsMedicine] = useState(detail?.is_medicine ?? false);
  const [units, setUnits] = useState<ProductUnitWrite[]>(
    detail?.units?.length
      ? detail.units.map((u) => ({
          name: u.name,
          name_bn: u.name_bn,
          conversion_factor: u.conversion_factor,
          selling_price: u.selling_price,
          is_base: u.is_base,
        }))
      : [{ name: "piece", name_bn: "টি", conversion_factor: "1", selling_price: "0", is_base: true }],
  );

  function updateUnit(i: number, patch: Partial<ProductUnitWrite>) {
    setUnits((prev) => prev.map((u, idx) => (idx === i ? { ...u, ...patch } : u)));
  }

  async function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError("");
    setInvalid([]);
    const f = new FormData(e.currentTarget);
    const name_en = String(f.get("name_en")).trim();
    const name_bn = String(f.get("name_bn")).trim();
    const sku = String(f.get("sku")).trim();
    const errs: string[] = [];
    if (!name_en) errs.push("name_en");
    if (!name_bn) errs.push("name_bn");
    if (!detail && !sku) errs.push("sku");
    if (!units.length || units.filter((u) => u.is_base).length !== 1) {
      setError("units");
      return;
    }
    if (errs.length) {
      setInvalid(errs);
      return;
    }

    const aliases = String(f.get("search_aliases"))
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);

    const medicine: MedicineWrite | null = isMedicine
      ? {
          brand_name: String(f.get("brand_name")).trim() || name_en,
          generic_name: String(f.get("generic_name")).trim() || name_en,
          manufacturer: String(f.get("manufacturer")).trim() || null,
          strength: String(f.get("strength")).trim() || null,
          dosage_form: String(f.get("dosage_form")).trim() || null,
          pack_size: String(f.get("pack_size")).trim() || null,
          mrp: localDigits(String(f.get("mrp")).trim()) || null,
          purchase_cost: localDigits(String(f.get("purchase_cost")).trim()) || null,
          retail_price: localDigits(String(f.get("retail_price")).trim()) || null,
          prescription_required: f.get("prescription_required") === "on",
        }
      : null;

    const baseBody = {
      category_id: String(f.get("category_id")),
      barcode: String(f.get("barcode")).trim() || null,
      name_en,
      name_bn,
      search_aliases: aliases,
      unit: String(f.get("unit")).trim() || "piece",
      pack_size: String(f.get("pack_size")).trim() || null,
      is_medicine: isMedicine,
      loyalty_eligible: f.get("loyalty_eligible") === "on",
      tax_rate: localDigits(String(f.get("tax_rate")).trim()) || "0",
      low_stock_threshold: localDigits(String(f.get("low_stock_threshold")).trim()) || "10",
      units,
      medicine,
    };

    // is_active is only meaningful on update; ProductWrite forbids it on create.
    const body: ProductWrite | Record<string, unknown> = detail
      ? { ...baseBody, is_active: f.get("is_active") === "on" }
      : ({ ...baseBody, sku } as ProductWrite);

    setSaving(true);
    try {
      await browserRequest<ProductDetailOut>(
        detail
          ? `/api/catalog-ops/catalog/products/${detail.id}`
          : "/api/catalog-ops/catalog/products",
        {
          method: detail ? "PUT" : "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
      );
      onSaved();
    } catch (err) {
      const code = errorCode(err);
      setError(code === "conflict" ? "duplicate" : code === "validation" ? "units" : "unknown");
      setInvalid(Object.keys(fieldErrors(err)));
    } finally {
      setSaving(false);
    }
  }

  const med = detail?.medicine;

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-0 sm:items-center sm:p-6" role="dialog" aria-modal="true">
      <Card className="max-h-[92vh] w-full max-w-2xl overflow-y-auto rounded-b-none sm:rounded-b-lg">
        <h2 className="mb-3 text-lg font-bold">{t(detail ? "edit" : "add")}</h2>
        <form onSubmit={save} className="space-y-4">
          <fieldset disabled={saving} className="grid gap-3 sm:grid-cols-2">
            <label className="space-y-1 text-sm font-medium">
              <span>{t("name_en")} *</span>
              <input name="name_en" defaultValue={detail?.name_en} className={fieldClass} aria-invalid={invalid.includes("name_en")} maxLength={200} />
            </label>
            <label className="space-y-1 text-sm font-medium">
              <span>{t("name_bn")} *</span>
              <input name="name_bn" defaultValue={detail?.name_bn} className={fieldClass} aria-invalid={invalid.includes("name_bn")} maxLength={200} />
            </label>
            <label className="space-y-1 text-sm font-medium">
              <span>{t("sku")} *</span>
              <input name="sku" defaultValue={detail?.sku} className={fieldClass} readOnly={!!detail} aria-invalid={invalid.includes("sku")} maxLength={64} />
            </label>
            <label className="space-y-1 text-sm font-medium">
              <span>{t("barcode")}</span>
              <input name="barcode" defaultValue={detail?.barcode ?? ""} className={fieldClass} maxLength={64} />
            </label>
            <label className="space-y-1 text-sm font-medium">
              <span>{t("category")} *</span>
              <select name="category_id" defaultValue={detail?.category_id ?? categories[0]?.id} className={fieldClass}>
                {categories.map((c) => (
                  <option key={c.id} value={c.id}>
                    {localizedName(c.name_en, c.name_bn, "")}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-1 text-sm font-medium">
              <span>{t("unit")}</span>
              <input name="unit" defaultValue={detail?.unit ?? "piece"} className={fieldClass} maxLength={16} />
            </label>
            <label className="space-y-1 text-sm font-medium">
              <span>{t("packSize")}</span>
              <input name="pack_size" defaultValue={detail?.pack_size ?? ""} className={fieldClass} maxLength={64} />
            </label>
            <label className="space-y-1 text-sm font-medium">
              <span>{t("taxRate")}</span>
              <input name="tax_rate" inputMode="decimal" defaultValue={String(detail?.tax_rate ?? "0")} className={fieldClass} />
            </label>
            <label className="space-y-1 text-sm font-medium">
              <span>{t("reorderLevel")}</span>
              <input name="low_stock_threshold" inputMode="decimal" defaultValue={String(detail?.low_stock_threshold ?? "10")} className={fieldClass} />
            </label>
            <label className="space-y-1 text-sm font-medium sm:col-span-2">
              <span>{t("aliases")}</span>
              <input name="search_aliases" defaultValue={(detail?.search_aliases ?? []).join(", ")} className={fieldClass} placeholder={t("aliasesHint")} />
            </label>
            <label className="flex items-center gap-2 text-sm font-medium">
              <input type="checkbox" name="loyalty_eligible" defaultChecked={detail?.loyalty_eligible ?? true} className="h-5 w-5" />
              {t("loyaltyEligible")}
            </label>
            <label className="flex items-center gap-2 text-sm font-medium">
              <input type="checkbox" checked={isMedicine} onChange={(e) => setIsMedicine(e.target.checked)} className="h-5 w-5" />
              {t("medicine")}
            </label>
            {detail && (
              <label className="flex items-center gap-2 text-sm font-medium">
                <input type="checkbox" name="is_active" defaultChecked={detail.is_active} className="h-5 w-5" />
                {t("active")}
              </label>
            )}
          </fieldset>

          {/* Units */}
          <div>
            <div className="mb-1 flex items-center justify-between">
              <h3 className="text-sm font-semibold">{t("units")}</h3>
              <button type="button" className={secondaryButton} onClick={() => setUnits([...units, { name: "", name_bn: "", conversion_factor: "1", selling_price: "0", is_base: false }])}>
                {t("addUnit")}
              </button>
            </div>
            <p className="mb-2 text-xs text-[var(--color-muted-foreground)]">{t("unitsHint")}</p>
            <div className="space-y-2">
              {units.map((u, i) => (
                <div key={i} className="grid grid-cols-[1fr_1fr_80px_90px_auto_auto] items-center gap-2">
                  <input value={u.name} onChange={(e) => updateUnit(i, { name: e.target.value })} placeholder={t("unitName")} className={fieldClass} />
                  <input value={u.name_bn} onChange={(e) => updateUnit(i, { name_bn: e.target.value })} placeholder={t("unitNameBn")} className={fieldClass} />
                  <input value={String(u.conversion_factor)} onChange={(e) => updateUnit(i, { conversion_factor: e.target.value })} placeholder={t("conversion")} inputMode="decimal" className={fieldClass} />
                  <input value={String(u.selling_price)} onChange={(e) => updateUnit(i, { selling_price: e.target.value })} placeholder={t("price")} inputMode="decimal" className={fieldClass} />
                  <label className="flex items-center gap-1 text-xs" title={t("isBase")}>
                    <input type="checkbox" checked={u.is_base} onChange={(e) => updateUnit(i, { is_base: e.target.checked })} className="h-4 w-4" />
                  </label>
                  <button type="button" className="text-red-700" onClick={() => setUnits(units.filter((_, x) => x !== i))} aria-label={t("removeUnit")}>×</button>
                </div>
              ))}
            </div>
          </div>

          {/* Medicine fields */}
          {isMedicine && (
            <fieldset disabled={saving} className="grid gap-3 rounded-lg border border-[var(--color-border)] p-3 sm:grid-cols-2">
              <h3 className="text-sm font-semibold sm:col-span-2">{t("medicineFields")}</h3>
              <label className="space-y-1 text-sm"><span>{t("brandName")}</span><input name="brand_name" defaultValue={med?.brand_name} className={fieldClass} /></label>
              <label className="space-y-1 text-sm"><span>{t("genericName")}</span><input name="generic_name" defaultValue={med?.generic_name} className={fieldClass} /></label>
              <label className="space-y-1 text-sm"><span>{t("manufacturer")}</span><input name="manufacturer" defaultValue={med?.manufacturer ?? ""} className={fieldClass} /></label>
              <label className="space-y-1 text-sm"><span>{t("strength")}</span><input name="strength" defaultValue={med?.strength ?? ""} className={fieldClass} /></label>
              <label className="space-y-1 text-sm"><span>{t("dosageForm")}</span><input name="dosage_form" defaultValue={med?.dosage_form ?? ""} className={fieldClass} /></label>
              <label className="space-y-1 text-sm"><span>{t("mrp")}</span><input name="mrp" inputMode="decimal" defaultValue={med?.mrp ? String(med.mrp) : ""} className={fieldClass} /></label>
              <label className="space-y-1 text-sm"><span>{t("purchaseCost")}</span><input name="purchase_cost" inputMode="decimal" defaultValue={med?.purchase_cost ? String(med.purchase_cost) : ""} className={fieldClass} /></label>
              <label className="space-y-1 text-sm"><span>{t("retailPrice")}</span><input name="retail_price" inputMode="decimal" defaultValue={med?.retail_price ? String(med.retail_price) : ""} className={fieldClass} /></label>
              <label className="flex items-center gap-2 text-sm"><input type="checkbox" name="prescription_required" defaultChecked={med?.prescription_required} className="h-5 w-5" />{t("prescriptionRequired")}</label>
            </fieldset>
          )}

          {detail?.has_history && (
            <p className="text-xs text-[var(--color-muted-foreground)]">{t("hasHistory")}</p>
          )}
          {error && <p role="alert" className="text-sm text-red-700">{t(`errors.${error}` as never)}</p>}
          <div className="flex flex-wrap gap-2">
            <button className={primaryButton} disabled={saving}>{t(saving ? "saving" : "save")}</button>
            <button type="button" className={secondaryButton} disabled={saving} onClick={onClose}>{t("cancel")}</button>
          </div>
        </form>
      </Card>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Category management                                                         */
/* -------------------------------------------------------------------------- */

function CategoriesTab({ categories }: { categories: CategoryManageOut[] }) {
  const t = useTranslations("products.categories");
  const tUnits = useTranslations("products");
  const router = useRouter();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [editing, setEditing] = useState<CategoryManageOut | null>(null);
  const formRef = useRef<HTMLFormElement>(null);

  async function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError("");
    const f = new FormData(e.currentTarget);
    const body = {
      name_en: String(f.get("name_en")).trim(),
      name_bn: String(f.get("name_bn")).trim(),
      slug: String(f.get("slug")).trim().toLowerCase(),
      parent_id: String(f.get("parent_id")) || null,
      is_medicine: f.get("is_medicine") === "on",
      loyalty_eligible: editing ? editing.loyalty_eligible : true,
      sort_order: Number(localDigits(String(f.get("sort_order")).trim()) || "0"),
      is_active: editing ? editing.is_active : true,
    };
    setSaving(true);
    try {
      await browserRequest<CategoryManageOut>(
        editing
          ? `/api/catalog-ops/catalog/categories/${editing.id}`
          : "/api/catalog-ops/catalog/categories",
        {
          method: editing ? "PUT" : "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
      );
      formRef.current?.reset();
      setEditing(null);
      router.refresh();
    } catch (err) {
      const code = errorCode(err);
      setError(code === "conflict" ? "duplicate" : code === "validation" ? "cycle" : "unknown");
    } finally {
      setSaving(false);
    }
  }

  async function setActive(c: CategoryManageOut, active: boolean) {
    setError("");
    setBusy(c.id);
    try {
      await browserRequest<CategoryManageOut>(
        `/api/catalog-ops/catalog/categories/${c.id}/state`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ is_active: active }),
        },
      );
      router.refresh();
    } catch {
      setError("unknown");
    } finally {
      setBusy(null);
    }
  }

  async function remove(c: CategoryManageOut) {
    setError("");
    setBusy(c.id);
    try {
      await browserRequest(`/api/catalog-ops/catalog/categories/${c.id}`, {
        method: "DELETE",
      });
      if (editing?.id === c.id) setEditing(null);
      router.refresh();
    } catch {
      setError("deleteBlocked");
    } finally {
      setBusy(null);
    }
  }

  const canDelete = (c: CategoryManageOut) =>
    c.product_count === 0 && !categories.some((x) => x.parent_id === c.id);

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <h3 className="mb-3 font-semibold">{t(editing ? "edit" : "add")}</h3>
        <form ref={formRef} key={editing?.id ?? "new"} onSubmit={save} className="grid gap-3">
          <input name="name_en" placeholder={t("name_en")} required className={fieldClass} defaultValue={editing?.name_en} />
          <input name="name_bn" placeholder={t("name_bn")} required className={fieldClass} defaultValue={editing?.name_bn} />
          <input name="slug" placeholder={t("slugHint")} required className={fieldClass} defaultValue={editing?.slug} />
          <select name="parent_id" className={fieldClass} defaultValue={editing?.parent_id ?? ""}>
            <option value="">{t("noParent")}</option>
            {categories.filter((c) => c.id !== editing?.id).map((c) => (
              <option key={c.id} value={c.id}>{c.name_en}</option>
            ))}
          </select>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" name="is_medicine" defaultChecked={editing?.is_medicine} className="h-5 w-5" />
            {t("isMedicine")}
          </label>
          <input name="sort_order" inputMode="numeric" placeholder={t("sortOrder")} defaultValue={editing ? String(editing.sort_order) : "0"} className={fieldClass} />
          {error && <p role="alert" className="text-sm text-red-700">{t(`errors.${error}` as never)}</p>}
          <div className="flex gap-2">
            <button className={primaryButton} disabled={saving}>{t(editing ? "saveEdit" : "save")}</button>
            {editing && (
              <button type="button" className={secondaryButton} disabled={saving} onClick={() => { setEditing(null); formRef.current?.reset(); }}>
                {tUnits("cancel")}
              </button>
            )}
          </div>
        </form>
      </Card>
      <Card>
        <h3 className="mb-3 font-semibold">{t("title")}</h3>
        {categories.length === 0 ? (
          <EmptyState title={t("empty")} />
        ) : (
          <ul className="divide-y divide-[var(--color-border)]">
            {categories.map((c) => (
              <li key={c.id} className="flex items-center justify-between gap-2 py-2 text-sm">
                <span className={c.is_active ? "" : "line-through opacity-60"}>
                  {c.name_en} <span className="text-xs text-[var(--color-muted-foreground)]">({c.slug})</span>
                </span>
                <span className="flex shrink-0 items-center gap-2">
                  <span className="text-xs text-[var(--color-muted-foreground)]">
                    {c.product_count} {tUnits("title").toLowerCase()}
                    {c.is_medicine ? ` · ${tUnits("medicine")}` : ""}
                    {!c.is_active ? ` · ${tUnits("inactive")}` : ""}
                  </span>
                  <button type="button" className={secondaryButton} disabled={busy === c.id}
                    onClick={() => setEditing(c)} aria-label={t("edit")}>
                    <Pencil size={14} aria-hidden="true" />
                  </button>
                  <button type="button" className={secondaryButton} disabled={busy === c.id}
                    onClick={() => setActive(c, !c.is_active)} aria-label={c.is_active ? tUnits("deactivate") : tUnits("activate")}>
                    {c.is_active ? <PowerOff size={14} aria-hidden="true" /> : <Power size={14} aria-hidden="true" />}
                  </button>
                  {canDelete(c) && (
                    <button type="button" className={secondaryButton} disabled={busy === c.id}
                      onClick={() => remove(c)} aria-label={tUnits("delete")}>
                      <Trash2 size={14} aria-hidden="true" />
                    </button>
                  )}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Bulk import                                                                 */
/* -------------------------------------------------------------------------- */

function ImportTab() {
  const t = useTranslations("products.import");
  const router = useRouter();
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [createMissing, setCreateMissing] = useState(false);
  const [approved, setApproved] = useState<Set<string>>(new Set());

  async function doPreview(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setError("");
    setReport(null);
    setPreview(null);
    if (!/\.(csv|xlsx|xlsm)$/i.test(file.name)) {
      setError("file");
      return;
    }
    setBusy(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await browserRequest<ImportPreview>(
        "/api/catalog-ops/catalog/imports/preview",
        { method: "POST", body: form },
      );
      setPreview(res);
      setApproved(new Set(res.rows.filter((r) => r.action === "create").map((r) => r.data?.sku ?? "").filter(Boolean)));
    } catch {
      setError("unknown");
    } finally {
      setBusy(false);
    }
  }

  async function doCommit() {
    if (!preview) return;
    const rows = preview.rows
      .filter((r) => r.action === "create" && r.data && approved.has(r.data.sku))
      .map((r) => r.data!);
    setBusy(true);
    try {
      const res = await browserRequest<ImportReport>(
        "/api/catalog-ops/catalog/imports/commit",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ rows, create_missing_categories: createMissing }),
        },
      );
      setReport(res);
      setPreview(null);
      router.refresh();
    } catch {
      setError("unknown");
    } finally {
      setBusy(false);
    }
  }

  const template = useMemo(
    () =>
      "data:text/csv;charset=utf-8," +
      encodeURIComponent(
        "sku,name_en,name_bn,barcode,category_slug,unit,selling_price,is_medicine,brand_name,generic_name,manufacturer,strength,dosage_form,pack_size,mrp,purchase_cost,retail_price,prescription_required\n" +
        "DEMO-1,Sample Rice,নমুনা চাল,,grocery,kg,60,0,,,,,,,,,,0\n",
      ),
    [],
  );

  return (
    <Card className="max-w-3xl space-y-4">
      <h3 className="font-semibold">{t("subtitle")}</h3>
      <p className="text-xs text-[var(--color-muted-foreground)]">{t("note")}</p>
      <a href={template} download="products-template.csv" className={`${secondaryButton} w-fit`}>
        {t("downloadTemplate")}
      </a>

      <div>
        <label className="block text-sm font-medium">{t("choose")}</label>
        <input type="file" accept=".csv,.xlsx,.xlsm" onChange={doPreview} disabled={busy} className="mt-1" />
      </div>

      {busy && <p className="text-sm">{preview ? t("committing") : t("uploading")}</p>}
      {error && <p role="alert" className="text-sm text-red-700">{t(`errors.${error}` as never)}</p>}

      {report && (
        <div className="rounded-lg border border-[var(--color-border)] p-3">
          <h4 className="font-semibold">{t("result")}</h4>
          <p className="text-sm">
            {t("created")}: {report.created} · {t("skipped")}: {report.skipped} · {t("failed")}: {report.errors}
          </p>
          <ul className="mt-2 max-h-48 space-y-1 overflow-y-auto text-xs">
            {report.results.map((r, i) => (
              <li key={i} className="flex justify-between">
                <span>{r.sku}</span>
                <span>{r.status}{r.detail ? ` — ${r.detail}` : ""}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {preview && (
        <div className="space-y-3">
          <p className="text-sm">
            {t("total")}: {preview.total_rows} · {t("valid")}: {preview.create_count} ·{" "}
            {t("duplicate")}: {preview.duplicate_count} · {t("invalid")}: {preview.invalid_count}
          </p>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={createMissing} onChange={(e) => setCreateMissing(e.target.checked)} className="h-5 w-5" />
            {t("createMissing")}
          </label>
          <div className="max-h-72 overflow-y-auto rounded-lg border border-[var(--color-border)]">
            <table className="w-full text-left text-xs">
              <thead className="sticky top-0 bg-[var(--color-muted)]">
                <tr>
                  <th className="px-2 py-1">{t("row")}</th>
                  <th className="px-2 py-1">SKU</th>
                  <th className="px-2 py-1">{t("action")}</th>
                  <th className="px-2 py-1">{t("approve")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--color-border)]">
                {preview.rows.map((r) => (
                  <tr key={r.row}>
                    <td className="px-2 py-1">{r.row}</td>
                    <td className="px-2 py-1">{r.data?.sku ?? "—"}</td>
                    <td className="px-2 py-1">
                      {r.action}
                      {r.errors.length ? ` (${r.errors.map((e) => e.message).join("; ")})` : ""}
                      {r.duplicate_of ? ` (${r.duplicate_of})` : ""}
                    </td>
                    <td className="px-2 py-1">
                      {r.action === "create" && r.data ? (
                        <input
                          type="checkbox"
                          checked={approved.has(r.data.sku)}
                          onChange={(e) => {
                            const next = new Set(approved);
                            if (e.target.checked) next.add(r.data!.sku);
                            else next.delete(r.data!.sku);
                            setApproved(next);
                          }}
                          className="h-4 w-4"
                          aria-label={t("approve")}
                        />
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <button className={primaryButton} onClick={doCommit} disabled={busy || approved.size === 0}>
            <Upload size={16} aria-hidden="true" />
            {t("commit")} ({approved.size})
          </button>
        </div>
      )}
    </Card>
  );
}
