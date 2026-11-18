import { cookies } from "next/headers";

/**
 * Session cookie holding the API's JWT. It is httpOnly and server-only so the
 * token never reaches browser JavaScript; writes are proxied through
 * /api/billing/invoices, which attaches the Authorization header.
 */
export const SESSION_COOKIE = "shopflow_token";

/** Lifecycle helper shared by the login/logout route handler and server pages. */
export async function readSessionToken(): Promise<string | null> {
  const store = await cookies();
  return store.get(SESSION_COOKIE)?.value ?? null;
}

export function authHeaders(token: string | null): Record<string, string> {
  return token ? { Authorization: `Bearer ${token}` } : {};
}
