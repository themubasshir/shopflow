import { NextResponse, type NextRequest } from "next/server";
import { cookies } from "next/headers";
import { SESSION_COOKIE, readSessionToken } from "@/lib/session";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001/api/v1";

/**
 * POST /api/auth — body: { action, ... }.
 *   login    {email,password}           → proxy /auth/login, set httpOnly cookie
 *   logout   {}                          → Bearer /auth/logout upstream, clear cookie
 *   password {current_password,new_password} → Bearer /auth/password (own password)
 * The API token is stored in an httpOnly cookie; it is never handed to the
 * browser. Same-site strict keeps it inside the POS app.
 */
export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => ({}));
  const store = await cookies();

  if (body?.action === "logout") {
    const token = await readSessionToken();
    if (token) {
      // Best-effort upstream revoke; the cookie is cleared regardless so the
      // browser is signed out even if the API is unreachable.
      await fetch(`${API_BASE}/auth/logout`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        cache: "no-store",
      }).catch(() => {});
    }
    store.delete(SESSION_COOKIE);
    return NextResponse.json({ ok: true });
  }

  if (body?.action === "password") {
    const token = await readSessionToken();
    if (!token) {
      return NextResponse.json(
        { error: "Not signed in", code: "unauthenticated", details: {} },
        { status: 401 },
      );
    }
    const res = await fetch(`${API_BASE}/auth/password`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        current_password: body.current_password,
        new_password: body.new_password,
      }),
      cache: "no-store",
    });
    if (!res.ok) {
      const payload = await res.json().catch(() => ({}));
      return NextResponse.json(
        {
          error: payload.error ?? "Password change failed",
          code: payload.code ?? "unknown",
          details: payload.details ?? {},
        },
        { status: res.status },
      );
    }
    return NextResponse.json({ ok: true });
  }

  // default: login
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
