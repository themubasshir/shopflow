import { Sidebar } from "./sidebar";
import { Header } from "./header";
import { BottomNav } from "./bottom-nav";
import type { Locale } from "@/i18n/config";
import type { Me } from "@/lib/session";

/**
 * Responsive app shell:
 *  - < 1024px : header + bottom nav (mobile-first cashier workflow)
 *  - >= 1024px: persistent sidebar + header
 * The signed-in user (`me`) drives the role-aware nav and the account menu.
 */
export function AppShell({
  locale,
  me,
  children,
}: {
  locale: Locale;
  me: Me;
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-dvh bg-[var(--color-surface)]">
      <Sidebar locale={locale} me={me} />
      <div className="flex min-h-dvh flex-col lg:pl-64">
        <Header locale={locale} me={me} />
        <main className="flex-1 px-4 pb-28 pt-4 lg:pb-8">
          <div className="mx-auto w-full max-w-[1440px]">{children}</div>
        </main>
        <BottomNav locale={locale} me={me} />
      </div>
    </div>
  );
}
