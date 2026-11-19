import { getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { Link } from "@/i18n/navigation";
import { api, ApiError } from "@/lib/api";
import { receiptLanguage } from "@/lib/receipt/paper";
import { EmptyState } from "@/components/ui/empty-state";
import { secondaryButton } from "@/components/ui/pos-form";
import { ReceiptPreview } from "./receipt-preview";
import { ThermalActions } from "./thermal-actions";
import { hasPermission, verifySession } from "@/lib/session";
import { ReturnPanel } from "./returns";

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
  const session = receipt ? await verifySession() : null;
  const canViewReturns = receipt?.status === "finalized" && session && hasPermission(session.me, "reports:read");
  const canWriteReturns = Boolean(session && ["sales:write", "catalog:write"].every((permission) => hasPermission(session.me, permission)));
  // Thermal queue is optional: an owner who never registered a printer still
  // gets the browser print/download fallback above.
  const [printers, jobs] = receipt && session && hasPermission(session.me, "sales:read")
    ? await Promise.all([
        api.printers().catch(() => []),
        api.printJobs({ invoice_id: id, limit: 5 }).catch(() => null),
      ])
    : [[], null];
  return (
    <div className="space-y-4">
      <Link href="/invoices" className={secondaryButton}><ArrowLeft size={17} aria-hidden="true" />{t("history")}</Link>
      {canViewReturns && <ReturnPanel invoiceId={id} canWrite={canWriteReturns} />}
      {receipt ? (
        <>
          <ReceiptPreview id={id} number={receipt.invoice_number}
            initialLanguage={receiptLanguage(query.lang, receipt.identity.branding?.preferred_language)} />
          {session ? (
            <ThermalActions
              invoiceId={id}
              printers={printers.filter((printer) => printer.is_enabled)}
              jobs={jobs?.items ?? []}
            />
          ) : null}
        </>
      ) : <EmptyState title={t("loadError")} />}
    </div>
  );
}
