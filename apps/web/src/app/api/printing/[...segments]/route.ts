import { NextResponse, type NextRequest } from "next/server";
import { apiProxy } from "@/app/api/_lib/proxy";

const UUID = "[0-9a-f-]{36}";
const route = new RegExp(
  `^(?:` +
    `printers` +                       // list
    `|printers/${UUID}` +              // update
    `|printers/${UUID}/rotate-token` +
    `|printers/${UUID}/test-page` +
    `|counters/${UUID}/printer` +      // assign counter ↔ printer
    `|jobs(?:/${UUID}(?:/(?:reprint|retry|cancel))?)?` +
    `)$`,
  "i",
);

async function forward(request: NextRequest, { params }: RouteContext<"/api/printing/[...segments]">) {
  const path = (await params).segments.join("/");
  if (!route.test(path)) {
    return NextResponse.json({ code: "not_found" }, { status: 404 });
  }
  return apiProxy("/printing/" + path + request.nextUrl.search, {
    method: request.method,
    body: request.method === "GET" ? undefined : await request.text(),
  });
}

export { forward as GET, forward as POST, forward as PATCH, forward as PUT };
