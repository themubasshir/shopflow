import { getTranslations } from "next-intl/server";
import { BottomNavItem } from "./bottom-nav-item";
import type { Locale } from "@/i18n/config";

const PRIMARY = [
  { key: "dashboard", href: "" },
  { key: "billing", href: "/billing" },
  { key: "inventory", href: "/inventory" },
  { key: "customers", href: "/customers" },
  { key: "more", href: "/reports" },
] as const;

export async function BottomNav({ locale }: { locale: Locale }) {
  const t = await getTranslations({ locale, namespace: "nav" });

  return (
    <nav
      className="fixed bottom-0 left-0 right-0 z-40 flex border-t border-[var(--color-border)] bg-[var(--color-card)] pb-[env(safe-area-inset-bottom)] lg:hidden"
      aria-label="Primary mobile"
    >
      {PRIMARY.map((item) => (
        <BottomNavItem
          key={item.key}
          href={item.href}
          icon={item.key}
          label={item.key === "more" ? "More" : t(item.key)}
          locale={locale}
        />
      ))}
    </nav>
  );
}
