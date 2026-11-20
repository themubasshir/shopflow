const bdtFormatter = new Intl.NumberFormat("en", {
  minimumFractionDigits: 0,
  maximumFractionDigits: 2,
});

const numberFormatter = new Intl.NumberFormat("en-BD", {
  maximumFractionDigits: 2,
});

const quantityFormatter = new Intl.NumberFormat("en-BD", {
  maximumFractionDigits: 3,
});

const bnNumberFormatter = new Intl.NumberFormat("bn-BD", {
  maximumFractionDigits: 2,
});

const bnQuantityFormatter = new Intl.NumberFormat("bn-BD", {
  maximumFractionDigits: 3,
});

const bnBdtFormatter = new Intl.NumberFormat("bn-BD", {
  minimumFractionDigits: 0,
  maximumFractionDigits: 2,
});

/**
 * Convert Latin digits in a formatted string to Bengali digits. Used when the
 * UI locale is Bangla so amounts like ৳25 render as ৳২৫.
 */
export function bengaliDigits(value: string): string {
  return value.replace(/[0-9]/g, (d) => "০১২৩৪৫৬৭৮৯"[Number(d)]);
}

function isBn(locale?: string): boolean {
  return locale === "bn";
}

/** Format a Decimal string from the API as BDT. Bangla locale ⇒ Bengali digits. */
export function formatBDT(
  value: string | number | null | undefined,
  locale = "en",
): string {
  if (value == null || value === "") return isBn(locale) ? "৳০" : "৳0";
  const n = typeof value === "string" ? parseFloat(value) : value;
  if (Number.isNaN(n)) return isBn(locale) ? "৳০" : "৳0";
  return isBn(locale)
    ? `৳${bnBdtFormatter.format(n)}`
    : `৳${bdtFormatter.format(n)}`;
}

export function formatNumber(
  value: string | number | null | undefined,
  locale = "en",
): string {
  if (value == null || value === "") return isBn(locale) ? "০" : "0";
  const n = typeof value === "string" ? parseFloat(value) : value;
  return (isBn(locale) ? bnNumberFormatter : numberFormatter).format(
    Number.isNaN(n) ? 0 : n,
  );
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

export function formatQuantity(value: string | number, locale = "en"): string {
  return (isBn(locale) ? bnQuantityFormatter : quantityFormatter).format(
    Number(value),
  );
}
