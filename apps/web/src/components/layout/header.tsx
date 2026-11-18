import { ShoppingCart } from "lucide-react";
import { getTranslations } from "next-intl/server";
import { Link } from "@/i18n/navigation";
import { LanguageSwitcher } from "./language-switcher";
import { AccountMenu } from "./account-menu";
import type { Me } from "@/lib/session";
import type { Locale } from "@/i18n/config";

export async function Header({ locale, me }: { locale: Locale; me: Me }) {
  const t = await getTranslations({ locale, namespace: "actions" });
  const tApp = await getTranslations({ locale, namespace: "app" });

  return (
    <header className="sticky top-0 z-30 flex h-16 items-center justify-between gap-3 border-b border-[var(--color-border)] bg-[var(--color-card)]/95 px-4 backdrop-blur">
      <div className="flex items-center gap-3 lg:hidden">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[var(--color-primary)] text-white">
          <ShoppingCart className="h-4 w-4" aria-hidden="true" />
        </div>
        <span className="text-lg font-bold text-[var(--color-ink)]">{tApp("name")}</span>
      </div>
      <div className="hidden lg:block" />
      <div className="flex items-center gap-3">
        <Link
          href="/billing"
          className="hidden items-center gap-2 rounded-lg bg-[var(--color-primary)] px-4 py-2 text-sm font-semibold text-white transition-colors duration-150 hover:bg-[var(--color-primary-strong)] sm:flex"
        >
          <ShoppingCart className="h-4 w-4" aria-hidden="true" />
          {t("newBill")}
        </Link>
        <LanguageSwitcher locale={locale} />
        <AccountMenu me={me} />
      </div>
    </header>
  );
}
