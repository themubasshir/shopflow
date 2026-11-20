"use client";

import { useMemo, useState, type FormEvent } from "react";
import { useTranslations } from "next-intl";
import { Check, Search, ShieldCheck, X } from "lucide-react";
import { useRouter } from "@/i18n/navigation";
import { browserRequest } from "@/lib/api-client";
import {
  fieldClass,
  localDigits,
  primaryButton,
  secondaryButton,
} from "@/components/ui/pos-form";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { formatBDT, localizedName } from "@/lib/format";
import type {
  MedexMatchOut,
  MedexRunOut,
  MedexStagingOut,
  MedexStatsOut,
} from "@/types";

const STATUS_ORDER = [
  "pending_review",
  "staged",
  "imported",
  "matched",
  "rejected",
] as const;

export function MedexClient({
  locale,
  consentNote,
  rows,
  total,
  offset,
  limit,
  stats,
  filters,
  matches,
  runs,
  initialQuery,
  initialStatus,
}: {
  locale: string;
  consentNote: string | null;
  rows: MedexStagingOut[];
  total: number;
  offset: number;
  limit: number;
  stats: MedexStatsOut | null;
  filters: { manufacturers: string[]; generics: string[] };
  matches: MedexMatchOut[];
  runs: MedexRunOut[];
  initialQuery: string;
  initialStatus: string;
}) {
  const t = useTranslations("medex");
  const router = useRouter();
  const [query, setQuery] = useState(initialQuery);
  const [status, setStatus] = useState(initialStatus);
  const [manufacturer, setManufacturer] = useState("");
  const [generic, setGeneric] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  // Per-row sellable price the owner typed before approving (opt-in only).
  const [price, setPrice] = useState<Record<string, string>>({});

  const matchByStaging = useMemo(() => {
    const m = new Map<string, MedexMatchOut[]>();
    for (const match of matches) {
      const list = m.get(match.staging_id) ?? [];
      list.push(match);
      m.set(match.staging_id, list);
    }
    return m;
  }, [matches]);

  function search(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    apply(0);
  }

  function apply(nextOffset: number) {
    const p = new URLSearchParams();
    if (query) p.set("q", query);
    if (status) p.set("status", status);
    if (manufacturer) p.set("manufacturer", manufacturer);
    if (generic) p.set("generic", generic);
    if (nextOffset) p.set("offset", String(nextOffset));
    router.push(`/settings/medex?${p.toString()}`);
    router.refresh();
  }

  async function approve(row: MedexStagingOut) {
    setBusy(row.id);
    setError("");
    try {
      const selling = localDigits(price[row.id] ?? "").trim();
      await browserRequest("/api/medex-ops/staging/approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          staging_id: row.id,
          selling_price: selling === "" ? null : selling,
        }),
      });
      setPrice((prev) => ({ ...prev, [row.id]: "" }));
      router.refresh();
    } catch {
      setError("approve");
    } finally {
      setBusy(null);
    }
  }

  async function reject(row: MedexStagingOut) {
    setBusy(row.id);
    setError("");
    try {
      await browserRequest("/api/medex-ops/staging/reject", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ staging_id: row.id }),
      });
      router.refresh();
    } catch {
      setError("reject");
    } finally {
      setBusy(null);
    }
  }

  async function decide(matchId: string, confirm: boolean) {
    setBusy(matchId);
    setError("");
    try {
      await browserRequest("/api/medex-ops/matches/decide", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ match_id: matchId, confirm }),
      });
      router.refresh();
    } catch {
      setError("match");
    } finally {
      setBusy(null);
    }
  }

  const lastPage = offset + limit;
  const hasPrev = offset > 0;
  const hasNext = offset + limit < total;

  return (
    <div className="space-y-4">
      {/* Consent + stats banner */}
      {consentNote && (
        <Card className="border-[var(--color-primary-200)] bg-[var(--color-primary-050)]">
          <p className="flex items-start gap-2 text-xs text-[var(--color-ink)]">
            <ShieldCheck size={15} aria-hidden="true" className="mt-0.5 shrink-0 text-[var(--color-primary)]" />
            <span>{consentNote}</span>
          </p>
        </Card>
      )}

      {stats && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Stat label={t("staged")} value={stats.total} />
          <Stat
            label={t("pending")}
            value={Number(stats.by_status?.pending_review ?? 0)}
          />
          <Stat label={t("missingPrice")} value={stats.missing_price} />
          <Stat label={t("matchCandidates")} value={stats.match_candidates} />
        </div>
      )}

      {runs.length > 0 && (
        <Card>
          <h3 className="mb-2 text-sm font-semibold">{t("runs")}</h3>
          <ul className="divide-y divide-[var(--color-border)] text-xs">
            {runs.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                <span className="font-mono">{r.id.slice(0, 8)}</span>
                <Badge variant={r.status === "completed" ? "success" : r.status === "failed" ? "danger" : "default"}>
                  {t(`runStatus.${r.status}` as never)}
                </Badge>
                <span className="text-[var(--color-muted-foreground)]">
                  {t("runSummary", { staged: r.staged, fetched: r.fetched, failed: r.failed })}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {/* Filters */}
      <Card>
        <form onSubmit={search} className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("search")}
            className={fieldClass}
            aria-label={t("search")}
          />
          <select value={status} onChange={(e) => setStatus(e.target.value)} className={fieldClass} aria-label={t("status")}>
            <option value="">{t("allStatus")}</option>
            {STATUS_ORDER.map((s) => (
              <option key={s} value={s}>{t(`importStatus.${s}` as never)}</option>
            ))}
          </select>
          <select value={manufacturer} onChange={(e) => setManufacturer(e.target.value)} className={fieldClass} aria-label={t("manufacturer")}>
            <option value="">{t("allManufacturers")}</option>
            {filters.manufacturers.map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
          <select value={generic} onChange={(e) => setGeneric(e.target.value)} className={fieldClass} aria-label={t("generic")}>
            <option value="">{t("allGenerics")}</option>
            {filters.generics.map((g) => (
              <option key={g} value={g}>{g}</option>
            ))}
          </select>
          <button className={secondaryButton} type="submit" aria-label={t("search")}>
            <Search size={16} aria-hidden="true" />
            {t("search")}
          </button>
        </form>
      </Card>

      {error && (
        <p role="alert" className="text-sm text-red-700">{t(`errors.${error}` as never)}</p>
      )}

      {/* Staging table */}
      {rows.length === 0 ? (
        <EmptyState title={t("empty")} hint={t("emptyHint")} />
      ) : (
        <Card className="p-0">
          <div className="table-scroll overflow-x-auto">
            <table className="w-full min-w-[900px] text-left text-sm">
              <thead className="bg-[var(--color-muted)] text-xs">
                <tr>
                  <th className="px-3 py-2">{t("medicine")}</th>
                  <th className="px-3 py-2">{t("generic")}</th>
                  <th className="px-3 py-2">{t("manufacturer")}</th>
                  <th className="px-3 py-2">{t("strengthForm")}</th>
                  <th className="px-3 py-2">{t("medexPrice")}</th>
                  <th className="px-3 py-2">{t("status")}</th>
                  <th className="px-3 py-2">{t("review")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--color-border)]">
                {rows.map((row) => (
                  <StagingRow
                    key={row.id}
                    row={row}
                    locale={locale}
                    matches={matchByStaging.get(row.id) ?? []}
                    busy={busy}
                    price={price[row.id] ?? ""}
                    onPrice={(v) => setPrice((p) => ({ ...p, [row.id]: v }))}
                    onApprove={() => approve(row)}
                    onReject={() => reject(row)}
                    onDecide={decide}
                    t={t}
                  />
                ))}
              </tbody>
            </table>
          </div>
          {/* Pager */}
          <div className="flex items-center justify-between border-t border-[var(--color-border)] px-3 py-2 text-xs">
            <span className="text-[var(--color-muted-foreground)]">
              {t("results", { first: total === 0 ? 0 : offset + 1, last: Math.min(lastPage, total), total })}
            </span>
            <div className="flex gap-2">
              <button className={secondaryButton} disabled={!hasPrev} onClick={() => apply(offset - limit)}>
                {t("previous")}
              </button>
              <button className={secondaryButton} disabled={!hasNext} onClick={() => apply(offset + limit)}>
                {t("next")}
              </button>
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <Card className="py-3 text-center">
      <p className="text-lg font-bold">{value}</p>
      <p className="text-xs text-[var(--color-muted-foreground)]">{label}</p>
    </Card>
  );
}

function StagingRow({
  row,
  locale,
  matches,
  busy,
  price,
  onPrice,
  onApprove,
  onReject,
  onDecide,
  t,
}: {
  row: MedexStagingOut;
  locale: string;
  matches: MedexMatchOut[];
  busy: string | null;
  price: string;
  onPrice: (v: string) => void;
  onApprove: () => void;
  onReject: () => void;
  onDecide: (matchId: string, confirm: boolean) => void;
  t: ReturnType<typeof useTranslations>;
}) {
  const brand = localizedName(row.brand_name, row.brand_name_bn, locale);
  const secondary = locale === "bn" ? row.brand_name : row.brand_name_bn;
  const generic = localizedName(row.generic_name, row.generic_name_bn, locale);
  const mfr = localizedName(row.manufacturer, row.manufacturer_bn, locale);
  const strength = localizedName(row.strength, row.strength_bn, locale);
  const form = localizedName(row.dosage_form, row.dosage_form_bn, locale);
  const pending = row.import_status === "pending_review" || row.import_status === "staged";
  const reference = row.unit_price ?? row.strip_price ?? row.pack_price;

  return (
    <tr className="align-top">
      <td className="px-3 py-2">
        <p className="font-semibold text-[var(--color-ink)]">{brand || `#${row.external_id}`}</p>
        {secondary && secondary !== brand && (
          <p className="text-xs text-[var(--color-muted-foreground)]">{secondary}</p>
        )}
        {row.prescription_note && (
          <Badge variant="warning">{t("rx")}</Badge>
        )}
      </td>
      <td className="px-3 py-2 text-xs">{generic || "—"}</td>
      <td className="px-3 py-2 text-xs">{mfr || "—"}</td>
      <td className="px-3 py-2 text-xs">
        {[strength, form].filter(Boolean).join(" · ") || "—"}
        {row.pack_label ? <p className="text-[var(--color-muted-foreground)]">{row.pack_label}</p> : null}
      </td>
      <td className="px-3 py-2 text-xs">
        {reference ? formatBDT(reference, locale) : "—"}
        {row.pack_price ? (
          <p className="text-[var(--color-muted-foreground)]">
            {t("pack")}: {formatBDT(row.pack_price, locale)}
          </p>
        ) : null}
      </td>
      <td className="px-3 py-2">
        <Badge
          variant={
            row.import_status === "imported"
              ? "success"
              : row.import_status === "rejected"
                ? "danger"
                : row.import_status === "matched"
                  ? "default"
                  : "warning"
          }
        >
          {t(`importStatus.${row.import_status}` as never)}
        </Badge>
        {row.validation_status !== "valid" && (
          <p className="mt-1 text-[10px] text-amber-700">{t(`validationStatus.${row.validation_status}` as never)}</p>
        )}
      </td>
      <td className="px-3 py-2">
        {pending ? (
          <div className="space-y-2">
            <div className="flex items-center gap-1">
              <input
                value={price}
                onChange={(e) => onPrice(e.target.value)}
                inputMode="decimal"
                placeholder={t("sellPrice")}
                className={`${fieldClass} w-24 px-2 py-1 text-xs`}
                aria-label={t("sellPrice")}
              />
              <button
                className={primaryButton}
                disabled={busy === row.id}
                onClick={onApprove}
                aria-label={t("approve")}
                title={t("approveHint")}
              >
                <Check size={14} aria-hidden="true" />
              </button>
              <button
                className={secondaryButton}
                disabled={busy === row.id}
                onClick={onReject}
                aria-label={t("reject")}
              >
                <X size={14} aria-hidden="true" />
              </button>
            </div>
            {matches.map((m) => (
              <div key={m.id} className="flex items-center gap-1 rounded border border-amber-300 bg-amber-50 px-2 py-1 text-[11px]">
                <span className="flex-1">
                  {t("match")}: {m.product_name_en ?? m.product_sku} ({m.score})
                </span>
                <button className={secondaryButton} disabled={busy === m.id} onClick={() => onDecide(m.id, true)} aria-label={t("confirmMatch")}>
                  <Check size={12} aria-hidden="true" />
                </button>
                <button className={secondaryButton} disabled={busy === m.id} onClick={() => onDecide(m.id, false)} aria-label={t("rejectMatch")}>
                  <X size={12} aria-hidden="true" />
                </button>
              </div>
            ))}
          </div>
        ) : (
          <span className="text-xs text-[var(--color-muted-foreground)]">
            {row.linked_product_id ? t("linked") : "—"}
          </span>
        )}
      </td>
    </tr>
  );
}
