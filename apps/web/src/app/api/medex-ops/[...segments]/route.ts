import { NextResponse, type NextRequest } from "next/server";
import { apiProxy } from "@/app/api/_lib/proxy";

/**
 * MedEx import-workspace proxy. Forwards the review-workspace calls to the API
 * (mounted at /catalog/medex) with the caller's JWT. Only the read + review
 * paths are whitelisted — the collector runs off-band via the CLI and is never
 * reachable through the browser.
 */
const route = new RegExp(
  "^(?:" +
    "source|runs|" +
    "staging(?:/filters|/stats|/approve|/reject)?|" +
    "matches(?:/decide)?" +
    ")$",
  "i",
);

async function forward(
  request: NextRequest,
  { params }: RouteContext<"/api/medex-ops/[...segments]">,
) {
  const path = (await params).segments.join("/");
  if (!route.test(path)) {
    return NextResponse.json({ code: "not_found" }, { status: 404 });
  }
  return apiProxy("/catalog/medex/" + path + request.nextUrl.search, {
    method: request.method,
    body: request.method === "GET" ? undefined : await request.text(),
  });
}

export { forward as GET, forward as POST, forward as PATCH, forward as PUT };
