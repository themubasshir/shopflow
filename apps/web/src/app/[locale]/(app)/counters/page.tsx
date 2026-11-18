import { getTranslations } from "next-intl/server";
import { redirect } from "@/i18n/navigation";
import { api } from "@/lib/api";
import { hasPermission, verifySession } from "@/lib/session";
import { EmptyState } from "@/components/ui/empty-state";
import { CountersClient } from "./counters-client";
import type { CounterStaffOut } from "@/types";
import type { Locale } from "@/i18n/config";

export const dynamic = "force-dynamic";

export default async function CountersPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "counterMgmt" });
  const tStates = await getTranslations({ locale, namespace: "states" });

  const session = await verifySession();
  if (!session) {
    redirect({ href: "/login", locale: locale as Locale });
  }
  if (!hasPermission(session!.me, "counters:manage")) {
    redirect({ href: "/", locale: locale as Locale });
  }

  const counters = await api.manageCounters().catch(() => null);
  // Staff rosters are per-counter; fetch them in parallel once we have the list.
  const staff: Record<string, CounterStaffOut[]> = {};
  if (counters) {
    const rosters = await Promise.all(
      counters.map((c) => api.counterStaff(c.id).catch(() => [] as CounterStaffOut[])),
    );
    counters.forEach((c, i) => {
      staff[c.id] = rosters[i] ?? [];
    });
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold text-[var(--color-ink)] sm:text-2xl">{t("title")}</h1>
        <p className="text-sm text-[var(--color-muted-foreground)]">{t("subtitle")}</p>
      </div>

      {!counters ? (
        <EmptyState title={tStates("error")} hint="API unreachable." />
      ) : (
        <CountersClient locale={locale as Locale} counters={counters} staff={staff} />
      )}
    </div>
  );
}
