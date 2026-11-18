import { getLocale } from "next-intl/server";
import { api } from "@/lib/api";
import { BillingClient } from "./billing-client";
import type { Locale } from "@/i18n/config";

export const dynamic = "force-dynamic";

/**
 * Billing screen: a server component that loads the product catalog, counters
 * and customers once, then hands interactive state to a client cart. The route
 * group already gates auth, so the cart always renders.
 */
export default async function BillingPage() {
  const locale = await getLocale();
  const [products, counters, customers] = await Promise.all([
    api.products({ limit: 100 }).catch(() => null),
    api.counters().catch(() => null),
    api.customers().catch(() => null),
  ]);

  return (
    <BillingClient
      locale={locale as Locale}
      products={products?.items ?? []}
      counters={counters ?? []}
      customers={customers?.items ?? []}
    />
  );
}
