import { getTranslations } from "next-intl/server";
import { Receipt } from "lucide-react";
import { LanguageSwitcher } from "@/components/layout/language-switcher";
import type { Locale } from "@/i18n/config";

/**
 * Public auth chrome: a centered column with the brand mark and a language
 * switcher. Deliberately no sidebar / bottom nav — those belong to the
 * authenticated (app) shell.
 */
export default async function AuthLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const tApp = await getTranslations({ locale, namespace: "app" });

  return (
    <div className="flex min-h-dvh flex-col bg-[var(--color-surface)]">
      <header className="flex items-center justify-between px-4 py-4 sm:px-6">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[var(--color-primary)] text-white">
            <Receipt className="h-5 w-5" aria-hidden="true" />
          </div>
          <div className="leading-tight">
            <p className="text-base font-bold text-[var(--color-ink)]">{tApp("name")}</p>
            <p className="text-xs text-[var(--color-muted-foreground)]">{tApp("tagline")}</p>
          </div>
        </div>
        <LanguageSwitcher locale={locale as Locale} />
      </header>
      <main className="flex flex-1 items-center justify-center px-4 pb-16">
        {children}
      </main>
    </div>
  );
}
