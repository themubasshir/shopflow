import { getTranslations } from "next-intl/server";
import { ArrowLeft } from "lucide-react";
import { Link, redirect } from "@/i18n/navigation";
import { api } from "@/lib/api";
import { hasPermission, verifySession } from "@/lib/session";
import { EmptyState } from "@/components/ui/empty-state";
import { secondaryButton } from "@/components/ui/pos-form";
import { MedexClient } from "./medex-client";
import type { Locale } from "@/i18n/config";

export const dynamic = "force-dynamic";

export default async function MedexImportPage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string }>;
  searchParams: Promise<{ q?: string; status?: string; offset?: string }>;
}) {
  const { locale } = await params;
  const { q = "", status = "pending_review", offset = "0" } = await searchParams;
  const t = await getTranslations({ locale, namespace: "medex" });
  const tStates = await getTranslations({ locale, namespace: "states" });

  const session = await verifySession();
  if (!session) {
    redirect({ href: "/login", locale: locale as Locale });
  }
  // Reviewing + promoting staged medicines is a catalog-write action.
  if (!hasPermission(session!.me, "catalog:write")) {
    redirect({ href: "/settings", locale: locale as Locale });
  }

  const limit = 25;
  const params_q: Record<string, string | number> = { limit, offset: Number(offset) || 0 };
  if (q) params_q.q = q;
  if (status) params_q.status = status;

  const [source, staging, stats, filters, matches, runs] = await Promise.all([
    api.medexSource().catch(() => null),
    api.medexStaging(params_q).catch(() => null),
    api.medexStats().catch(() => null),
    api.medexFilters().catch(() => ({ manufacturers: [], generics: [] })),
    api.medexMatches({ status: "pending" }).catch(() => []),
    api.medexRuns(10).catch(() => []),
  ]);

  return (
    <div className="space-y-4">
      <div>
        <Link href="/settings" className={secondaryButton}>
          <ArrowLeft size={17} aria-hidden="true" />
          {t("back")}
        </Link>
      </div>
      <div>
        <h1 className="text-xl font-bold text-[var(--color-ink)] sm:text-2xl">{t("title")}</h1>
        <p className="text-sm text-[var(--color-muted-foreground)]">{t("subtitle")}</p>
      </div>

      {!staging ? (
        <EmptyState title={tStates("error")} hint="API unreachable." />
      ) : (
        <MedexClient
          locale={locale as Locale}
          consentNote={source?.consent_note ?? null}
          rows={staging.rows}
          total={staging.total}
          offset={staging.offset}
          limit={staging.limit}
          stats={stats}
          filters={filters}
          matches={matches}
          runs={runs}
          initialQuery={q}
          initialStatus={status}
        />
      )}
    </div>
  );
}
