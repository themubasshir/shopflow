import { NextResponse } from "next/server";
import { readSessionToken } from "@/lib/session";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001/api/v1";

/**
 * Authenticated write-path proxy shared by the /api/* route handlers. Reads the
 * JWT from the httpOnly cookie, forwards the request verbatim to the API and
 * streams the response (including the {error,code,details} envelope) back so the
 * browser can localize it. The token never reaches client JS.
 */
export async function apiProxy(
  path: string,
  init: RequestInit = {},
): Promise<NextResponse> {
  const token = await readSessionToken();
  if (!token) {
    return NextResponse.json(
      { error: "Sign in required", code: "unauthenticated", details: {} },
      { status: 401 },
    );
  }
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...(init.headers ?? {}),
    },
    cache: "no-store",
  });
  const body = res.status === 204 ? null : await res.arrayBuffer();
  return new NextResponse(body, {
    status: res.status,
    headers: {
      "Content-Type": res.headers.get("content-type") ?? "application/json",
      "Cache-Control": "no-store",
    },
  });
}
