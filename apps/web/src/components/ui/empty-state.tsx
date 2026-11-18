import { Inbox } from "lucide-react";

export function EmptyState({
  title,
  hint,
}: {
  title: string;
  hint?: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-[var(--color-border)] py-10 text-center">
      <Inbox className="h-8 w-8 text-[var(--color-muted-foreground)]" aria-hidden="true" />
      <p className="text-sm font-medium text-[var(--color-ink)]">{title}</p>
      {hint ? <p className="max-w-xs text-xs text-[var(--color-muted-foreground)]">{hint}</p> : null}
    </div>
  );
}
