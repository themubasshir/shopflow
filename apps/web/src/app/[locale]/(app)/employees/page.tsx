import { getTranslations } from "next-intl/server";
import { redirect } from "@/i18n/navigation";
import { api } from "@/lib/api";
import { hasPermission, verifySession } from "@/lib/session";
import { EmptyState } from "@/components/ui/empty-state";
import { EmployeesClient } from "./employees-client";
import type { Locale } from "@/i18n/config";

export const dynamic = "force-dynamic";

export default async function EmployeesPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "employees" });
  const tStates = await getTranslations({ locale, namespace: "states" });

  const session = await verifySession();
  if (!session) {
    redirect({ href: "/login", locale: locale as Locale });
  }
  if (!hasPermission(session!.me, "employees:manage")) {
    redirect({ href: "/", locale: locale as Locale });
  }

  const [employees, roles, counters] = await Promise.all([
    api.employees().catch(() => null),
    api.employeeRoles().catch(() => null),
    api.counters().catch(() => null),
  ]);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold text-[var(--color-ink)] sm:text-2xl">{t("title")}</h1>
        <p className="text-sm text-[var(--color-muted-foreground)]">{t("subtitle")}</p>
      </div>

      {!employees || !roles ? (
        <EmptyState title={tStates("error")} hint="API unreachable." />
      ) : (
        <EmployeesClient
          locale={locale as Locale}
          employees={employees}
          roles={roles}
          counters={counters ?? []}
        />
      )}
    </div>
  );
}
