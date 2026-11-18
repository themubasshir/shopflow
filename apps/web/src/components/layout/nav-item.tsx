"use client";

import { usePathname } from "@/i18n/navigation";
import { Link } from "@/i18n/navigation";
import type { Locale } from "@/i18n/config";
import {
  LayoutDashboard,
  Receipt,
  Package,
  Users,
  Gift,
  BarChart3,
  Settings,
  MoreHorizontal,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";

const ICONS: Record<string, LucideIcon> = {
  dashboard: LayoutDashboard,
  billing: Receipt,
  inventory: Package,
  customers: Users,
  loyalty: Gift,
  reports: BarChart3,
  settings: Settings,
  more: MoreHorizontal,
};

export function NavItem({
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
        "group flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors duration-150",
        isActive
          ? "bg-[var(--color-primary)] text-white"
          : "text-[var(--color-ink)] hover:bg-[var(--color-primary-100)] hover:text-[var(--color-primary-strong)]",
      )}
    >
      <Icon className="h-5 w-5 shrink-0" aria-hidden="true" />
      <span>{label}</span>
    </Link>
  );
}
