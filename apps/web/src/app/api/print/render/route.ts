import { NextResponse } from "next/server";
import { api, ApiError } from "@/lib/api";
import { receiptLanguage } from "@/lib/receipt/paper";
import { renderReceiptPdf } from "@/lib/receipt/pdf";
import { receiptHtml } from "@/lib/receipt/template";
import { testPageHtml } from "@/lib/receipt/test-page";

export const runtime = "nodejs";

interface GrantClaims {
  kind?: string;
  invoice_id?: string;
  language?: string;
  printer_name?: string;
  paper_width_mm?: number;
  dots_width?: number;
  type?: string;
}

/**
 * Canonical print document for a print agent. The agent presents a short-lived,
 * single-purpose `grant` minted by the API when it claimed a job. We verify the
 * grant signature with the shared secret, then render exactly the scoped
 * document through the ONE receipt engine (invoice) or the calibration template
 * (test page). The grant authorizes a single render and cannot be widened or
 * minted here.
 */
export async function GET(request: Request) {
  const grant = new URL(request.url).searchParams.get("grant") ?? "";
  if (!grant) {
    return NextResponse.json(
      { error: "Missing render grant", code: "unauthenticated", details: {} },
      { status: 401 },
    );
  }
  let claims: GrantClaims;
  try {
    const res = await fetch(
      `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001/api/v1"}/print/grants/verify`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ grant }),
        cache: "no-store",
      },
    );
    const body = (await res.json().catch(() => ({}))) as GrantClaims;
    if (!res.ok || body.type !== "render") {
      return NextResponse.json(
        { error: "Invalid render grant", code: "unauthenticated", details: {} },
        { status: 401 },
      );
    }
    claims = body;
  } catch {
    return NextResponse.json(
      { error: "Grant verification unavailable", code: "render_unavailable", details: {} },
      { status: 503 },
    );
  }

  const language = receiptLanguage(claims.language ?? null, "bilingual");
  try {
    if (claims.kind === "test_page") {
      const markup = await testPageHtml({
        language,
        printerName: claims.printer_name ?? "Printer",
        paperWidthMm: claims.paper_width_mm ?? 80,
        dotsWidth: claims.dots_width ?? 576,
        dpi: 203,
      });
      const pdf = await renderReceiptPdf(markup, new Date().toISOString());
      return pdfResponse(pdf, "printer-test-page", language);
    }
    if (claims.kind !== "invoice" || !claims.invoice_id) {
      return NextResponse.json(
        { error: "Invalid render grant", code: "unauthenticated", details: {} },
        { status: 401 },
      );
    }
    // The grant is the authorization. We fetch the receipt the grant scopes
    // (the API refuses any invoice_id outside the grant) and render it through
    // the ONE canonical template + PDF engine.
    const receipt = await api.receiptForGrant(grant, String(claims.invoice_id));
    const markup = await receiptHtml(receipt, language);
    const pdf = await renderReceiptPdf(markup, receipt.issued_at);
    const filename = receipt.invoice_number.replace(/[^A-Za-z0-9_-]+/g, "_");
    return pdfResponse(pdf, `${filename}-${language}`, language);
  } catch (error) {
    if (error instanceof ApiError) {
      return NextResponse.json(
        { error: error.message, code: error.code, details: {} },
        { status: error.status },
      );
    }
    return NextResponse.json(
      { error: "Could not render receipt", code: "receipt_unavailable", details: {} },
      { status: 503 },
    );
  }
}

function pdfResponse(pdf: Uint8Array, name: string, language: string) {
  return new Response(new Uint8Array(pdf), {
    headers: {
      "Content-Type": "application/pdf",
      "Content-Disposition": `inline; filename="${name}-${language}.pdf"`,
      "Cache-Control": "private, no-store",
      "X-Content-Type-Options": "nosniff",
    },
  });
}
