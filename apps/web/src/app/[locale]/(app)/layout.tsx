import { redirect } from "@/i18n/navigation";
import { AppShell } from "@/components/layout/app-shell";
import { verifySession } from "@/lib/session";
import type { Locale } from "@/i18n/config";

export const dynamic = "force-dynamic";

/**
 * Protected group layout. `verifySession()` is the auth gate — when there is no
 * valid session it returns null and we bounce to the localized /login before
 * any protected page renders. On success we hand the resolved user (`me`) to
 * the shell so the sidebar can filter nav by permission and the header can show
 * the account menu.
 */
export default async function AppGroupLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const session = await verifySession();
  if (!session) {
    redirect({ href: "/login", locale: locale as Locale });
  }

  return (
    <AppShell locale={locale as Locale} me={session!.me}>
      {children}
    </AppShell>
  );
}
