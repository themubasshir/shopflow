import { apiProxy } from "../../_lib/proxy";

export async function POST(request: Request) {
  const key = request.headers.get("Idempotency-Key");
  return apiProxy("/invoices", {
    method: "POST",
    headers: key ? { "Idempotency-Key": key } : {},
    body: await request.text(),
  });
}
