import { ApiError } from "@/lib/api-client";

export const fieldClass = "min-h-11 w-full rounded-lg border border-[var(--color-border)] bg-white px-3 text-base";
export const primaryButton = "inline-flex min-h-11 cursor-pointer items-center justify-center gap-2 rounded-lg bg-[var(--color-primary)] px-4 text-sm font-semibold text-white transition-colors hover:bg-[var(--color-primary-strong)] disabled:cursor-not-allowed disabled:opacity-60";
export const secondaryButton = "inline-flex min-h-11 cursor-pointer items-center justify-center gap-2 rounded-lg border border-[var(--color-border)] bg-white px-4 text-sm font-semibold transition-colors hover:bg-[var(--color-primary-050)] disabled:cursor-not-allowed disabled:opacity-60";

export function errorCode(error: unknown) {
  return error instanceof ApiError ? error.code : "network";
}

export function localDigits(value: string) {
  return value.replace(/[০-৯]/g, (digit) => String("০১২৩৪৫৬৭৮৯".indexOf(digit)));
}

/** Taka amounts as integer poisha for form validation and estimates. */
export function minorUnits(value: string): number | null {
  const text = localDigits(value.trim());
  if (!/^\d{1,12}(\.\d{1,2})?$/.test(text)) return null;
  const [whole, fraction = ""] = text.split(".");
  return Number(whole) * 100 + Number(fraction.padEnd(2, "0"));
}
