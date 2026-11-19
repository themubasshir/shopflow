import { NextResponse, type NextRequest } from "next/server";
import { apiProxy } from "@/app/api/_lib/proxy";

const route = new RegExp(
  "^(?:suppliers(?:/[0-9a-f-]{36}(?:/ledger)?)?|purchases(?:/[0-9a-f-]{36}(?:/(?:receive|payments|cancel|reverse))?)?|inventory/(?:batches(?:/[0-9a-f-]{36}/state)?|adjustments|movements|products/[0-9a-f-]{36}/(?:valuation|units|threshold))|catalog/products)$",
  "i",
);

async function forward(request: NextRequest, { params }: RouteContext<"/api/inventory-ops/[...segments]">) {
  const path = (await params).segments.join("/");
  if (!route.test(path)) return NextResponse.json({ code: "not_found" }, { status: 404 });
  const key = request.headers.get("Idempotency-Key");
  return apiProxy("/" + path + request.nextUrl.search, {
    method: request.method,
    headers: key ? { "Idempotency-Key": key } : {},
    body: request.method === "GET" ? undefined : await request.text(),
  });
}

export { forward as GET, forward as POST, forward as PUT };
