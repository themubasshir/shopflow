import { NextResponse, type NextRequest } from "next/server";
import { readSessionToken } from "@/lib/session";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001/api/v1";

/**
 * Catalog write-path proxy. Forwards product / category / import calls to the
 * API with the caller's JWT. Multipart bodies (the import file upload) are
 * streamed through verbatim so the API can parse them; JSON is passed through
 * untouched. The token never reaches client JS.
 */
const route = new RegExp(
  "^(?:catalog/(?:products(?:/[0-9a-f-]{36}(?:/state)?)?|categories(?:/[0-9a-f-]{36}|/manage)?|imports/(?:preview|commit)))$",
  "i",
);

async function forward(
  request: NextRequest,
  { params }: RouteContext<"/api/catalog-ops/[...segments]">,
) {
  const path = (await params).segments.join("/");
  if (!route.test(path)) {
    return NextResponse.json({ code: "not_found" }, { status: 404 });
  }
  const token = await readSessionToken();
  if (!token) {
    return NextResponse.json(
      { error: "Sign in required", code: "unauthenticated", details: {} },
      { status: 401 },
    );
  }

  const contentType = request.headers.get("content-type") ?? "";
  const headers: Record<string, string> = { Authorization: `Bearer ${token}` };
  let body: BodyInit | undefined;
  if (contentType.includes("multipart/form-data")) {
    // Forward the raw multipart stream so the boundary stays intact.
    headers["Content-Type"] = contentType;
    body = await request.arrayBuffer();
  } else if (request.method !== "GET" && request.method !== "HEAD") {
    headers["Content-Type"] = "application/json";
    body = await request.text();
  }

  const res = await fetch(`${API_BASE}/${path}${request.nextUrl.search}`, {
    method: request.method,
    headers,
    body,
    cache: "no-store",
  });
  const out = res.status === 204 ? null : await res.arrayBuffer();
  return new NextResponse(out, {
    status: res.status,
    headers: {
      "Content-Type": res.headers.get("content-type") ?? "application/json",
      "Cache-Control": "no-store",
    },
  });
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
export const PATCH = forward;
export const DELETE = forward;
