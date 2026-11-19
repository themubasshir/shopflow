import { apiProxy } from "@/app/api/_lib/proxy";

export async function POST(
  request: Request,
  { params }: RouteContext<"/api/customers/[id]/invoices/[invoiceId]/payments">,
) {
  const { id, invoiceId } = await params;
  const key = request.headers.get("Idempotency-Key");
  return apiProxy(`/customers/${encodeURIComponent(id)}/invoices/${encodeURIComponent(invoiceId)}/payments`, {
    method: "POST",
    headers: key ? { "Idempotency-Key": key } : {},
    body: await request.text(),
  });
}
