import { NextResponse, type NextRequest } from "next/server";
import { cookies } from "next/headers";
import { SESSION_COOKIE } from "@/lib/session";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001/api/v1";

/**
 * POST /api/auth — body: { action: "login" | "logout", email?, password? }.
 * The API token is stored in an httpOnly cookie; it is never handed to the
 * browser. Same-site strict keeps it inside the POS app.
 */
export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => ({}));
  const store = await cookies();

  if (body?.action === "logout") {
    store.delete(SESSION_COOKIE);
    return NextResponse.json({ ok: true });
  }

  const email = typeof body?.email === "string" ? body.email : "";
  const password = typeof body?.password === "string" ? body.password : "";
  if (!email || !password) {
    return NextResponse.json(
      { error: "Email and password are required", code: "validation_error" },
      { status: 422 },
    );
  }

  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
    cache: "no-store",
  });
  const payload = await res.json().catch(() => ({}));
  if (!res.ok) {
    return NextResponse.json(
      {
        error: payload.error ?? "Login failed",
        code: payload.code ?? "unauthenticated",
        details: payload.details ?? {},
      },
      { status: res.status },
    );
  }

  store.set(SESSION_COOKIE, payload.access_token, {
    httpOnly: true,
    sameSite: "strict",
    secure: process.env.NODE_ENV === "production",
    maxAge: typeof payload.expires_in === "number" ? payload.expires_in : 60 * 60 * 12,
    path: "/",
  });
  return NextResponse.json({ ok: true });
}
