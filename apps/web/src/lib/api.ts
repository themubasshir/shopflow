import { readSessionToken } from "@/lib/session";
import { ApiError } from "@/lib/api-client";

export { ApiError, fieldErrors, newIdempotencyKey } from "@/lib/api-client";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001/api/v1";

/**
 * Server-side request helper. The JWT lives in an httpOnly cookie, so only
 * server code (Server Components and Route Handlers) attaches it.
 */
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = await readSessionToken();
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers ?? {}),
    },
    // Always fetch fresh data — the POS never wants a cached catalog/invoice.
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(
      body.error ?? `Request failed: ${res.status}`,
      res.status,
      body.code ?? "unknown",
      body.details ?? {},
    );
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => request<{ status: string; database: string }>("/health"),
  dashboard: () => request<import("@/types").DashboardResponse>("/reports/dashboard"),
  products: (params?: Record<string, string | number | boolean>) => {
    const qs = params
      ? "?" +
        new URLSearchParams(
          Object.entries(params).map(([k, v]) => [k, String(v)]),
        ).toString()
      : "";
    return request<import("@/types").Paginated<import("@/types").ProductOut>>(
      `/catalog/products${qs}`,
    );
  },
  categories: () => request<import("@/types").CategoryOut[]>("/catalog/categories"),
  counters: () => request<import("@/types").CounterOut[]>("/counters"),
  customers: () => request<import("@/types").Paginated<import("@/types").CustomerOut>>("/customers"),
  loyaltyAccounts: () =>
    request<import("@/types").Paginated<import("@/types").LoyaltyAccountOut>>("/loyalty/accounts"),
  invoices: () => request<import("@/types").Paginated<import("@/types").InvoiceOut>>("/invoices"),
};
