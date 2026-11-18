import { cache } from "react";
import { cookies } from "next/headers";

/**
 * Session cookie holding the API's JWT. It is httpOnly and server-only so the
 * token never reaches browser JavaScript; writes are proxied through the
 * /api/* route handlers, which attach the Authorization header.
 */
export const SESSION_COOKIE = "shopflow_token";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001/api/v1";

/** Lifecycle helper shared by the login/logout route handler and server pages. */
export async function readSessionToken(): Promise<string | null> {
  const store = await cookies();
  return store.get(SESSION_COOKIE)?.value ?? null;
}

export function authHeaders(token: string | null): Record<string, string> {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// ---- Session / current user ------------------------------------------------

/** Mirrors the API's MeOut (GET /auth/me). */
export interface Me {
  id: string;
  name: string;
  email: string;
  preferred_locale: "en" | "bn";
  role: string;
  permissions: string[];
  /** null = unrestricted (owner/manager); a list = restricted (cashier). */
  assigned_counter_ids: string[] | null;
  is_demo: boolean;
}

export interface Session {
  token: string;
  me: Me;
}

/**
 * Data Access Layer entry point: reads the JWT cookie and validates it against
 * the API (`/auth/me`). Returns null when there is no cookie or the token is
 * rejected (401). Wrapped in React `cache` so all consumers in one render pass
 * share a single upstream call. Server-only — never import from a client file.
 */
export const verifySession = cache(async (): Promise<Session | null> => {
  const token = await readSessionToken();
  if (!token) return null;
  try {
    const res = await fetch(`${API_BASE}/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    });
    if (!res.ok) return null;
    const me = (await res.json()) as Me;
    return { token, me };
  } catch {
    return null;
  }
});

/** True when the signed-in user holds a permission (or the owner wildcard). */
export function hasPermission(
  me: Pick<Me, "permissions" | "role">,
  permission: string,
): boolean {
  return me.permissions.includes(permission);
}
