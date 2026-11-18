import { getTranslations } from "next-intl/server";
import { BottomNavItem } from "./bottom-nav-item";
import { hasPermission } from "@/lib/session";
import type { Me } from "@/lib/session";
import type { Locale } from "@/i18n/config";

const PRIMARY: { key: string; href: string; permission?: string }[] = [
  { key: "dashboard", href: "" },
  { key: "billing", href: "/billing" },
  { key: "inventory", href: "/inventory" },
  { key: "customers", href: "/customers" },
  { key: "more", href: "/reports", permission: "reports:read" },
];

export async function BottomNav({ locale, me }: { locale: Locale; me: Me }) {
  const t = await getTranslations({ locale, namespace: "nav" });

  const items = PRIMARY.filter(
    (item) => !item.permission || hasPermission(me, item.permission),
  );

  return (
    <nav
      className="fixed bottom-0 left-0 right-0 z-40 flex border-t border-[var(--color-border)] bg-[var(--color-card)] pb-[env(safe-area-inset-bottom)] lg:hidden"
      aria-label="Primary mobile"
    >
      {items.map((item) => (
        <BottomNavItem
          key={item.key}
          href={item.href}
          icon={item.key}
          label={item.key === "more" ? t("more") : t(item.key)}
          locale={locale}
        />
      ))}
    </nav>
  );
}
