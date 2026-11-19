import { NextResponse } from "next/server";
import { api, ApiError } from "@/lib/api";
import { receiptLanguage } from "@/lib/receipt/paper";
import { renderReceiptPdf } from "@/lib/receipt/pdf";
import { receiptHtml } from "@/lib/receipt/template";

export const runtime = "nodejs";

export async function GET(request: Request, { params }: RouteContext<"/api/invoices/[id]/receipt">) {
  const { id } = await params;
  const query = new URL(request.url).searchParams;
  try {
    const receipt = await api.invoiceReceipt(id);
    const language = receiptLanguage(query.get("lang"), receipt.identity.branding?.preferred_language);
    const markup = await receiptHtml(receipt, language);
    const headers = {
      "Cache-Control": "private, no-store",
      "X-Content-Type-Options": "nosniff",
    };
    if (query.get("format") === "pdf") {
      const pdf = await renderReceiptPdf(markup, receipt.issued_at);
      const filename = receipt.invoice_number.replace(/[^A-Za-z0-9_-]+/g, "_");
      return new Response(new Uint8Array(pdf), { headers: {
        ...headers, "Content-Type": "application/pdf",
        "Content-Disposition": `attachment; filename="${filename}-${language}.pdf"`,
      } });
    }
    return new Response(markup, { headers: {
      ...headers, "Content-Type": "text/html; charset=utf-8",
      "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; font-src data:; frame-ancestors 'self'; base-uri 'none'; form-action 'none'",
      "X-Frame-Options": "SAMEORIGIN",
    } });
  } catch (error) {
    if (error instanceof ApiError) {
      return NextResponse.json({ error: error.message, code: error.code, details: {} },
        { status: error.status, headers: { "Cache-Control": "private, no-store" } });
    }
    console.error("Receipt rendering failed", error);
    return NextResponse.json({ error: "Could not render receipt", code: "receipt_unavailable", details: {} },
      { status: 503, headers: { "Cache-Control": "private, no-store" } });
  }
}
