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
  // 204 No Content (disable/enable/logout) has no JSON body — don't parse it.
  if (res.status === 204) return undefined as T;
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
  product: (id: string) =>
    request<import("@/types").ProductDetailOut>(`/catalog/products/${encodeURIComponent(id)}`),
  categoriesManage: () =>
    request<import("@/types").CategoryManageOut[]>("/catalog/categories/manage"),
  counters: () => request<import("@/types").CounterOut[]>("/counters"),
  customers: (query = new URLSearchParams()) =>
    request<import("@/types").Paginated<import("@/types").CustomerOut>>(`/customers?${query}`),
  customer: (id: string) => request<import("@/types").CustomerOut>(`/customers/${encodeURIComponent(id)}`),
  customerBalance: (id: string) => request<import("@/types").CustomerBalanceOut>(`/customers/${id}/balance`),
  customerLoyalty: (id: string) => request<import("@/types").CustomerLoyaltyOut>(`/customers/${id}/loyalty`),
  customerInvoices: (id: string, offset: number) => request<import("@/types").Paginated<import("@/types").InvoiceOut>>(`/customers/${id}/invoices?offset=${offset}`),
  customerPayments: (id: string, offset: number) => request<import("@/types").Paginated<import("@/types").CustomerPaymentOut>>(`/customers/${id}/payments?offset=${offset}`),
  customerStatement: (id: string, offset: number) => request<import("@/types").Paginated<import("@/types").CustomerLedgerEntryOut>>(`/customers/${id}/statement?offset=${offset}`),
  customerLoyaltyHistory: (id: string, offset: number) => request<import("@/types").Paginated<import("@/types").LoyaltyEntryOut>>(`/customers/${id}/loyalty/transactions?offset=${offset}`),
  loyaltyAccounts: (offset = 0) =>
    request<import("@/types").Paginated<import("@/types").LoyaltyAccountOut>>("/loyalty/accounts?limit=24&offset=" + offset),
  invoices: (query = new URLSearchParams()) => request<import("@/types").Paginated<import("@/types").InvoiceOut>>("/invoices?" + query),
  invoiceReceipt: (id: string) => request<import("@/types").InvoiceReceipt>(`/invoices/${encodeURIComponent(id)}/receipt`),
  receiptSettings: () => request<import("@/types").ReceiptSettings>("/settings/receipts"),

  // ---- Phase 2D-2: print agent render grants --------------------------------
  // Server-to-server: the web layer exchanges a verified render grant for the
  // receipt the grant scopes, so an agent's printed PDF is the canonical doc.
  receiptForGrant: (grant: string, invoiceId: string) =>
    request<import("@/types").InvoiceReceipt>("/print/grants/receipt", {
      method: "POST",
      body: JSON.stringify({ grant, invoice_id: invoiceId }),
    }),

  // ---- Phase 2D-2: shared thermal printing (server components only) ---------
  printers: () => request<import("@/types").PrinterOut[]>("/printing/printers"),
  printJobs: (params?: { invoice_id?: string; status?: string; limit?: number; offset?: number }) => {
    const qs = params
      ? "?" +
        new URLSearchParams(
          Object.entries(params)
            .filter(([, v]) => v != null)
            .map(([k, v]) => [k, String(v)]),
        ).toString()
      : "";
    return request<import("@/types").PrintJobList>(`/printing/jobs${qs}`);
  },

  // ---- Phase 2B: session / employees / counter management ------------------
  me: () => request<import("@/lib/session").Me>("/auth/me"),
  employees: () => request<import("@/types").EmployeeOut[]>("/employees"),
  employeeRoles: () => request<import("@/types").RoleOut[]>("/employees/roles"),
  createEmployee: (body: import("@/types").EmployeeCreate) =>
    request<import("@/types").EmployeeOut>("/employees", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateEmployee: (id: string, body: import("@/types").EmployeeUpdate) =>
    request<import("@/types").EmployeeOut>(`/employees/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  disableEmployee: (id: string) =>
    request<void>(`/employees/${id}/disable`, { method: "POST" }),
  enableEmployee: (id: string) =>
    request<void>(`/employees/${id}/enable`, { method: "POST" }),
  resetEmployeePassword: (id: string, newPassword: string) =>
    request<void>(`/employees/${id}/reset-password`, {
      method: "POST",
      body: JSON.stringify({ new_password: newPassword }),
    }),
  assignEmployeeCounters: (id: string, counterIds: string[]) =>
    request<import("@/types").EmployeeOut>(`/employees/${id}/counters`, {
      method: "PUT",
      body: JSON.stringify({ counter_ids: counterIds }),
    }),
  manageCounters: () =>
    request<import("@/types").CounterOut[]>("/manage/counters"),
  counterStaff: (id: string) =>
    request<import("@/types").CounterStaffOut[]>(`/manage/counters/${id}/staff`),
  updateCounter: (id: string, body: import("@/types").CounterUpdate) =>
    request<import("@/types").CounterOut>(`/manage/counters/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
};
