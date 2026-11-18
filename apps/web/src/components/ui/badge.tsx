import { cn } from "@/lib/utils";

const variants = {
  default: "bg-[var(--color-muted)] text-[var(--color-ink)]",
  success: "bg-[var(--color-primary-100)] text-[var(--color-primary-strong)]",
  warning: "bg-amber-100 text-amber-800",
  danger: "bg-red-100 text-red-800",
  outline: "border border-[var(--color-border)] text-[var(--color-muted-foreground)]",
};

export function Badge({
  variant = "default",
  className,
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & { variant?: keyof typeof variants }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold",
        variants[variant],
        className,
      )}
      {...props}
    />
  );
}
