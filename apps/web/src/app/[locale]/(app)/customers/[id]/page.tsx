import { getLocale, getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";
import { ArrowLeft, Gift, Wallet } from "lucide-react";
import { Link } from "@/i18n/navigation";
import { api, ApiError } from "@/lib/api";
import { formatBDT, formatDate, localizedName } from "@/lib/format";
import { hasPermission, verifySession } from "@/lib/session";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { secondaryButton } from "@/components/ui/pos-form";
import { CustomerForm } from "../customer-form";
import { DuePaymentForm } from "../due-payment-form";
import { Pager } from "../pager";

const tabs = ["invoices", "payments", "statement", "loyalty"] as const;

export default async function CustomerPage({ params, searchParams }: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ tab?: string; offset?: string }>;
}) {
  const [{ id }, filters, locale, t, session] = await Promise.all([
    params, searchParams, getLocale(), getTranslations("customers"), verifySession(),
  ]);
  if (!/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(id)) notFound();
  const me = session?.me;
  const history = Boolean(me && me.assigned_counter_ids === null && hasPermission(me, "reports:read"));
  const hasSales = Boolean(me && hasPermission(me, "sales:read"));
  const hasLoyalty = Boolean(me && hasPermission(me, "loyalty:read"));
  const canCollect = Boolean(me && history && hasPermission(me, "sales:write"));
  const canEdit = Boolean(me && hasPermission(me, "customers:write"));
  const available = tabs.filter((tab) => history && (tab === "loyalty" ? hasLoyalty : tab === "invoices" ? hasSales : true));
  const tab = available.find((option) => option === filters.tab) ?? available[0];
  const offset = /^\d{1,9}$/.test(filters.offset ?? "") ? Number(filters.offset) : 0;
  const [customer, balance, loyalty] = await Promise.all([
    api.customer(id).catch((error) => {
      if (error instanceof ApiError && error.status === 404) notFound();
      throw error;
    }),
    history ? api.customerBalance(id) : null,
    hasLoyalty ? api.customerLoyalty(id) : null,
  ]);
  const detailPath = `/customers/${customer.id}`;
  const name = localizedName(customer.name, customer.name_bn, locale);
  const otherName = locale === "bn" && customer.name_bn ? customer.name : customer.name_bn;
  const transactions = tab === "invoices" ? await api.customerInvoices(id, offset)
    : tab === "payments" ? await api.customerPayments(id, offset)
    : tab === "statement" ? await api.customerStatement(id, offset)
    : tab === "loyalty" ? await api.customerLoyaltyHistory(id, offset) : null;

  return (
    <div className="space-y-4">
      <Link href="/customers" className={secondaryButton}><ArrowLeft size={16} aria-hidden="true" />{t("title")}</Link>
      <Card className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="break-words text-xl font-bold sm:text-2xl">{name}</h1>
            <Badge variant={customer.is_active ? "success" : "outline"}>{t(customer.is_active ? "active" : "inactive")}</Badge>
          </div>
          {otherName && otherName !== name && <p className="break-words text-sm">{otherName}</p>}
          <p className="break-words text-sm text-[var(--color-muted-foreground)]">{[customer.phone, customer.email].filter(Boolean).join(" · ") || "—"}</p>
        </div>
        {canEdit && <CustomerForm key={customer.id + customer.name + customer.is_active} customer={customer} />}
      </Card>
      <div className="grid gap-3 sm:grid-cols-2">
        {loyalty && <Card>
          <p className="flex items-center gap-2 text-sm font-medium"><Gift size={18} aria-hidden="true" />{t("pointsBalance")}</p>
          <p className="my-2 text-2xl font-bold tabular-nums">{t("pointCount", { count: loyalty.points_balance })}</p>
          <Badge variant={loyalty.can_redeem ? "success" : "outline"}>{t(loyalty.can_redeem ? "redeemReady" : "redeemLocked")}</Badge>
        </Card>}
        {balance && <Card>
          <p className="flex items-center gap-2 text-sm font-medium"><Wallet size={18} aria-hidden="true" />{t("outstanding")}</p>
          <p className="my-2 text-2xl font-bold tabular-nums">{formatBDT(balance.outstanding_due)}</p>
          <p className="text-sm text-[var(--color-muted-foreground)]">{t("creditLimit")} · {Number(customer.credit_limit) > 0 ? formatBDT(customer.credit_limit) : t("unlimited")}</p>
        </Card>}
      </div>
      {tab && transactions && (
        <section aria-label={t(`tabs.${tab}`)} className="space-y-3">
          <nav className="flex flex-wrap gap-2" aria-label={t("account")}>
            {available.map((key) => (
              <Link key={key} href={{ pathname: detailPath, query: { tab: key } }} aria-current={tab === key ? "page" : undefined}
                className={`${secondaryButton} aria-[current=page]:border-[var(--color-primary)] aria-[current=page]:bg-[var(--color-primary-100)]`}>
                {t(`tabs.${key}`)}
              </Link>
            ))}
          </nav>
          {transactions.items.length === 0 && <EmptyState title={t("noTransactions")} />}
          <ul className="space-y-2">
            {transactions.items.map((row) => (
              <li key={row.id}>
                <Card className="space-y-2">
                  <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1">
                    <div className="min-w-0">
                      <p className="break-words font-semibold">{row.invoice_number ?? "—"}</p>
                      <p className="text-sm text-[var(--color-muted-foreground)]">
                        {formatDate("paid_at" in row ? row.paid_at : row.created_at, locale)}
                      </p>
                    </div>
                    {"payment_status" in row ? (
                      <Badge variant={row.status !== "finalized" ? "outline" : row.payment_status === "paid" ? "success" : "warning"}>
                        {row.status === "finalized" ? t(`paymentStatus.${row.payment_status}`) : t.has(`invoiceStatus.${row.status}`) ? t(`invoiceStatus.${row.status}`) : row.status}
                      </Badge>
                    ) : "transaction_type" in row ? (
                      <Badge variant={row.points > 0 ? "success" : "outline"}>
                        {t.has(`loyaltyTypes.${row.transaction_type}`) ? t(`loyaltyTypes.${row.transaction_type}`) : row.transaction_type}
                      </Badge>
                    ) : (
                      <p className="text-sm font-semibold tabular-nums">{formatBDT(row.amount)}</p>
                    )}
                  </div>
                  {"payment_status" in row ? (
                    <>
                      <p className="flex flex-wrap gap-x-4 gap-y-1 text-sm tabular-nums">
                        <span>{t("total")} · {formatBDT(row.total)}</span>
                        <span>{t("paid")} · {formatBDT(row.paid_total)}</span>
                        <span>{t("due")} · {formatBDT(row.due_total)}</span>
                      </p>
                      {canCollect && row.status === "finalized" && <DuePaymentForm customerId={id} invoice={row} />}
                    </>
                  ) : "method" in row ? (
                    <p className="break-words text-sm">{t.has(`methods.${row.method}`) ? t(`methods.${row.method}`) : row.method}{row.reference ? ` · ${row.reference}` : ""}</p>
                  ) : "transaction_type" in row ? (
                    <p className="text-sm tabular-nums">{row.points > 0 ? "+" : ""}{row.points} · {t("pointsBalance")} {row.balance_after}</p>
                  ) : (
                    <p className="text-sm tabular-nums">{t(row.payment_id ? "collectionEntry" : "chargeEntry")} · {t("outstanding")} {formatBDT(row.balance_after)}</p>
                  )}
                </Card>
              </li>
            ))}
          </ul>
          <Pager path={detailPath} query={{ tab }} offset={offset} limit={transactions.limit} total={transactions.total} />
        </section>
      )}
    </div>
  );
}
