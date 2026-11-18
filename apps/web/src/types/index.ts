/** Mirrors apps/api schemas for Phase 1; generated contract types land in packages/contracts. */

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

export interface CustomerOut {
  id: string;
  name: string;
  phone: string | null;
  email: string | null;
  credit_limit: string;
  points_balance: number;
  is_active: boolean;
}

export interface LoyaltyAccountOut {
  customer_id: string;
  customer_name: string;
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

export interface InvoiceOut {
  id: string;
  invoice_number: string;
  counter_code: string | null;
  customer_name: string | null;
  status: string;
  subtotal: string;
  discount_total: string;
  loyalty_discount: string;
  tax_total: string;
  total: string;
  paid_total: string;
  due_total: string;
  finalized_at: string | null;
  created_at: string;
  items: InvoiceItemOut[];
  payment_methods: string[];
}
