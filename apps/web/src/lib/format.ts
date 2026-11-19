const bdtFormatter = new Intl.NumberFormat("en", {
  minimumFractionDigits: 0,
  maximumFractionDigits: 2,
});

const numberFormatter = new Intl.NumberFormat("en-BD", {
  maximumFractionDigits: 2,
});

/** Format a Decimal string from the API as BDT. Always Latin digits for POS legibility. */
export function formatBDT(value: string | number | null | undefined): string {
  if (value == null || value === "") return "৳0";
  const n = typeof value === "string" ? parseFloat(value) : value;
  if (Number.isNaN(n)) return "৳0";
  return `৳${bdtFormatter.format(n)}`;
}

export function formatNumber(value: string | number | null | undefined): string {
  if (value == null || value === "") return "0";
  const n = typeof value === "string" ? parseFloat(value) : value;
  return numberFormatter.format(Number.isNaN(n) ? 0 : n);
}

export function formatDate(iso: string | null | undefined, locale = "en"): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat(locale === "bn" ? "bn-BD-u-nu-latn" : "en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(new Date(iso));
}

export function formatTime(iso: string | null | undefined, locale = "en"): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat(locale === "bn" ? "bn-BD" : "en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: true,
  }).format(new Date(iso));
}

/** Pick the right localized name: Bangla when locale=bn and a Bangla name exists. */
export function localizedName(
  nameEn: string | null | undefined,
  nameBn: string | null | undefined,
  locale: string,
): string {
  if (locale === "bn" && nameBn) return nameBn;
  return nameEn ?? nameBn ?? "";
}
