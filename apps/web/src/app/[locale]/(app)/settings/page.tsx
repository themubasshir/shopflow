import { getTranslations } from "next-intl/server";
import { Store, MonitorSmartphone, Globe, Printer, Users } from "lucide-react";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { LanguageSwitcher } from "@/components/layout/language-switcher";
import { verifySession, hasPermission } from "@/lib/session";
import { ReceiptSettingsEditor } from "./receipt-settings";
import { api } from "@/lib/api";
import type { Locale } from "@/i18n/config";

export const dynamic = "force-dynamic";

export default async function SettingsPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "settings" });
  const tApp = await getTranslations({ locale, namespace: "app" });

  const tReceipt = await getTranslations({ locale, namespace: "receipts" });
  const [dashboard, session] = await Promise.all([api.dashboard().catch(() => null), verifySession()]);
  const canEditReceipt = session?.me.role === "owner" && hasPermission(session.me, "settings:write");
  const receipt = canEditReceipt ? await api.receiptSettings().catch(() => null) : null;

  const rows = [
    { icon: Store, label: t("shop"), value: `${tApp("name")} · ${tApp("tagline")}` },
    { icon: MonitorSmartphone, label: t("counters"), value: dashboard ? `${dashboard.summary.active_counters} active` : "3" },
    { icon: Globe, label: t("timezone"), value: "Asia/Dhaka (UTC+6)" },
    { icon: Printer, label: t("receipt"), value: "80mm thermal · BDT ৳" },
    { icon: Users, label: t("users"), value: "Manager · 2 cashiers" },
  ];

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold text-[var(--color-ink)] sm:text-2xl">{t("title")}</h1>
        <p className="text-sm text-[var(--color-muted-foreground)]">{t("subtitle")}</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>{t("language")}</CardTitle>
          <LanguageSwitcher locale={locale as Locale} />
        </CardHeader>
        <ul className="divide-y divide-[var(--color-border)]">
          {rows.map((row) => (
            <li key={row.label} className="flex items-center gap-3 py-3">
              <row.icon className="h-5 w-5 shrink-0 text-[var(--color-muted-foreground)]" aria-hidden="true" />
              <div className="min-w-0 flex-1">
                <p className="text-xs font-medium uppercase tracking-wide text-[var(--color-muted-foreground)]">{row.label}</p>
                <p className="truncate text-sm font-medium">{row.value}</p>
              </div>
            </li>
          ))}
        </ul>
      </Card>

      <Card className="bg-[var(--color-primary-050)]">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-sm font-semibold">{t("currency")}</p>
            <p className="text-xs text-[var(--color-muted-foreground)]">Bangladeshi Taka · NUMERIC storage · Latin digits</p>
          </div>
          <Badge variant="success">BDT ৳</Badge>
        </div>
      </Card>
      {canEditReceipt && (receipt ? <ReceiptSettingsEditor settings={receipt} /> : <p role="alert">{tReceipt("loadError")}</p>)}
    </div>
  );
}
