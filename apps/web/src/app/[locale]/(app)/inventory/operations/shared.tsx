"use client";

import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Search } from "lucide-react";
import { ApiError, browserRequest, newIdempotencyKey } from "@/lib/api-client";
import { localizedName } from "@/lib/format";
import { fieldClass, localDigits, primaryButton, secondaryButton } from "@/components/ui/pos-form";
import type { Paginated, ProductOut } from "@/types";

export const prefix = "/api/inventory-ops/";

type Remote<T> = { path: string; token: string; data?: T; error?: boolean };

export function useRemote<T>(path: string | null, revision = 0) {
  const token = `${revision}:${path}`;
  const [result, setResult] = useState<Remote<T>>();
  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    browserRequest<T>(prefix + path, { signal: controller.signal })
      .then((data) => { if (!controller.signal.aborted) setResult({ path, token, data }); })
      .catch(() => { if (!controller.signal.aborted) setResult({ path, token, error: true }); });
    return () => controller.abort();
  }, [path, token]);
  return {
    data: result?.path === path ? result.data : undefined,
    error: result?.token === token && result.error,
    loading: Boolean(path && result?.token !== token),
  };
}

export function useWrite(refresh: () => void) {
  const [state, setState] = useState({ busy: false, error: "", success: false });
  const pending = useRef<{ signature: string; key: string } | null>(null);
  const inFlight = useRef(false);
  async function send<T>(path: string, data: object, method = "POST"): Promise<T | null> {
    if (inFlight.current) return null;
    const body = JSON.stringify(data);
    const signature = path + method + body;
    if (pending.current && pending.current.signature !== signature) {
      setState({ busy: false, error: "retrySame", success: false });
      return null;
    }
    const key = pending.current?.key ?? newIdempotencyKey();
    pending.current = { signature, key };
    inFlight.current = true;
    setState({ busy: true, error: "", success: false });
    try {
      const result = await browserRequest<T>(prefix + path, {
        method, body, headers: { "Content-Type": "application/json", "Idempotency-Key": key },
      });
      pending.current = null;
      setState({ busy: false, error: "", success: true });
      refresh();
      return result;
    } catch (error) {
      if (error instanceof ApiError && error.status < 500) pending.current = null;
      const code = error instanceof ApiError ? error.code : "retrySame";
      setState({ busy: false, error: code, success: false });
      return null;
    } finally {
      inFlight.current = false;
    }
  }
  return { ...state, send };
}

export function WriteStatus({ state }: { state: ReturnType<typeof useWrite> }) {
  const t = useTranslations("inventoryOps");
  if (state.error) return <p role="alert" className="mt-2 text-sm text-red-700">{t.has("errors." + state.error) ? t("errors." + state.error) : t("errors.unknown")}</p>;
  return state.success ? <p role="status" className="mt-2 text-sm font-semibold text-[var(--color-primary-strong)]">{t("saved")}</p> : null;
}

export function FetchStatus({ loading, error, empty }: { loading?: boolean; error?: boolean; empty?: boolean }) {
  const t = useTranslations("inventoryOps");
  if (error) return <p role="alert" className="py-3 text-sm text-red-700">{t("loadError")}</p>;
  if (loading) return <p role="status" className="py-3 text-sm">{t("loading")}</p>;
  return empty ? <p className="py-3 text-sm text-[var(--color-muted-foreground)]">{t("empty")}</p> : null;
}

export function SearchBox({ label, onSearch }: { label: string; onSearch: (q: string) => void }) {
  const t = useTranslations("inventoryOps");
  return (
    <form className="flex flex-wrap items-end gap-2" onSubmit={(event) => {
      event.preventDefault();
      onSearch(String(new FormData(event.currentTarget).get("search") ?? "").trim());
    }}>
      <label className="grid flex-1 basis-48 gap-1 text-sm font-medium">
        <span>{label}</span>
        <input name="search" type="search" className={fieldClass} maxLength={160} />
      </label>
      <button className={secondaryButton}><Search size={16} aria-hidden="true" />{t("search")}</button>
    </form>
  );
}

export function Pager({ offset, total, limit, setOffset }: {
  offset: number; total: number; limit: number; setOffset: (value: number) => void;
}) {
  const t = useTranslations("inventoryOps");
  if (offset === 0 && total <= limit) return null;
  return (
    <nav className="flex flex-wrap items-center justify-between gap-2 text-sm" aria-label={t("page")}>
      <button type="button" className={secondaryButton} disabled={offset === 0}
        onClick={() => setOffset(Math.max(0, offset - limit))}>{t("previous")}</button>
      <span>{Math.min(offset + 1, total)}–{Math.min(offset + limit, total)} / {total}</span>
      <button type="button" className={secondaryButton} disabled={offset + limit >= total}
        onClick={() => setOffset(offset + limit)}>{t("next")}</button>
    </nav>
  );
}

export function ProductPicker({ initial, product, onPick, searchLabel, label }: {
  initial: ProductOut[]; product: ProductOut | null; onPick: (p: ProductOut | null) => void;
  searchLabel?: string; label?: string;
}) {
  const t = useTranslations("inventoryOps");
  const locale = useLocale();
  const [search, setSearch] = useState("");
  const query = search.trim();
  const { data, loading, error } = useRemote<Paginated<ProductOut>>(query ? "catalog/products?" + new URLSearchParams({ q: query, limit: "40" }) : null);
  const products = query ? data?.items ?? [] : initial;
  const displayed = product && !products.some((row) => row.id === product.id) ? [product, ...products] : products;
  return (
    <div className="space-y-2">
      <label className="grid gap-1 text-sm font-medium">
        <span>{searchLabel ?? t("findProduct")}</span>
        <input type="search" value={search} maxLength={120} className={fieldClass} onChange={(event) => setSearch(event.target.value)} />
      </label>
      <label className="grid gap-1 text-sm font-medium">
        <span>{label ?? t("product")}</span>
        <select className={fieldClass} value={product?.id ?? ""}
          onChange={(event) => onPick(displayed.find((row) => row.id === event.target.value) ?? null)}>
          <option value="">{t("selectProduct")}</option>
          {displayed.map((row) => <option key={row.id} value={row.id}>{localizedName(row.name_en, row.name_bn, locale)} · {row.sku}</option>)}
        </select>
      </label>
      <FetchStatus loading={loading} error={error} empty={Boolean(query && data?.items.length === 0)} />
    </div>
  );
}

export function Field({ name, label, value, required, kind = "text" }: {
  name: string; label: string; value?: string; required?: boolean; kind?: "text" | "date" | "decimal" | "tel";
}) {
  return (
    <label className="grid min-w-0 gap-1 text-sm font-medium">
      <span>{label}</span>
      <input name={name} defaultValue={value} required={required} className={fieldClass}
        type={kind === "decimal" ? "text" : kind} inputMode={kind === "decimal" ? "decimal" : undefined} />
    </label>
  );
}

export function Form({ children, onSubmit, busy, submit }: {
  children: ReactNode; onSubmit: (data: FormData) => void; busy: boolean; submit: string;
}) {
  const t = useTranslations("inventoryOps");
  function handle(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSubmit(new FormData(event.currentTarget));
  }
  return (
    <form onSubmit={handle} className="space-y-3">
      <fieldset disabled={busy} className="space-y-3">{children}</fieldset>
      <button className={primaryButton} disabled={busy}>{busy ? t("working") : submit}</button>
    </form>
  );
}

export const value = (data: FormData, name: string) => String(data.get(name) ?? "").trim();
export const quantity = (data: FormData, name: string) => localDigits(value(data, name));
