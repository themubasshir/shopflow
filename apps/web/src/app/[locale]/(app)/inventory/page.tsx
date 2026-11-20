import { getTranslations } from "next-intl/server";
import { PackageSearch } from "lucide-react";
import { Link } from "@/i18n/navigation";
import { secondaryButton } from "@/components/ui/pos-form";
import { hasPermission, verifySession } from "@/lib/session";
import { api } from "@/lib/api";
import { formatBDT, formatQuantity, localizedName } from "@/lib/format";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";

export const dynamic = "force-dynamic";

export default async function InventoryPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "inventory" });
  const tStates = await getTranslations({ locale, namespace: "states" });

  const operations = await getTranslations({ locale, namespace: "inventoryOps" });
  const [products, categories, session] = await Promise.all([
    api.products({ limit: 100 }).catch(() => null),
    api.categories().catch(() => []),
    verifySession(),
  ]);

  const stockStatus = (p: { stock_on_hand: string; low_stock_threshold: string }) => {
    const stock = parseFloat(p.stock_on_hand);
    if (stock <= 0) return { label: t("outOfStock"), variant: "danger" as const };
    if (stock <= parseFloat(p.low_stock_threshold)) return { label: t("lowStock"), variant: "warning" as const };
    return { label: t("inStock"), variant: "success" as const };
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-[var(--color-ink)] sm:text-2xl">{t("title")}</h1>
          <p className="text-sm text-[var(--color-muted-foreground)]">{t("subtitle")}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {session && hasPermission(session.me, "reports:read") && <Link href="/inventory/operations" className={secondaryButton}>{operations("title")}</Link>}
          {categories.slice(0, 4).map((c) => (
            <Badge key={c.id} variant="outline">
              {localizedName(c.name_en, c.name_bn, locale)} ({c.product_count})
            </Badge>
          ))}
        </div>
      </div>

      {!products ? (
        <EmptyState title={tStates("error")} hint="API unreachable." />
      ) : products.items.length === 0 ? (
        <EmptyState title={tStates("empty")} hint={tStates("emptyHint")} />
      ) : (
        <Card className="p-0">
          <div className="table-scroll overflow-x-auto">
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead>
                <tr className="border-b border-[var(--color-border)] bg-[var(--color-primary-050)] text-xs uppercase tracking-wide text-[var(--color-muted-foreground)]">
                  <th className="px-4 py-3 font-medium">{t("product")}</th>
                  <th className="px-4 py-3 font-medium">{t("sku")}</th>
                  <th className="px-4 py-3 font-medium">{t("category")}</th>
                  <th className="px-4 py-3 font-medium">{t("stock")}</th>
                  <th className="px-4 py-3 font-medium">{t("price")}</th>
                  <th className="px-4 py-3 font-medium">{t("status")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--color-border)]">
                {products.items.map((p) => {
                  const status = stockStatus(p);
                  return (
                    <tr key={p.id} className="transition-colors duration-150 hover:bg-[var(--color-primary-050)]">
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <PackageSearch className="h-4 w-4 shrink-0 text-[var(--color-muted-foreground)]" aria-hidden="true" />
                          <div className="min-w-0">
                            <p className="truncate font-medium">{localizedName(p.name_en, p.name_bn, locale)}</p>
                            {p.barcode ? <p className="font-mono text-xs text-[var(--color-muted-foreground)]">{p.barcode}</p> : null}
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3 font-mono text-xs">{p.sku}</td>
                      <td className="px-4 py-3">
                        <Badge variant={p.is_medicine ? "success" : "default"}>
                          {p.is_medicine ? t("medicine") : t("grocery")}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 tabular-nums">
                        {formatQuantity(p.stock_on_hand, locale)} {p.unit}
                      </td>
                      <td className="px-4 py-3 font-semibold tabular-nums">{formatBDT(p.price, locale)}</td>
                      <td className="px-4 py-3">
                        <Badge variant={status.variant}>{status.label}</Badge>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
