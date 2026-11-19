import { getTranslations } from "next-intl/server";
import { ArrowLeft } from "lucide-react";
import { Link, redirect } from "@/i18n/navigation";
import { api } from "@/lib/api";
import { hasPermission, verifySession } from "@/lib/session";
import { EmptyState } from "@/components/ui/empty-state";
import { secondaryButton } from "@/components/ui/pos-form";
import { PrintersClient } from "./printers-client";
import { JobsList } from "./jobs-list";
import type { Locale } from "@/i18n/config";

export const dynamic = "force-dynamic";

export default async function PrintersPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "printers" });
  const tStates = await getTranslations({ locale, namespace: "states" });

  const session = await verifySession();
  if (!session) {
    redirect({ href: "/login", locale: locale as Locale });
  }
  // Printer + queue management is owner-only (mirrors settings:write on the API).
  if (!hasPermission(session!.me, "settings:write")) {
    redirect({ href: "/settings", locale: locale as Locale });
  }

  const [printers, counters, jobs] = await Promise.all([
    api.printers().catch(() => null),
    api.manageCounters().catch(() => []),
    api.printJobs({ limit: 25 }).catch(() => null),
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

      {!printers ? (
        <EmptyState title={tStates("error")} hint="API unreachable." />
      ) : (
        <>
          <PrintersClient
            locale={locale as Locale}
            printers={printers}
            counters={counters}
          />
          {jobs ? (
            <JobsList
              locale={locale as Locale}
              jobs={jobs.items}
              printers={printers.map((p) => ({ id: p.id, name: p.name }))}
            />
          ) : null}
        </>
      )}
    </div>
  );
}
