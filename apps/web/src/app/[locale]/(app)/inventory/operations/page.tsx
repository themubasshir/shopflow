import { ArrowLeft } from "lucide-react";
import { getTranslations } from "next-intl/server";
import { secondaryButton } from "@/components/ui/pos-form";
import { EmptyState } from "@/components/ui/empty-state";
import { Link } from "@/i18n/navigation";
import { api } from "@/lib/api";
import { hasPermission, verifySession } from "@/lib/session";
import { Operations } from "./operations";

export default async function OperationsPage() {
  const [t, session] = await Promise.all([getTranslations("inventoryOps"), verifySession()]);
  if (!session || !hasPermission(session.me, "reports:read")) return <EmptyState title={t("forbidden")} />;
  const products = await api.products({ limit: 40 }).catch(() => null);
  return (
    <div className="space-y-4">
      <Link className={secondaryButton} href="/inventory"><ArrowLeft size={16} aria-hidden="true" />{t("back")}</Link>
      <h1 className="text-xl font-bold sm:text-2xl">{t("title")}</h1>
      <Operations canWrite={hasPermission(session.me, "catalog:write")} initialProducts={products?.items ?? []} />
    </div>
  );
}
