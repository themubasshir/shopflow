import { getLocale, getTranslations } from "next-intl/server";
import { Search, UserRound } from "lucide-react";
import { Link } from "@/i18n/navigation";
import { api } from "@/lib/api";
import { hasPermission, verifySession } from "@/lib/session";
import { localizedName } from "@/lib/format";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { fieldClass, primaryButton } from "@/components/ui/pos-form";
import { CustomerForm } from "./customer-form";
import { Pager } from "./pager";

export default async function CustomersPage({ searchParams }: {
  searchParams: Promise<{ q?: string; active?: string; offset?: string }>;
}) {
  const [locale, t, states, filters, session] = await Promise.all([
    getLocale(), getTranslations("customers"), getTranslations("states"), searchParams, verifySession(),
  ]);
  const q = typeof filters.q === "string" ? filters.q.trim().slice(0, 160) : "";
  const active = filters.active === "true" || filters.active === "false" ? filters.active : "";
  const offset = /^\d{1,9}$/.test(filters.offset ?? "") ? Number(filters.offset) : 0;
  const query = new URLSearchParams({ q, limit: "24", offset: String(offset) });
  if (active) query.set("active", active);
  const data = await api.customers(query).catch(() => null);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold sm:text-2xl">{t("title")}</h1>
          <p className="text-sm text-[var(--color-muted-foreground)]">{t("subtitle")}</p>
        </div>
        {session && hasPermission(session.me, "customers:write") && <CustomerForm />}
      </div>
      <Card>
        <form method="get" className="grid items-end gap-3 sm:grid-cols-[minmax(0,1fr)_10rem_auto]">
          <label className="space-y-1 text-sm font-medium">
            <span>{t("search")}</span>
            <input type="search" name="q" maxLength={160} defaultValue={q} className={fieldClass} />
          </label>
          <label className="space-y-1 text-sm font-medium">
            <span>{t("status")}</span>
            <select name="active" defaultValue={active} className={fieldClass}>
              <option value="">{t("all")}</option>
              <option value="true">{t("active")}</option>
              <option value="false">{t("inactive")}</option>
            </select>
          </label>
          <button className={primaryButton}><Search size={17} aria-hidden="true" />{t("find")}</button>
        </form>
      </Card>
      {!data ? (
        <EmptyState title={states("error")} hint={t("errors.unknown")} />
      ) : (
        <>
          {!data.items.length && <EmptyState title={t("noCustomers")} hint={t("searchHint")} />}
          <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {data.items.map((customer) => (
              <li key={customer.id}>
                <Link href={`/customers/${customer.id}`} className="block rounded-xl hover:bg-[var(--color-primary-050)]">
                  <Card className="flex h-full items-start gap-3 transition-colors hover:bg-[var(--color-primary-050)]">
                    <span className="flex size-11 shrink-0 items-center justify-center rounded-full bg-[var(--color-primary-100)] text-[var(--color-primary)]">
                      <UserRound size={21} aria-hidden="true" />
                    </span>
                    <div className="min-w-0">
                      <p className="break-words font-semibold">{localizedName(customer.name, customer.name_bn, locale)}</p>
                      <p className="text-sm text-[var(--color-muted-foreground)]">{customer.phone ?? "—"}</p>
                      <div className="mt-2 flex flex-wrap gap-2">
                        <Badge variant={customer.is_active ? "success" : "outline"}>{t(customer.is_active ? "active" : "inactive")}</Badge>
                        <Badge variant="outline">{t("pointCount", { count: customer.points_balance })}</Badge>
                      </div>
                    </div>
                  </Card>
                </Link>
              </li>
            ))}
          </ul>
          <Pager path="/customers" query={{ q, active }} offset={offset} limit={data.limit} total={data.total} />
        </>
      )}
    </div>
  );
}
