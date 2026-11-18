"use client";

import { usePathname, Link } from "@/i18n/navigation";
import type { Locale } from "@/i18n/config";
import {
  LayoutDashboard,
  Receipt,
  Package,
  Users,
  MoreHorizontal,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";

const ICONS: Record<string, LucideIcon> = {
  dashboard: LayoutDashboard,
  billing: Receipt,
  inventory: Package,
  customers: Users,
  more: MoreHorizontal,
};

export function BottomNavItem({
  href,
  icon,
  label,
}: {
  href: string;
  icon: string;
  label: string;
  locale: Locale;
}) {
  const pathname = usePathname();
  const isActive =
    href === "" ? pathname === "/" || pathname === "" : pathname.startsWith(href);
  const Icon = ICONS[icon] ?? LayoutDashboard;

  return (
    <Link
      href={href || "/"}
      aria-current={isActive ? "page" : undefined}
      className={cn(
        "flex min-h-[56px] flex-1 flex-col items-center justify-center gap-0.5 py-2 text-xs font-medium transition-colors duration-150",
        isActive ? "text-[var(--color-primary)]" : "text-[var(--color-muted-foreground)]",
      )}
    >
      <Icon className="h-5 w-5" aria-hidden="true" />
      <span className="max-w-full truncate px-1">{label}</span>
    </Link>
  );
}
