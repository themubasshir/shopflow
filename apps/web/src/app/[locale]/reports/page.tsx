import { getTranslations } from "next-intl/server";
import { api } from "@/lib/api";
import { formatBDT, formatDate, formatTime } from "@/lib/format";
import { SalesChart } from "@/components/dashboard/sales-chart";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";

export const dynamic = "force-dynamic";

export default async function ReportsPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "reports" });
  const tStates = await getTranslations({ locale, namespace: "states" });
  const tCounters = await getTranslations({ locale, namespace: "counters" });

  const data = await api.dashboard().catch(() => null);

  const methodTotal = (method: string) =>
    data?.recent_transactions.filter((tx) => tx.method === method).length ?? 0;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold text-[var(--color-ink)] sm:text-2xl">{t("title")}</h1>
        <p className="text-sm text-[var(--color-muted-foreground)]">{t("subtitle")}</p>
      </div>

      {!data ? (
        <EmptyState title={tStates("error")} hint="API unreachable." />
      ) : (
        <>
          <div className="grid grid-cols-3 gap-3">
            {(["cash", "bkash", "nagad"] as const).map((m) => (
              <Card key={m}>
                <p className="text-xs font-medium uppercase tracking-wide text-[var(--color-muted-foreground)]">
                  {t(m)}
                </p>
                <p className="text-2xl font-bold tabular-nums">{methodTotal(m)}</p>
                <p className="text-xs text-[var(--color-muted-foreground)]">{t("invoices")}</p>
              </Card>
            ))}
          </div>

          <Card>
            <CardHeader>
              <CardTitle>{t("daily")} {t("sales")}</CardTitle>
            </CardHeader>
            {data.sales_series.length ? (
              <SalesChart data={data.sales_series} locale={locale} />
            ) : (
              <EmptyState title={tStates("empty")} hint={tStates("emptyHint")} />
            )}
          </Card>

          <Card className="p-0">
            <div className="table-scroll overflow-x-auto">
              <table className="w-full min-w-[640px] text-left text-sm">
                <thead>
                  <tr className="border-b border-[var(--color-border)] bg-[var(--color-primary-050)] text-xs uppercase tracking-wide text-[var(--color-muted-foreground)]">
                    <th className="px-4 py-3 font-medium">{t("date")}</th>
                    <th className="px-4 py-3 font-medium">#</th>
                    <th className="px-4 py-3 font-medium">{tCounters("counter")}</th>
                    <th className="px-4 py-3 font-medium">{t("method")}</th>
                    <th className="px-4 py-3 text-right font-medium">{t("sales")}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--color-border)]">
                  {data.recent_transactions.map((tx) => (
                    <tr key={tx.id} className="transition-colors duration-150 hover:bg-[var(--color-primary-050)]">
                      <td className="px-4 py-3 text-xs tabular-nums">
                        {formatDate(tx.finalized_at, locale)} · {formatTime(tx.finalized_at, locale)}
                      </td>
                      <td className="px-4 py-3 font-mono text-xs">{tx.invoice_number}</td>
                      <td className="px-4 py-3"><Badge variant="outline">{tx.counter_code}</Badge></td>
                      <td className="px-4 py-3">
                        {tx.method ? (
                          <Badge variant={tx.method === "cash" ? "success" : "default"}>
                            {t(tx.method as "cash" | "bkash" | "nagad")}
                          </Badge>
                        ) : "—"}
                      </td>
                      <td className="px-4 py-3 text-right font-semibold tabular-nums">{formatBDT(tx.total)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </div>
  );
}
