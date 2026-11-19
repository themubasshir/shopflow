import { getTranslations } from "next-intl/server";
import { Skeleton } from "@/components/ui/skeleton";

export default async function InvoiceLoading() {
  const t = await getTranslations("receipts");
  return <div role="status" className="space-y-3">
    <p className="sr-only">{t("loading")}</p>
    <Skeleton className="h-14 w-full" />
    <Skeleton className="mx-auto h-72 max-w-[80mm]" />
  </div>;
}
