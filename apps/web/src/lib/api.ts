const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001/api/v1";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    // Read APIs only for Phase 1 - always get fresh data, no cache.
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(
      body.error ?? `Request failed: ${res.status}`,
      res.status,
      body.code ?? "unknown",
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
  customers: () => request<import("@/types").Paginated<import("@/types").CustomerOut>>("/customers"),
  loyaltyAccounts: () =>
    request<import("@/types").Paginated<import("@/types").LoyaltyAccountOut>>("/loyalty/accounts"),
  invoices: () => request<import("@/types").Paginated<import("@/types").InvoiceOut>>("/invoices"),
};
