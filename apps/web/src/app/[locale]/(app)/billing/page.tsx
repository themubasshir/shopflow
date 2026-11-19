import { getLocale } from "next-intl/server";
import { verifySession } from "@/lib/session";
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
  const [products, counters, customers, session] = await Promise.all([
    api.products({ limit: 100 }).catch(() => null),
    api.counters().catch(() => null),
    api.customers(new URLSearchParams({ active: "true", limit: "30" })).catch(() => null),
    verifySession(),
  ]);

  return (
    <BillingClient
      locale={locale as Locale}
      products={products?.items ?? []}
      counters={(counters ?? []).filter((c) => !session?.me.assigned_counter_ids || session.me.assigned_counter_ids.includes(c.id))}
      canRedeem={session?.me.permissions.includes("loyalty:write") ?? false}
      customers={customers?.items ?? []}
    />
  );
}
