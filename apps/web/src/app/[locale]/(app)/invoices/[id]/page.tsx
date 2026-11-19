import { getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { Link } from "@/i18n/navigation";
import { api, ApiError } from "@/lib/api";
import { receiptLanguage } from "@/lib/receipt/paper";
import { EmptyState } from "@/components/ui/empty-state";
import { secondaryButton } from "@/components/ui/pos-form";
import { ReceiptPreview } from "./receipt-preview";

export default async function InvoiceReceiptPage({ params, searchParams }: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ lang?: string }>;
}) {
  const [{ id }, query, t] = await Promise.all([params, searchParams, getTranslations("receipts")]);
  if (!/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(id)) notFound();
  const receipt = await api.invoiceReceipt(id).catch((error) => {
    if (error instanceof ApiError && error.status === 404) notFound();
    return null;
  });
  return (
    <div className="space-y-4">
      <Link href="/invoices" className={secondaryButton}><ArrowLeft size={17} aria-hidden="true" />{t("history")}</Link>
      {receipt ? (
        <ReceiptPreview id={id} number={receipt.invoice_number}
          initialLanguage={receiptLanguage(query.lang, receipt.identity.branding?.preferred_language)} />
      ) : <EmptyState title={t("loadError")} />}
    </div>
  );
}
