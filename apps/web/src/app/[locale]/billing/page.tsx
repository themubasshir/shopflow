import { getTranslations } from "next-intl/server";
import { Search, User } from "lucide-react";
import { api } from "@/lib/api";
import { formatBDT, localizedName } from "@/lib/format";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";

export const dynamic = "force-dynamic";

export default async function BillingPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "billing" });
  const tStates = await getTranslations({ locale, namespace: "states" });

  const products = await api.products({ limit: 24 }).catch(() => null);

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <div className="lg:col-span-2">
        <div className="mb-4">
          <h1 className="text-xl font-bold text-[var(--color-ink)] sm:text-2xl">{t("title")}</h1>
          <p className="text-sm text-[var(--color-muted-foreground)]">{t("subtitle")}</p>
        </div>
        <label className="mb-4 flex min-h-[52px] items-center gap-3 rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] px-4">
          <Search className="h-5 w-5 text-[var(--color-muted-foreground)]" aria-hidden="true" />
          <input
            type="search"
            placeholder={t("searchProducts")}
            aria-label={t("searchProducts")}
            className="w-full bg-transparent text-base outline-none placeholder:text-[var(--color-muted-foreground)]"
          />
        </label>
        {products?.items.length ? (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4">
            {products.items.map((p) => (
              <button
                key={p.id}
                type="button"
                disabled={parseFloat(p.stock_on_hand) <= 0}
                className="min-h-[96px] rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] p-3 text-left transition-colors duration-150 hover:border-[var(--color-primary)] hover:bg-[var(--color-primary-050)] disabled:opacity-50"
              >
                <p className="line-clamp-2 text-sm font-semibold">
                  {localizedName(p.name_en, p.name_bn, locale)}
                </p>
                <p className="mt-1 text-xs text-[var(--color-muted-foreground)]">{p.sku}</p>
                <p className="mt-1 text-base font-bold text-[var(--color-primary)]">
                  {formatBDT(p.price)}
                </p>
              </button>
            ))}
          </div>
        ) : (
          <EmptyState title={tStates("empty")} hint={tStates("emptyHint")} />
        )}
      </div>

      <Card className="h-fit lg:sticky lg:top-20">
        <CardHeader>
          <CardTitle>{t("cart")}</CardTitle>
          <Badge variant="outline">0 items</Badge>
        </CardHeader>
        <div className="mb-3 flex items-center gap-2 rounded-lg border border-dashed border-[var(--color-border)] px-3 py-2">
          <User className="h-4 w-4 text-[var(--color-muted-foreground)]" aria-hidden="true" />
          <span className="text-sm text-[var(--color-muted-foreground)]">{t("walkIn")}</span>
        </div>
        <EmptyState title={t("emptyCart")} hint={t("comingSoon")} />
        <dl className="mt-4 space-y-2 border-t border-[var(--color-border)] pt-4 text-sm">
          <div className="flex justify-between"><dt>{t("subtotal")}</dt><dd className="tabular-nums">{formatBDT(0)}</dd></div>
          <div className="flex justify-between"><dt>{t("discount")}</dt><dd className="tabular-nums">{formatBDT(0)}</dd></div>
          <div className="flex justify-between text-base font-bold"><dt>{t("total")}</dt><dd className="tabular-nums text-[var(--color-primary)]">{formatBDT(0)}</dd></div>
        </dl>
        <div className="mt-4 grid grid-cols-3 gap-2">
          {[t("payCash"), t("payBkash"), t("payNagad")].map((m) => (
            <button
              key={m}
              type="button"
              className="min-h-[44px] rounded-lg border border-[var(--color-border)] text-xs font-semibold transition-colors duration-150 hover:bg-[var(--color-primary-100)]"
            >
              {m}
            </button>
          ))}
        </div>
        <button
          type="button"
          disabled
          className="mt-3 min-h-[52px] w-full rounded-xl bg-[var(--color-primary)] text-base font-bold text-white transition-colors duration-150 hover:bg-[var(--color-primary-strong)] disabled:opacity-50"
        >
          {t("finalize")}
        </button>
      </Card>
    </div>
  );
}
