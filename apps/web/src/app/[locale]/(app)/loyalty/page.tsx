import { getLocale, getTranslations } from "next-intl/server";
import { Gift, Lock, Unlock } from "lucide-react";
import { api } from "@/lib/api";
import { Link } from "@/i18n/navigation";
import { localizedName } from "@/lib/format";
import { verifySession, hasPermission } from "@/lib/session";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { secondaryButton } from "@/components/ui/pos-form";
import { Pager } from "../customers/pager";

export default async function LoyaltyPage({ searchParams }: { searchParams: Promise<{ offset?: string }> }) {
  const [locale, t, states, customer, session, query] = await Promise.all([
    getLocale(), getTranslations("loyalty"), getTranslations("states"),
    getTranslations("customers"), verifySession(), searchParams,
  ]);
  const offset = /^\d{1,9}$/.test(query.offset ?? "") ? Number(query.offset) : 0;
  const data = await api.loyaltyAccounts(offset).catch(() => null);
  const fullHistory = session && session.me.assigned_counter_ids === null && hasPermission(session.me, "reports:read");

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold sm:text-2xl">{t("title")}</h1>
        <p className="text-sm text-[var(--color-muted-foreground)]">{t("subtitle")}</p>
      </div>
      <Card className="flex items-start gap-3 bg-[var(--color-primary-050)]">
        <Gift className="mt-0.5 size-5 shrink-0 text-[var(--color-primary)]" aria-hidden="true" />
        <p className="text-sm font-medium">{t("rule")}</p>
      </Card>
      {!data ? (
        <EmptyState title={states("error")} hint={customer("errors.unknown")} />
      ) : data.items.length === 0 ? (
        <EmptyState title={states("empty")} hint={states("emptyHint")} />
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {data.items.map((account) => (
            <li key={account.customer_id}>
              <Card className="h-full space-y-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="break-words font-bold">{localizedName(account.customer_name, account.customer_name_bn, locale)}</p>
                    <p className="text-sm text-[var(--color-muted-foreground)]">{account.phone ?? "—"}</p>
                  </div>
                  <Badge variant={account.can_redeem ? "success" : "outline"}>
                    {account.can_redeem ? <Unlock size={13} aria-hidden="true" /> : <Lock size={13} aria-hidden="true" />}
                    {t(account.can_redeem ? "canRedeem" : "locked")}
                  </Badge>
                </div>
                <dl className="space-y-1 text-sm tabular-nums">
                  <div className="flex justify-between gap-2 font-semibold"><dt>{t("balance")}</dt><dd>{account.points_balance}</dd></div>
                  {fullHistory && <>
                    <div className="flex justify-between gap-2"><dt>{t("earned")}</dt><dd>{account.lifetime_earned}</dd></div>
                    <div className="flex justify-between gap-2"><dt>{t("redeemed")}</dt><dd>{account.lifetime_redeemed}</dd></div>
                  </>}
                </dl>
                {fullHistory && (
                  <Link className={secondaryButton} href={{ pathname: `/customers/${account.customer_id}`, query: { tab: "loyalty" } }}>
                    {t("viewHistory")}
                  </Link>
                )}
              </Card>
            </li>
          ))}
        </ul>
      )}
      {data && <Pager path="/loyalty" query={{}} offset={offset} limit={data.limit} total={data.total} />}
    </div>
  );
}
