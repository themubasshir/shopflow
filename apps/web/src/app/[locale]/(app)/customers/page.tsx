import { getTranslations } from "next-intl/server";
import { Users } from "lucide-react";
import { api } from "@/lib/api";
import { formatBDT } from "@/lib/format";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";

export const dynamic = "force-dynamic";

export default async function CustomersPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "customers" });
  const tStates = await getTranslations({ locale, namespace: "states" });

  const data = await api.customers().catch(() => null);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold text-[var(--color-ink)] sm:text-2xl">{t("title")}</h1>
        <p className="text-sm text-[var(--color-muted-foreground)]">{t("subtitle")}</p>
      </div>

      {!data ? (
        <EmptyState title={tStates("error")} hint="API unreachable." />
      ) : data.items.length === 0 ? (
        <EmptyState title={tStates("empty")} hint={tStates("emptyHint")} />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {data.items.map((c) => (
            <Card key={c.id} className="flex items-start gap-3">
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-[var(--color-primary-100)] text-[var(--color-primary)]">
                <Users className="h-5 w-5" aria-hidden="true" />
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate font-semibold">{c.name}</p>
                <p className="truncate text-xs text-[var(--color-muted-foreground)]">
                  {c.phone ?? "—"}
                </p>
                <div className="mt-2 flex flex-wrap gap-2">
                  <Badge variant="success">{c.points_balance} pts</Badge>
                  {parseFloat(c.credit_limit) > 0 ? (
                    <Badge variant="outline">{t("creditLimit")} {formatBDT(c.credit_limit)}</Badge>
                  ) : null}
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
