import { getTranslations } from "next-intl/server";
import { Gift, Lock, Unlock } from "lucide-react";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";

export const dynamic = "force-dynamic";

export default async function LoyaltyPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "loyalty" });
  const tStates = await getTranslations({ locale, namespace: "states" });
  const tCust = await getTranslations({ locale, namespace: "customers" });

  const data = await api.loyaltyAccounts().catch(() => null);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold text-[var(--color-ink)] sm:text-2xl">{t("title")}</h1>
        <p className="text-sm text-[var(--color-muted-foreground)]">{t("subtitle")}</p>
      </div>

      <Card className="flex items-start gap-3 bg-[var(--color-primary-050)]">
        <Gift className="mt-0.5 h-5 w-5 shrink-0 text-[var(--color-primary)]" aria-hidden="true" />
        <p className="text-sm font-medium">{t("rule")}</p>
      </Card>

      {!data ? (
        <EmptyState title={tStates("error")} hint="API unreachable." />
      ) : data.items.length === 0 ? (
        <EmptyState title={tStates("empty")} hint={tStates("emptyHint")} />
      ) : (
        <Card className="p-0">
          <div className="table-scroll overflow-x-auto">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead>
                <tr className="border-b border-[var(--color-border)] bg-[var(--color-primary-050)] text-xs uppercase tracking-wide text-[var(--color-muted-foreground)]">
                  <th className="px-4 py-3 font-medium">{tCust("name")}</th>
                  <th className="px-4 py-3 font-medium">{tCust("phone")}</th>
                  <th className="px-4 py-3 text-right font-medium">{t("balance")}</th>
                  <th className="px-4 py-3 text-right font-medium">{t("earned")}</th>
                  <th className="px-4 py-3 text-right font-medium">{t("redeemed")}</th>
                  <th className="px-4 py-3 font-medium">{t("canRedeem")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--color-border)]">
                {data.items.map((a) => (
                  <tr key={a.customer_id} className="transition-colors duration-150 hover:bg-[var(--color-primary-050)]">
                    <td className="px-4 py-3 font-medium">{a.customer_name}</td>
                    <td className="px-4 py-3 text-xs text-[var(--color-muted-foreground)]">{a.phone ?? "—"}</td>
                    <td className="px-4 py-3 text-right font-bold tabular-nums">{a.points_balance}</td>
                    <td className="px-4 py-3 text-right tabular-nums">{a.lifetime_earned}</td>
                    <td className="px-4 py-3 text-right tabular-nums">{a.lifetime_redeemed}</td>
                    <td className="px-4 py-3">
                      {a.can_redeem ? (
                        <Badge variant="success"><Unlock className="h-3 w-3" aria-hidden="true" />{t("canRedeem")}</Badge>
                      ) : (
                        <Badge variant="outline"><Lock className="h-3 w-3" aria-hidden="true" />{t("locked")}</Badge>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
