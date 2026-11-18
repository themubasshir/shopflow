import type { LucideIcon } from "lucide-react";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export function KpiCard({
  title,
  value,
  subtitle,
  icon: Icon,
  iconBg,
  valueClassName,
}: {
  title: string;
  value: string;
  subtitle?: string;
  icon: LucideIcon;
  iconBg?: string;
  valueClassName?: string;
}) {
  return (
    <Card className="flex items-center gap-4">
      <div
        className={cn(
          "flex h-12 w-12 shrink-0 items-center justify-center rounded-xl",
          iconBg ?? "bg-[var(--color-primary-100)] text-[var(--color-primary)]",
        )}
        aria-hidden="true"
      >
        <Icon className="h-6 w-6" />
      </div>
      <div className="min-w-0">
        <p className="truncate text-xs font-medium uppercase tracking-wide text-[var(--color-muted-foreground)]">
          {title}
        </p>
        <p className={cn("truncate text-2xl font-bold tabular-nums", valueClassName ?? "text-[var(--color-ink)]")}>
          {value}
        </p>
        {subtitle ? (
          <p className="truncate text-xs text-[var(--color-muted-foreground)]">{subtitle}</p>
        ) : null}
      </div>
    </Card>
  );
}
