import { cn } from "@/lib/utils";

export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={cn("animate-pulse rounded-lg bg-[var(--color-muted)]", className)}
    />
  );
}

export function KpiSkeleton() {
  return (
    <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] p-4">
      <Skeleton className="mb-2 h-4 w-20" />
      <Skeleton className="h-8 w-28" />
    </div>
  );
}
