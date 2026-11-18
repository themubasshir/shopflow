import { getLocale } from "next-intl/server";
import { api } from "@/lib/api";
import { readSessionToken } from "@/lib/session";
import { BillingClient } from "./billing-client";
import type { Locale } from "@/i18n/config";

export const dynamic = "force-dynamic";

/**
 * Billing screen: a server component that loads the product catalog, counters
 * and customers once, then hands interactive state to a client cart. The JWT
 * session is checked here so the cart never renders a dead-end form.
 */
export default async function BillingPage() {
  const [locale, token] = await Promise.all([getLocale(), readSessionToken()]);
  const [products, counters, customers] = await Promise.all([
    api.products({ limit: 100 }).catch(() => null),
    api.counters().catch(() => null),
    api.customers().catch(() => null),
  ]);

  return (
    <BillingClient
      locale={locale as Locale}
      signedIn={Boolean(token)}
      products={products?.items ?? []}
      counters={counters ?? []}
      customers={customers?.items ?? []}
    />
  );
}
