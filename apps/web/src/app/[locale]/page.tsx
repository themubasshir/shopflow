import { getTranslations } from "next-intl/server";
import {
  Banknote,
  Receipt,
  PackageX,
  Pill,
  ShoppingCart,
  Clock,
  User,
} from "lucide-react";
import { api } from "@/lib/api";
import { formatBDT, formatTime, localizedName } from "@/lib/format";
import { KpiCard } from "@/components/dashboard/kpi-card";
import { SalesChart } from "@/components/dashboard/sales-chart";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { Link } from "@/i18n/navigation";

export const dynamic = "force-dynamic";

export default async function DashboardPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "dashboard" });
  const tActions = await getTranslations({ locale, namespace: "actions" });
  const tCounters = await getTranslations({ locale, namespace: "counters" });
  const tStates = await getTranslations({ locale, namespace: "states" });
  const tInv = await getTranslations({ locale, namespace: "inventory" });
  const tApp = await getTranslations({ locale, namespace: "app" });

  let data;
  try {
    data = await api.dashboard();
  } catch {
    data = null;
  }

  const summary = data?.summary;

  return (
    <div className="space-y-4">
      {/* Page header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-[var(--color-ink)] sm:text-2xl">{t("title")}</h1>
          <p className="text-sm text-[var(--color-muted-foreground)]">{t("subtitle")}</p>
        </div>
        <div className="flex items-center gap-2">
          {summary?.is_demo ? <Badge variant="warning">{tApp("demoBadge")}</Badge> : null}
          <Link
            href="/billing"
            className="inline-flex min-h-[44px] items-center gap-2 rounded-lg bg-[var(--color-primary)] px-4 text-sm font-semibold text-white transition-colors duration-150 hover:bg-[var(--color-primary-strong)]"
          >
            <ShoppingCart className="h-4 w-4" aria-hidden="true" />
            {tActions("newBill")}
          </Link>
        </div>
      </div>

      {!data ? (
        <EmptyState title={tStates("error")} hint="API unreachable — start the backend on port 8001." />
      ) : (
        <>
          {/* KPI row */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
            <KpiCard
              title={t("todaySales")}
              value={formatBDT(summary!.today_sales)}
              icon={Banknote}
            />
            <KpiCard
              title={t("invoices")}
              value={String(summary!.invoice_count)}
              icon={Receipt}
            />
            <KpiCard
              title={t("averageBill")}
              value={formatBDT(summary!.average_bill)}
              icon={Banknote}
              iconBg="bg-sky-100 text-sky-700"
            />
            <KpiCard
              title={t("lowStock")}
              value={String(summary!.low_stock_count)}
              icon={PackageX}
              iconBg="bg-amber-100 text-amber-700"
            />
            <KpiCard
              title={t("expiringSoon")}
              value={String(summary!.expiring_soon_count)}
              icon={Pill}
              iconBg="bg-red-100 text-red-700"
            />
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            {/* Counter activity */}
            <Card>
              <CardHeader>
                <CardTitle>{t("counterActivity")}</CardTitle>
              </CardHeader>
              <ul className="space-y-3">
                {data.counters.map((c) => (
                  <li key={c.id} className="flex items-center gap-3">
                    <div
                      className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg font-bold ${
                        c.is_busy
                          ? "bg-[var(--color-primary-100)] text-[var(--color-primary-strong)]"
                          : "bg-[var(--color-muted)] text-[var(--color-muted-foreground)]"
                      }`}
                    >
                      {c.code}
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">
                        {localizedName(c.name_en, c.name_bn, locale)}
                      </p>
                      <p className="text-xs text-[var(--color-muted-foreground)]">
                        {c.invoice_count} {tCounters("invoices")}
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="text-sm font-semibold tabular-nums">{formatBDT(c.total_sales)}</p>
                      <Badge variant={c.is_busy ? "success" : "outline"}>
                        {c.is_busy ? tCounters("busy") : tCounters("idle")}
                      </Badge>
                    </div>
                  </li>
                ))}
              </ul>
            </Card>

            {/* Sales chart */}
            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle>{t("salesTrend")}</CardTitle>
              </CardHeader>
              {data.sales_series.length ? (
                <SalesChart data={data.sales_series} locale={locale} />
              ) : (
                <EmptyState title={tStates("empty")} hint={tStates("emptyHint")} />
              )}
            </Card>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            {/* Low stock */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <PackageX className="h-4 w-4 text-amber-600" aria-hidden="true" />
                  {t("lowStock")}
                </CardTitle>
                <Link href="/inventory" className="text-xs font-semibold text-[var(--color-primary)] hover:underline">
                  {tActions("viewAll")}
                </Link>
              </CardHeader>
              {data.low_stock.length ? (
                <ul className="divide-y divide-[var(--color-border)]">
                  {data.low_stock.slice(0, 5).map((item) => (
                    <li key={item.product_id} className="flex items-center justify-between gap-2 py-2">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium">
                          {localizedName(item.name_en, item.name_bn, locale)}
                        </p>
                        <p className="text-xs text-[var(--color-muted-foreground)]">{item.sku}</p>
                      </div>
                      <Badge variant="warning">
                        {item.stock_on_hand} / {item.low_stock_threshold}
                      </Badge>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState title={tStates("empty")} />
              )}
            </Card>

            {/* Expiring medicines */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Clock className="h-4 w-4 text-red-600" aria-hidden="true" />
                  {t("expiringSoon")}
                </CardTitle>
                <Link href="/inventory" className="text-xs font-semibold text-[var(--color-primary)] hover:underline">
                  {tActions("viewAll")}
                </Link>
              </CardHeader>
              {data.expiring.length ? (
                <ul className="divide-y divide-[var(--color-border)]">
                  {data.expiring.slice(0, 5).map((item) => (
                    <li key={item.batch_id} className="flex items-center justify-between gap-2 py-2">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium">
                          {localizedName(item.name_en, item.name_bn, locale)}
                        </p>
                        <p className="text-xs text-[var(--color-muted-foreground)]">
                          {tInv("batch")} {item.batch_number}
                        </p>
                      </div>
                      <Badge variant={item.days_to_expiry <= 30 ? "danger" : "warning"}>
                        {item.days_to_expiry} {tInv("days")}
                      </Badge>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState title={tStates("empty")} />
              )}
            </Card>
          </div>

          {/* Recent transactions */}
          <Card>
            <CardHeader>
              <CardTitle>{t("recentTransactions")}</CardTitle>
              <Link href="/reports" className="text-xs font-semibold text-[var(--color-primary)] hover:underline">
                {tActions("viewAll")}
              </Link>
            </CardHeader>
            {data.recent_transactions.length ? (
              <div className="table-scroll -mx-4 overflow-x-auto px-4">
                <table className="w-full min-w-[560px] text-left text-sm">
                  <thead>
                    <tr className="border-b border-[var(--color-border)] text-xs uppercase tracking-wide text-[var(--color-muted-foreground)]">
                      <th className="pb-2 pr-4 font-medium">#</th>
                      <th className="pb-2 pr-4 font-medium">{tCounters("counter")}</th>
                      <th className="pb-2 pr-4 font-medium"><User className="inline h-3 w-3" aria-hidden="true" /></th>
                      <th className="pb-2 pr-4 font-medium">{locale === "bn" ? "সময়" : "Time"}</th>
                      <th className="pb-2 pr-4 font-medium">{tInv("status")}</th>
                      <th className="pb-2 text-right font-medium">{tCounters("sales")}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--color-border)]">
                    {data.recent_transactions.map((tx) => (
                      <tr key={tx.id}>
                        <td className="py-2.5 pr-4 font-mono text-xs">{tx.invoice_number}</td>
                        <td className="py-2.5 pr-4">
                          <Badge variant="outline">{tx.counter_code}</Badge>
                        </td>
                        <td className="py-2.5 pr-4 text-xs text-[var(--color-muted-foreground)]">
                          {tx.customer_name ?? "Walk-in"}
                        </td>
                        <td className="py-2.5 pr-4 text-xs tabular-nums">
                          {formatTime(tx.finalized_at, locale)}
                        </td>
                        <td className="py-2.5 pr-4">
                          <Badge variant={tx.status === "finalized" ? "success" : "danger"}>
                            {tx.status}
                          </Badge>
                        </td>
                        <td className="py-2.5 text-right font-semibold tabular-nums">
                          {formatBDT(tx.total)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <EmptyState title={tStates("empty")} hint={tStates("emptyHint")} />
            )}
          </Card>
        </>
      )}
    </div>
  );
}
