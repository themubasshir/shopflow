"use client";

import { usePathname, useRouter } from "@/i18n/navigation";
import { useParams } from "next/navigation";
import { Languages } from "lucide-react";
import { localeNames, type Locale } from "@/i18n/config";

export function LanguageSwitcher({ locale }: { locale: Locale }) {
  const pathname = usePathname();
  const router = useRouter();
  const params = useParams();

  const toggle = () => {
    const next: Locale = locale === "en" ? "bn" : "en";
    // Preserve the current path + query so the user stays exactly where they are.
    router.replace({ pathname, query: params }, { locale: next });
  };

  const nextLabel = locale === "en" ? localeNames.bn : localeNames.en;

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={`Switch to ${nextLabel}`}
      className="flex min-h-[44px] min-w-[44px] items-center justify-center gap-1.5 rounded-lg border border-[var(--color-border)] bg-[var(--color-card)] px-3 text-sm font-semibold text-[var(--color-ink)] transition-colors duration-150 hover:bg-[var(--color-primary-100)]"
    >
      <Languages className="h-4 w-4" aria-hidden="true" />
      <span className="hidden sm:inline">{nextLabel}</span>
      <span className="sm:hidden">{locale === "en" ? "বাং" : "EN"}</span>
    </button>
  );
}
