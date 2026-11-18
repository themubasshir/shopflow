"use client";

import { useState } from "react";
import { MonitorSmartphone, Users } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRouter } from "@/i18n/navigation";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { localizedName } from "@/lib/format";
import type { CounterOut, CounterStaffOut } from "@/types";
import type { Locale } from "@/i18n/config";

export function CountersClient({
  locale,
  counters,
  staff,
}: {
  locale: Locale;
  counters: CounterOut[];
  staff: Record<string, CounterStaffOut[]>;
}) {
  const t = useTranslations("counterMgmt");
  const tStates = useTranslations("states");
  const router = useRouter();
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function toggle(counter: CounterOut) {
    if (pendingId) return;
    setPendingId(counter.id);
    setError(null);
    try {
      const res = await fetch(`/api/manage/counters/${counter.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_active: !counter.is_active }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setError(body.code ?? "unknown");
        return;
      }
      router.refresh();
    } catch {
      setError("network");
    } finally {
      setPendingId(null);
    }
  }

  if (counters.length === 0) {
    return <EmptyState title={tStates("empty")} hint={tStates("emptyHint")} />;
  }

  return (
    <>
      {error ? (
        <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm font-medium text-red-700">
          {t(`errors.${error}` as never)}
        </p>
      ) : null}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {counters.map((c) => (
          <Card key={c.id} className={!c.is_active ? "opacity-70" : undefined}>
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-3">
                <div
                  className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl font-bold ${
                    c.is_active
                      ? "bg-[var(--color-primary-100)] text-[var(--color-primary-strong)]"
                      : "bg-[var(--color-muted)] text-[var(--color-muted-foreground)]"
                  }`}
                >
                  <MonitorSmartphone className="h-5 w-5" aria-hidden="true" />
                </div>
                <div className="min-w-0">
                  <p className="truncate font-semibold">
                    {c.code} · {localizedName(c.name_en, c.name_bn, locale)}
                  </p>
                  <Badge variant={c.is_active ? "success" : "danger"} className="mt-1">
                    {c.is_active ? t("active") : t("inactive")}
                  </Badge>
                </div>
              </div>
              <button
                type="button"
                role="switch"
                aria-checked={c.is_active}
                aria-label={c.is_active ? t("deactivate") : t("activate")}
                disabled={pendingId === c.id}
                onClick={() => toggle(c)}
                className={`relative h-7 w-12 shrink-0 rounded-full transition-colors disabled:opacity-50 ${
                  c.is_active ? "bg-[var(--color-primary)]" : "bg-[var(--color-muted)]"
                }`}
              >
                <span
                  className={`absolute top-1 h-5 w-5 rounded-full bg-white shadow transition-transform ${
                    c.is_active ? "left-6" : "left-1"
                  }`}
                />
              </button>
            </div>
            <div className="mt-3 border-t border-[var(--color-border)] pt-3">
              <p className="mb-1 flex items-center gap-1 text-xs font-semibold uppercase tracking-wide text-[var(--color-muted-foreground)]">
                <Users className="h-3.5 w-3.5" aria-hidden="true" />
                {t("assignedStaff")}
              </p>
              {staff[c.id]?.length ? (
                <ul className="space-y-1">
                  {staff[c.id].map((s) => (
                    <li key={s.email} className="flex items-center justify-between text-xs">
                      <span className="truncate">{s.name}</span>
                      <Badge variant={s.is_active ? "success" : "outline"}>
                        {s.is_active ? t("active") : t("inactive")}
                      </Badge>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-[var(--color-muted-foreground)]">{t("noStaff")}</p>
              )}
            </div>
          </Card>
        ))}
      </div>
    </>
  );
}
