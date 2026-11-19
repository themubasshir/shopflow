import type { components } from "../../../../packages/contracts/api.generated";

/** Mirrors apps/api schemas for Phase 1; generated contract types land in packages/contracts. */

export type InvoiceReturns = components["schemas"]["InvoiceReturnsOut"];
export type ReturnChoice = components["schemas"]["ReturnOption"];
export type ReturnHistory = components["schemas"]["ReturnOut"];
export type PurchaseCredits = components["schemas"]["PurchaseCreditsOut"];
export type SupplierCreditNote = components["schemas"]["CreditNoteOut"];
export type FinanceReport = components["schemas"]["FinanceReport"];
export type Reconciliation = components["schemas"]["ReconciliationOut"];

export interface Paginated<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface CounterActivity {
  id: string;
  code: string;
  name_en: string;
  name_bn: string;
  active_cashier: string | null;
  invoice_count: number;
  total_sales: string;
  is_busy: boolean;
}

export interface SalesPoint {
  bucket: string;
  sales: string;
  invoice_count: number;
}

export interface LowStockAlert {
  product_id: string;
  sku: string;
  name_en: string;
  name_bn: string;
  stock_on_hand: string;
  low_stock_threshold: string;
  category_name_en: string | null;
}

export interface ExpiryAlert {
  batch_id: string;
  product_id: string;
  sku: string;
  name_en: string;
  name_bn: string;
  batch_number: string;
  expiry_date: string;
  quantity_on_hand: string;
  days_to_expiry: number;
}

export interface RecentTransaction {
  id: string;
  invoice_number: string;
  counter_code: string;
  customer_name: string | null;
  total: string;
  method: string | null;
  finalized_at: string | null;
  status: string;
}

export interface DashboardSummary {
  today_sales: string;
  invoice_count: number;
  average_bill: string;
  low_stock_count: number;
  expiring_soon_count: number;
  active_counters: number;
  is_demo: boolean;
  generated_at: string;
}

export interface DashboardResponse {
  summary: DashboardSummary;
  counters: CounterActivity[];
  sales_series: SalesPoint[];
  recent_transactions: RecentTransaction[];
  low_stock: LowStockAlert[];
  expiring: ExpiryAlert[];
}

export interface CategoryOut {
  id: string;
  name_en: string;
  name_bn: string;
  slug: string;
  is_medicine: boolean;
  loyalty_eligible: boolean;
  product_count: number;
}

export interface ProductOut {
  id: string;
  sku: string;
  barcode: string | null;
  name_en: string;
  name_bn: string;
  unit: string;
  is_medicine: boolean;
  is_active: boolean;
  stock_on_hand: string;
  low_stock_threshold: string;
  price: string | null;
  category_name_en: string | null;
  category_name_bn: string | null;
  loyalty_eligible: boolean;
}

export type CustomerOut = components["schemas"]["CustomerOut"];

export interface LoyaltyAccountOut {
  customer_id: string;
  customer_name: string;
  customer_name_bn?: string | null;
  phone: string | null;
  points_balance: number;
  lifetime_earned: number;
  lifetime_redeemed: number;
  can_redeem: boolean;
}

export interface InvoiceItemOut {
  id: string;
  product_id: string;
  description: string;
  quantity: string;
  unit_price: string;
  line_discount: string;
  line_total: string;
}

export type InvoiceOut = components["schemas"]["InvoiceOut"];

// ---- Phase 2A: billing write path ------------------------------------------

export interface CounterOut {
  id: string;
  code: string;
  name_en: string;
  name_bn: string;
  is_active: boolean;
}

export interface InvoiceItemCreate {
  product_id: string;
  product_unit_id?: string | null;
  quantity: string;
  line_discount?: string;
}

export interface PaymentCreate {
  method: "cash" | "bkash" | "nagad";
  amount?: string | null;
  reference?: string | null;
}

export type InvoiceCreate = components["schemas"]["InvoiceCreate"];

export interface PaymentOut {
  id: string;
  method: string;
  amount: string;
  reference: string | null;
  paid_at: string;
}

export type InvoiceCreateOut = components["schemas"]["InvoiceCreateOut"];

// ---- Phase 2B: employees & counter management -------------------------------

export interface RoleOut {
  id: string;
  code: string;
  name_en: string;
  name_bn: string;
}

export interface EmployeeOut {
  id: string;
  name: string;
  email: string;
  phone: string | null;
  role_code: string;
  role_name_en: string;
  role_name_bn: string;
  is_active: boolean;
  preferred_locale: "en" | "bn";
  last_login_at: string | null;
  assigned_counter_ids: string[];
  created_at: string;
}

export interface EmployeeCreate {
  name: string;
  email: string;
  phone?: string | null;
  role_id: string;
  password: string;
  preferred_locale: "en" | "bn";
  counter_ids: string[];
}

export interface EmployeeUpdate {
  name?: string;
  phone?: string | null;
  role_id?: string;
  preferred_locale?: "en" | "bn";
}

export interface CounterUpdate {
  is_active?: boolean;
  name_en?: string;
  name_bn?: string;
}

export interface CounterStaffOut {
  name: string;
  email: string;
  is_active: boolean;
}

// ---- Phase 2D-2: shared thermal printing ------------------------------------

export type ReceiptLang = "en" | "bn" | "bilingual";
export type PrintJobStatus =
  | "pending"
  | "claimed"
  | "printing"
  | "completed"
  | "failed"
  | "uncertain"
  | "cancelled";

export interface PrinterCapabilities {
  raster: boolean;
  character: boolean;
}

export interface PrinterConnection {
  host?: string;
  port?: number;
  gateway_id?: string;
  device_address?: string | null;
}

export interface PrinterOut {
  id: string;
  name: string;
  transport: "network" | "bluetooth";
  agent_id: string;
  device_model: string | null;
  paper_width_mm: number;
  dots_width: number;
  dpi: number;
  density: number;
  feed_dots: number;
  has_cutter: boolean;
  is_enabled: boolean;
  default_language: ReceiptLang;
  capabilities: PrinterCapabilities | null;
  counter_ids: string[];
}

export interface PrinterCreate {
  name: string;
  transport: "network" | "bluetooth";
  agent_id: string;
  device_model?: string | null;
  paper_width_mm?: number;
  dots_width?: number;
  dpi?: number;
  density?: number;
  feed_dots?: number;
  has_cutter?: boolean;
  is_enabled?: boolean;
  default_language?: ReceiptLang;
  capabilities?: PrinterCapabilities;
  config?: PrinterConnection | null;
}

export interface PrinterUpdate {
  name?: string;
  transport?: "network" | "bluetooth";
  agent_id?: string;
  device_model?: string | null;
  paper_width_mm?: number;
  dots_width?: number;
  dpi?: number;
  density?: number;
  feed_dots?: number;
  has_cutter?: boolean;
  is_enabled?: boolean;
  default_language?: ReceiptLang;
  capabilities?: PrinterCapabilities;
  config?: PrinterConnection | null;
}

export interface PrinterRegistered {
  printer: PrinterOut;
  agent_token: string;
}

export interface PrintJobOut {
  id: string;
  kind: "invoice" | "test_page";
  invoice_id: string | null;
  printer_id: string;
  counter_id: string | null;
  language: string;
  status: PrintJobStatus;
  attempts: number;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
  reprint_of_job_id: string | null;
}

export interface PrintJobList {
  items: PrintJobOut[];
  total: number;
  limit: number;
  offset: number;
}

export type CustomerCreate = components["schemas"]["CustomerCreate"];
export type CustomerUpdate = components["schemas"]["CustomerUpdate"];
export type CustomerLoyaltyOut = components["schemas"]["CustomerLoyaltyOut"];
export type LoyaltyEntryOut = components["schemas"]["LoyaltyEntryOut"];
export type CustomerPaymentOut = components["schemas"]["CustomerPaymentOut"];
export type CustomerBalanceOut = components["schemas"]["CustomerBalanceOut"];
export type CustomerLedgerEntryOut = components["schemas"]["CustomerLedgerEntryOut"];
export type DuePaymentCreate = components["schemas"]["DuePaymentCreate"];
export type DuePaymentOut = components["schemas"]["DuePaymentOut"];

export type InvoiceReceipt = components["schemas"]["InvoiceReceipt"];
export type ReceiptSettings = components["schemas"]["ReceiptSettings"];

export type InventorySupplier = components["schemas"]["SupplierOut"];
export type SupplierEntry = components["schemas"]["SupplierEntry"];
export type InventoryPurchase = components["schemas"]["PurchaseOut"];
export type InventoryBatch = components["schemas"]["BatchOut"];
export type InventoryUnit = components["schemas"]["ProductUnitOut"];
export type InventoryMovement = components["schemas"]["MovementOut"];
export type InventoryValue = components["schemas"]["StockValue"];
