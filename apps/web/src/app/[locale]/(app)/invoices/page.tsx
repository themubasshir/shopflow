import { getLocale, getTranslations } from "next-intl/server";
import { ArrowLeft, Download, Printer, Search } from "lucide-react";
import { Link } from "@/i18n/navigation";
import { api } from "@/lib/api";
import { formatBDT, formatDate } from "@/lib/format";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { fieldClass, primaryButton, secondaryButton } from "@/components/ui/pos-form";
import { Card } from "@/components/ui/card";
import { Pager } from "../customers/pager";

export default async function InvoiceHistory({ searchParams }: {
  searchParams: Promise<{ q?: string; offset?: string }>;
}) {
  const [t, customer, locale, params] = await Promise.all([
    getTranslations("receipts"), getTranslations("customers"), getLocale(), searchParams,
  ]);
  const query = typeof params.q === "string" ? params.q.trim().slice(0, 40) : "";
  const offset = /^\d{1,9}$/.test(params.offset ?? "") ? Number(params.offset) : 0;
  const data = await api.invoices(new URLSearchParams({
    q: query, offset: String(offset), limit: "24", printable: "true",
  })).catch(() => null);

  return (
    <div className="space-y-4">
      <Link href="/billing" className={secondaryButton}><ArrowLeft size={16} aria-hidden="true" />{t("backBilling")}</Link>
      <h1 className="text-xl font-bold sm:text-2xl">{t("history")}</h1>
      <Card>
        <form method="get" className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
          <label className="grid gap-1 text-sm font-medium">
            {t("searchInvoice")}
            <input type="search" name="q" defaultValue={query} maxLength={40} className={fieldClass} />
          </label>
          <button className={primaryButton}><Search size={16} aria-hidden="true" />{customer("find")}</button>
        </form>
      </Card>
      {!data ? <EmptyState title={t("loadError")} /> : !data.items.length ? <EmptyState title={t("empty")} /> : (
        <ul className="grid gap-3 lg:grid-cols-2">
          {data.items.map((invoice) => (
            <li key={invoice.id}>
              <Card className="flex h-full flex-wrap items-center justify-between gap-3">
                <div className="min-w-0 space-y-1">
                  <p className="font-semibold">{invoice.invoice_number}</p>
                  <p className="text-sm text-[var(--color-muted-foreground)]">{formatDate(invoice.finalized_at ?? invoice.created_at, locale)} · {invoice.counter_code}</p>
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <strong>{formatBDT(invoice.total, locale)}</strong>
                    <Badge variant={invoice.status === "finalized" && invoice.payment_status === "paid" ? "success" : "warning"}>
                      {invoice.status === "finalized" ? customer("paymentStatus." + invoice.payment_status) : t("status." + invoice.status)}
                    </Badge>
                  </div>
                </div>
                <div className="flex shrink-0 flex-wrap items-center gap-2">
                  <a
                    href={`/api/invoices/${invoice.id}/receipt?format=pdf&lang=${locale}`}
                    download
                    className={secondaryButton}
                    aria-label={t("download")}
                  >
                    <Download size={16} aria-hidden="true" />{t("download")}
                  </a>
                  <Link href={`/invoices/${invoice.id}`} className={secondaryButton}>
                    <Printer size={16} aria-hidden="true" />{t("preview")}
                  </Link>
                </div>
              </Card>
            </li>
          ))}
        </ul>
      )}
      {data && <Pager path="/invoices" query={{ q: query }} offset={offset} limit={data.limit} total={data.total} />}
    </div>
  );
}
