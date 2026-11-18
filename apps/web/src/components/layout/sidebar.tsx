import { Receipt } from "lucide-react";
import { getTranslations } from "next-intl/server";
import { NavItem } from "./nav-item";
import type { Locale } from "@/i18n/config";

const ITEMS = [
  { key: "dashboard", href: "" },
  { key: "billing", href: "/billing" },
  { key: "inventory", href: "/inventory" },
  { key: "customers", href: "/customers" },
  { key: "loyalty", href: "/loyalty" },
  { key: "reports", href: "/reports" },
  { key: "settings", href: "/settings" },
] as const;

export async function Sidebar({ locale }: { locale: Locale }) {
  const t = await getTranslations({ locale, namespace: "nav" });
  const tApp = await getTranslations({ locale, namespace: "app" });

  return (
    <aside
      className="fixed inset-y-0 left-0 z-40 hidden w-64 flex-col border-r border-[var(--color-border)] bg-[var(--color-card)] lg:flex"
      aria-label="Primary"
    >
      <div className="flex items-center gap-3 border-b border-[var(--color-border)] px-5 py-4">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[var(--color-primary)] text-white">
          <Receipt className="h-5 w-5" aria-hidden="true" />
        </div>
        <div className="leading-tight">
          <p className="text-base font-bold text-[var(--color-ink)]">{tApp("name")}</p>
          <p className="text-xs text-[var(--color-muted-foreground)]">{tApp("tagline")}</p>
        </div>
      </div>
      <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-4" aria-label="Main">
        {ITEMS.map((item) => (
          <NavItem
            key={item.key}
            href={item.href}
            icon={item.key}
            label={t(item.key)}
            locale={locale}
          />
        ))}
      </nav>
      <div className="border-t border-[var(--color-border)] px-4 py-3">
        <p className="text-xs text-[var(--color-muted-foreground)]">
          {tApp("demoBadge")} · v0.1
        </p>
      </div>
    </aside>
  );
}
