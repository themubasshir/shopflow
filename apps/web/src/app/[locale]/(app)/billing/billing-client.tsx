"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  Search,
  User,
  Minus,
  Plus,
  Trash2,
  CheckCircle2,
  AlertTriangle,
  X,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { Link, useRouter } from "@/i18n/navigation";
import { ApiError, browserRequest, newIdempotencyKey } from "@/lib/api-client";
import { formatBDT, localizedName, formatNumber } from "@/lib/format";
import { fieldClass, localDigits, minorUnits, primaryButton, secondaryButton } from "@/components/ui/pos-form";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import type {
  CounterOut,
  CustomerOut,
  InvoiceCreate,
  InvoiceCreateOut,
  Paginated,
  ProductOut,
} from "@/types";
import type { Locale } from "@/i18n/config";

type CartLine = {
  product: ProductOut;
  qty: number;
};

type PayMethod = "cash" | "bkash" | "nagad";

function parseDecimal(value: string | null | undefined): number {
  const n = value == null ? NaN : parseFloat(value);
  return Number.isFinite(n) ? n : 0;
}

function BillingDialog({ titleId, dismiss, children }: {
  titleId: string;
  dismiss?: () => void;
  children: ReactNode;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    return () => element?.close();
  }, []);
  return (
    <dialog ref={dialog} aria-labelledby={titleId} onCancel={(event) => { event.preventDefault(); dismiss?.(); }}
      className="fixed inset-0 m-0 h-full max-h-none w-full max-w-none items-end justify-center bg-transparent p-4 open:flex backdrop:bg-black/40 sm:items-center">
      {children}
    </dialog>
  );
}

export function BillingClient({
  locale,
  products,
  counters,
  customers,
  canRedeem,
}: {
  locale: Locale;
  products: ProductOut[];
  counters: CounterOut[];
  customers: CustomerOut[];
  canRedeem: boolean;
}) {
  const t = useTranslations("billing");
  const receiptsText = useTranslations("receipts");
  const customersText = useTranslations("customers");
  const router = useRouter();

  // ----- cart state --------------------------------------------------------
  const [query, setQuery] = useState("");
  const [cart, setCart] = useState<CartLine[]>([]);
  const [counterId, setCounterId] = useState(counters[0]?.id ?? "");
  const [customer, setCustomer] = useState<CustomerOut | null>(null);
  const [customerQuery, setCustomerQuery] = useState("");
  const [customerSearch, setCustomerSearch] = useState<{ query: string; items: CustomerOut[]; failed?: boolean } | null>(null);
  const [redeemInput, setRedeemInput] = useState("");
  const [paymentMode, setPaymentMode] = useState<"full" | "partial" | "due">("full");
  const [partial, setPartial] = useState("");
  const [uncertain, setUncertain] = useState(false);
  const pending = useRef<InvoiceCreate | null>(null);
  const [discount, setDiscount] = useState("0");
  const [payMethod, setPayMethod] = useState<PayMethod>("cash");
  const [confirming, setConfirming] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [errorCode, setErrorCode] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<InvoiceCreateOut | null>(null);
  const [idemKey, setIdemKey] = useState(() => newIdempotencyKey());

  // Keep the page under a modal from scrolling — on touch devices the CATALOG
  // behind the dialog otherwise moves and steals taps meant for the buttons.
  const modalOpen = confirming || receipt !== null;
  useEffect(() => {
    if (!modalOpen) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [modalOpen]);

  const customerTerm = customerQuery.trim();
  useEffect(() => {
    if (!customerTerm) return;
    const abort = new AbortController();
    const timer = setTimeout(async () => {
      const query = new URLSearchParams({ q: customerTerm, active: "true", limit: "30" });
      try {
        const matches = await browserRequest<Paginated<CustomerOut>>("/api/customers?" + query, { signal: abort.signal });
        if (!abort.signal.aborted) setCustomerSearch({ query: customerTerm, items: matches.items });
      } catch {
        if (!abort.signal.aborted) setCustomerSearch({ query: customerTerm, items: [], failed: true });
      }
    }, 250);
    return () => { clearTimeout(timer); abort.abort(); };
  }, [customerTerm]);
  const loadingCustomers = Boolean(customerTerm && customerSearch?.query !== customerTerm);
  const customerOptions = customerTerm ? (loadingCustomers ? [] : customerSearch?.items ?? []) : customers;
  const candidates = customer && !customerOptions.some((row) => row.id === customer.id)
    ? [customer, ...customerOptions] : customerOptions;

  // ----- derived -----------------------------------------------------------
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return products;
    return products.filter(
      (p) =>
        p.name_en.toLowerCase().includes(q) ||
        p.name_bn.toLowerCase().includes(q) ||
        p.sku.toLowerCase().includes(q) ||
        (p.barcode ?? "").toLowerCase().includes(q),
    );
  }, [products, query]);

  const totals = cart.reduce((sum, line) => {
    const amount = (minorUnits(line.product.price ?? "") ?? 0) * line.qty;
    return {
      subtotal: sum.subtotal + amount,
      eligible: sum.eligible + (line.product.loyalty_eligible ? amount : 0),
    };
  }, { subtotal: 0, eligible: 0 });
  const manual = minorUnits(discount || "0");
  const discountInvalid = manual === null || manual > 99_999_999 || (cart.length > 0 && manual >= totals.subtotal);
  const maxPoints = customer && customer.points_balance >= 300 && canRedeem
    ? Math.max(0, Math.min(Math.floor(customer.points_balance / 100), Math.floor((totals.eligible - (manual ?? 0)) / 10000)) * 100)
    : 0;
  const redeemText = localDigits(redeemInput.trim());
  const redeemPoints = redeemText ? Number(redeemText) : 0;
  const redemptionInvalid = !/^\d*$/.test(redeemText) || !Number.isSafeInteger(redeemPoints) ||
    redeemPoints > maxPoints || redeemPoints % 100 !== 0;
  const totalCents = Math.max(0, totals.subtotal - (manual ?? 0) - (redemptionInvalid ? 0 : redeemPoints * 100));
  const partialCents = minorUnits(partial);
  const partialInvalid = paymentMode === "partial" &&
    (partialCents === null || partialCents <= 0 || partialCents >= totalCents || partialCents > 9_999_999_999);
  const paidCents = paymentMode === "full" ? totalCents : paymentMode === "partial" ? partialCents ?? 0 : 0;
  const dueCents = Math.max(0, totalCents - paidCents);
  const subtotal = totals.subtotal / 100;
  const discountNum = (manual ?? 0) / 100;
  const total = totalCents / 100;
  const canSubmit = cart.length > 0 && counterId !== "" && !discountInvalid && !redemptionInvalid
    && !partialInvalid && (paymentMode === "full" || (Boolean(customer?.phone) && totalCents > 0)) && !submitting;

  // ----- cart ops ----------------------------------------------------------
  function addToCart(product: ProductOut) {
    setReceipt(null);
    setErrorCode(null);
    setCart((prev) => {
      const found = prev.find((l) => l.product.id === product.id);
      if (found) {
        return prev.map((l) =>
          l.product.id === product.id ? { ...l, qty: l.qty + 1 } : l,
        );
      }
      return [...prev, { product, qty: 1 }];
    });
  }

  function setQty(productId: string, qty: number) {
    setCart((prev) =>
      qty <= 0
        ? prev.filter((l) => l.product.id !== productId)
        : prev.map((l) =>
            l.product.id === productId ? { ...l, qty } : l,
          ),
    );
  }

  function removeLine(productId: string) {
    setCart((prev) => prev.filter((l) => l.product.id !== productId));
  }

  function resetBill() {
    setCart([]);
    setCustomer(null);
    setCustomerQuery("");
    setCustomerSearch(null);
    setRedeemInput("");
    setPaymentMode("full");
    setPartial("");
    setUncertain(false);
    pending.current = null;
    setDiscount("0");
    setPayMethod("cash");
    setErrorCode(null);
    setReceipt(null);
    setConfirming(false);
    setIdemKey(newIdempotencyKey()); // a new bill gets a new idempotency key
    // A fresh bill starts at the top of the catalog, not wherever the last
    // modal happened to leave the page scrolled.
    if (typeof window !== "undefined") window.scrollTo({ top: 0 });
  }

  // ----- submit -------------------------------------------------------------
  async function submit() {
    if (submitting) return;
    setSubmitting(true);
    setErrorCode(null);
    const body: InvoiceCreate = pending.current ?? {
      counter_id: counterId,
      customer_id: customer?.id ?? null,
      items: cart.map((l) => ({
        product_id: l.product.id,
        quantity: String(l.qty),
        line_discount: "0",
      })),
      discount_total: discountNum.toFixed(2),
      payments: paidCents === 0 ? [] : [{ method: payMethod, ...(paymentMode === "partial" ? { amount: (paidCents / 100).toFixed(2) } : {}) }],
      allow_due: paymentMode !== "full",
      redeem_points: redeemPoints,
    };
    pending.current = body;
    try {
      const res = await fetch("/api/billing/invoices", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": idemKey,
        },
        body: JSON.stringify(body),
      });
      const payload = await res.json();
      if (!res.ok) {
        throw new ApiError(
          payload.error ?? `HTTP ${res.status}`,
          res.status,
          payload.code ?? "unknown",
          payload.details ?? {},
        );
      }
      pending.current = null;
      setUncertain(false);
      setReceipt(payload as InvoiceCreateOut);
      setConfirming(false);
    } catch (err) {
      if (!(err instanceof ApiError) || err.status >= 500) {
        setUncertain(true);
        setErrorCode("retryBill");
        return;
      }
      pending.current = null;
      setUncertain(false);
      setConfirming(false);
      if (err.status === 401) {
        router.replace("/login");
        return;
      }
      setErrorCode(err.code || "unknown");
    } finally {
      setSubmitting(false);
    }
  }

  // =========================================================================
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      {/* ------------------------- left: catalog ------------------------- */}
      <div className="min-w-0 lg:col-span-2">
        <div className="mb-4">
          <h1 className="text-xl font-bold text-[var(--color-ink)] sm:text-2xl">
            {t("title")}
          </h1>
          <p className="text-sm text-[var(--color-muted-foreground)]">
            {t("subtitle")}
          </p>
        </div>

        <Link href="/invoices" className={secondaryButton + " mb-3 mr-2"}>{receiptsText("history")}</Link>
        {cart.length > 0 && (
          <a href="#checkout-cart" className={secondaryButton + " sticky top-16 z-10 mb-3 lg:hidden"}>{t("viewCart", { count: cart.length })}</a>
        )}
        <label className="mb-4 flex min-h-[52px] items-center gap-3 rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] px-4">
              <Search className="h-5 w-5 text-[var(--color-muted-foreground)]" aria-hidden="true" />
              <input
                type="search"
                placeholder={t("searchProducts")}
                aria-label={t("searchProducts")}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="w-full bg-transparent text-base outline-none placeholder:text-[var(--color-muted-foreground)]"
              />
            </label>
            {filtered.length ? (
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4">
                {filtered.map((p) => {
                  const outOfStock = parseDecimal(p.stock_on_hand) <= 0;
                  return (
                    <button
                      key={p.id}
                      type="button"
                      disabled={outOfStock}
                      onClick={() => addToCart(p)}
                      data-testid="product-card"
                      data-sku={p.sku}
                      data-stock={p.stock_on_hand}
                      data-name={localizedName(p.name_en, p.name_bn, locale)}
                      className="min-h-[96px] cursor-pointer rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] p-3 text-left transition-colors duration-150 hover:border-[var(--color-primary)] hover:bg-[var(--color-primary-050)] disabled:opacity-50"
                    >
                      <p className="line-clamp-2 text-sm font-semibold">
                        {localizedName(p.name_en, p.name_bn, locale)}
                      </p>
                      <p className="mt-1 text-xs text-[var(--color-muted-foreground)]">
                        {p.sku} · {formatNumber(p.stock_on_hand, locale)} {p.unit}
                      </p>
                      <p className="mt-1 text-base font-bold text-[var(--color-primary)]">
                        {formatBDT(p.price, locale)}
                      </p>
                    </button>
                  );
                })}
              </div>
        ) : (
          <EmptyState title={t("emptyCart")} hint={t("emptyCartHint")} />
        )}
      </div>

      {/* ------------------------- right: cart -------------------------- */}
      <div id="checkout-cart" className="h-fit min-w-0 scroll-mt-28 lg:sticky lg:top-20">
      <Card>
        <CardHeader>
          <CardTitle>{t("cart")}</CardTitle>
          <Badge variant="outline">
            {t("itemsCount", { count: cart.reduce((n, l) => n + l.qty, 0) })}
          </Badge>
        </CardHeader>

        {/* counter selector */}
        <label className="mb-3 block">
          <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-[var(--color-muted-foreground)]">
            {t("counter")}
          </span>
          <select
            value={counterId}
            onChange={(e) => setCounterId(e.target.value)}
            className="min-h-[44px] w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-card)] px-3 text-sm font-medium"
          >
            {counters.map((c) => (
              <option key={c.id} value={c.id}>
                {c.code} · {localizedName(c.name_en, c.name_bn, locale)}
              </option>
            ))}
          </select>
        </label>

        <div className="mb-3 space-y-2">
          <label className="block text-sm font-medium">
            <span className="mb-1 block">{t("searchCustomers")}</span>
            <input type="search" value={customerQuery} maxLength={160} className={fieldClass}
              onChange={(event) => setCustomerQuery(event.target.value)} />
          </label>
          <div>
            <label htmlFor="billing-customer" className="mb-1 flex items-center gap-1 text-sm font-medium">
              <User size={15} aria-hidden="true" />{t("customer")}
            </label>
            <select id="billing-customer" value={customer?.id ?? ""} className={fieldClass}
              onChange={(event) => {
                const picked = candidates.find((row) => row.id === event.target.value) ?? null;
                setCustomer(picked);
                setRedeemInput("");
                if (!picked?.phone) setPaymentMode("full");
              }}>
              <option value="">{t("noCustomer")}</option>
              {candidates.map((row) => (
                <option key={row.id} value={row.id}>
                  {localizedName(row.name, row.name_bn, locale)}{row.phone ? " · " + row.phone : ""}
                </option>
              ))}
            </select>
          </div>
          {customerTerm && (
            <p className="text-xs text-[var(--color-muted-foreground)]" role="status">
              {loadingCustomers ? t("loadingCustomers") : customerSearch?.failed ? t("errors.network") :
                t("customerMatches", { count: customerOptions.length })}
            </p>
          )}
          {customer && <p className="text-sm font-medium">{t("openingPoints", { count: customer.points_balance })}</p>}
        </div>

        {/* cart lines */}
        {cart.length === 0 ? (
          <EmptyState title={t("emptyCart")} hint={t("emptyCartHint")} />
        ) : (
          <ul className="divide-y divide-[var(--color-border)]">
            {cart.map((l) => (
              <li key={l.product.id} className="flex items-center gap-2 py-2">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-semibold">
                    {localizedName(l.product.name_en, l.product.name_bn, locale)}
                  </p>
                  <p className="text-xs text-[var(--color-muted-foreground)]">
                    {formatBDT(l.product.price, locale)} {t("each")}
                  </p>
                </div>
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    aria-label={`${t("qty")} −`}
                    onClick={() => setQty(l.product.id, l.qty - 1)}
                    className="flex h-11 w-11 cursor-pointer items-center justify-center rounded-lg border border-[var(--color-border)] hover:bg-[var(--color-muted)]"
                  >
                    <Minus className="h-4 w-4" aria-hidden="true" />
                  </button>
                  <span className="w-6 text-center text-sm font-bold tabular-nums">
                    {l.qty}
                  </span>
                  <button
                    type="button"
                    aria-label={`${t("qty")} +`}
                    onClick={() => setQty(l.product.id, l.qty + 1)}
                    className="flex h-11 w-11 cursor-pointer items-center justify-center rounded-lg border border-[var(--color-border)] hover:bg-[var(--color-muted)]"
                  >
                    <Plus className="h-4 w-4" aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    aria-label={t("remove")}
                    onClick={() => removeLine(l.product.id)}
                    className="flex h-11 w-11 cursor-pointer items-center justify-center rounded-lg text-red-600 hover:bg-red-50"
                  >
                    <Trash2 className="h-4 w-4" aria-hidden="true" />
                  </button>
                </div>
                <p className="min-w-12 text-right text-sm font-bold tabular-nums">
                  {formatBDT(parseDecimal(l.product.price) * l.qty, locale)}
                </p>
              </li>
            ))}
          </ul>
        )}

        {/* discount */}
        <label className="mt-3 block">
          <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-[var(--color-muted-foreground)]">
            {t("discountLabel")}
          </span>
          <input
            inputMode="decimal"
            aria-invalid={discountInvalid}
            aria-describedby={discountInvalid ? "billing-discount-error" : undefined}
            value={discount}
            onChange={(e) => setDiscount(e.target.value)}
            className="min-h-[44px] w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-card)] px-3 text-sm font-medium tabular-nums"
          />
        </label>

        {discountInvalid && <p id="billing-discount-error" className="mt-1 text-sm text-red-700">{t("invalidDiscount")}</p>}

        {customer && canRedeem && (
          <div className="mt-3 space-y-1">
            <label className="block text-sm font-medium">
              <span className="mb-1 block">{t("redeem")}</span>
              <input inputMode="numeric" value={redeemInput} onChange={(event) => setRedeemInput(event.target.value)}
                className={fieldClass} placeholder="0" disabled={!maxPoints && !redeemInput}
                aria-invalid={redemptionInvalid} aria-describedby="billing-redemption-hint" />
            </label>
            <p id="billing-redemption-hint" className={"text-xs " + (redemptionInvalid ? "text-red-700" : "text-[var(--color-muted-foreground)]")}>
              {customer.points_balance < 300 ? t("redemptionLocked")
                : maxPoints ? t("redemptionRange", { max: maxPoints }) : t("redemptionIneligible")}
            </p>
          </div>
        )}

        {/* totals */}
        <dl className="mt-4 space-y-2 border-t border-[var(--color-border)] pt-4 text-sm">
          <div className="flex justify-between">
            <dt>{t("subtotal")}</dt>
            <dd className="tabular-nums">{formatBDT(subtotal, locale)}</dd>
          </div>
          <div className="flex justify-between">
            <dt>{t("discount")}</dt>
            <dd className="tabular-nums text-red-600">−{formatBDT(discountNum, locale)}</dd>
          </div>
          {!redemptionInvalid && redeemPoints > 0 && <div className="flex justify-between gap-2">
            <dt>{t("loyaltyDiscount")}</dt><dd className="tabular-nums">−{formatBDT(redeemPoints, locale)}</dd>
          </div>}
          <div className="flex justify-between text-base font-bold">
            <dt>{t("total")}</dt>
            <dd className="tabular-nums text-[var(--color-primary)]">
              {formatBDT(total, locale)}
            </dd>
          </div>
        </dl>

        <div className="mt-4 space-y-1">
          <label htmlFor="billing-payment-type" className="block text-sm font-medium">{t("paymentType")}</label>
          <select id="billing-payment-type" value={paymentMode} className={fieldClass}
            onChange={(event) => setPaymentMode(event.target.value as typeof paymentMode)}>
            <option value="full">{t("paymentFull")}</option>
            <option value="partial" disabled={!customer?.phone}>{t("paymentPartial")}</option>
            <option value="due" disabled={!customer?.phone}>{t("paymentDue")}</option>
          </select>
        </div>
        {!customer?.phone && <p className="mt-1 text-xs text-[var(--color-muted-foreground)]">{t("customerRequiredForDue")}</p>}
        {paymentMode === "partial" && (
          <div className="mt-3 space-y-1">
            <label htmlFor="billing-payment-amount" className="block text-sm font-medium">{t("amountReceived")}</label>
            <input id="billing-payment-amount" inputMode="decimal" value={partial} className={fieldClass}
              onChange={(event) => setPartial(event.target.value)} aria-invalid={partialInvalid && partial !== ""}
              aria-describedby={partialInvalid && partial !== "" ? "billing-partial-error" : undefined} />
            {partialInvalid && partial !== "" && <p id="billing-partial-error" className="text-xs text-red-700">{t("invalidPartial")}</p>}
          </div>
        )}
        {paymentMode !== "full" && <div className="mt-3 flex items-center justify-between gap-3 rounded-lg bg-amber-50 p-3 text-sm font-semibold text-amber-900">
          <span>{t("remainingDue")}</span><span className="tabular-nums">{formatBDT(dueCents / 100, locale)}</span>
        </div>}

        {paymentMode !== "due" && totalCents > 0 && <>
        <p className="mb-2 mt-4 text-xs font-semibold uppercase tracking-wide text-[var(--color-muted-foreground)]">
          {t("payWith")}
        </p>
        <div className="grid grid-cols-3 gap-2">
          {(["cash", "bkash", "nagad"] as PayMethod[]).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setPayMethod(m)}
              aria-pressed={payMethod === m}
              className={`min-h-[44px] cursor-pointer rounded-lg border text-xs font-semibold transition-colors duration-150 ${
                payMethod === m
                  ? "border-[var(--color-primary)] bg-[var(--color-primary)] text-white"
                  : "border-[var(--color-border)] hover:bg-[var(--color-primary-100)]"
              }`}
            >
              {t(`pay${m[0].toUpperCase()}${m.slice(1)}` as never)}
            </button>
          ))}
        </div>

        </>}

        {/* error surface */}
        {errorCode && !confirming ? (
          <p
            role="alert"
            data-testid="billing-error"
            className="mt-3 flex items-start gap-2 rounded-lg bg-red-50 px-3 py-2 text-sm font-medium text-red-700"
          >
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            {t.has("errors." + errorCode) ? t("errors." + errorCode) : t("errors.unknown")}
          </p>
        ) : null}

        {/* finalize */}
        <button
          type="button"
          disabled={!canSubmit}
          onClick={() => setConfirming(true)}
          className="mt-4 min-h-[52px] w-full cursor-pointer rounded-xl bg-[var(--color-primary)] text-base font-bold text-white transition-colors duration-150 hover:bg-[var(--color-primary-strong)] disabled:cursor-not-allowed disabled:opacity-50"
        >
          {t("finalize")}
        </button>
      </Card>
      </div>

      {/* ------------------------- confirm dialog ------------------------ */}
      {confirming && !receipt ? (
        <BillingDialog titleId="billing-confirm-title" dismiss={submitting || uncertain ? undefined : () => setConfirming(false)}>
          <div className="flex max-h-[90dvh] w-full max-w-md flex-col rounded-2xl bg-[var(--color-card)] shadow-xl">
            <div className="flex items-start justify-between p-5 pb-0">
              <h2 id="billing-confirm-title" className="text-lg font-bold">
                {t("reviewTitle")}
              </h2>
              <button
                type="button"
                aria-label={t("cancel")}
                onClick={() => setConfirming(false)}
                disabled={submitting || uncertain}
                className="grid size-11 shrink-0 cursor-pointer place-items-center rounded-lg hover:bg-[var(--color-muted)] disabled:opacity-50"
              >
                <X className="h-5 w-5" aria-hidden="true" />
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto px-5">
              <p className="mt-1 text-sm text-[var(--color-muted-foreground)]">
                {t("reviewBody")}
              </p>
              <dl className="mt-4 space-y-1 pb-4 text-sm">
                <div className="flex justify-between">
                  <dt>{t("subtotal")}</dt>
                  <dd className="tabular-nums">{formatBDT(subtotal, locale)}</dd>
                </div>
                <div className="flex justify-between">
                  <dt>{t("discount")}</dt>
                  <dd className="tabular-nums">−{formatBDT(discountNum, locale)}</dd>
                </div>
                {redeemPoints > 0 && <div className="flex justify-between gap-2">
                  <dt>{t("loyaltyDiscount")}</dt><dd className="tabular-nums">−{formatBDT(redeemPoints, locale)}</dd>
                </div>}
                <div className="flex justify-between text-base font-bold">
                  <dt>{t("total")}</dt>
                  <dd className="tabular-nums text-[var(--color-primary)]">
                    {formatBDT(total, locale)}
                  </dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt>{t("amountReceived")}</dt><dd>{formatBDT(paidCents / 100, locale)}</dd>
                </div>
                {dueCents > 0 && <div className="flex justify-between gap-2">
                  <dt>{t("remainingDue")}</dt><dd>{formatBDT(dueCents / 100, locale)}</dd>
                </div>}
                {paidCents > 0 && <div className="flex justify-between gap-2">
                  <dt>{t("payWith")}</dt>
                  <dd>{t(({ cash: "payCash", bkash: "payBkash", nagad: "payNagad" } as const)[payMethod])}</dd>
                </div>}
              </dl>
              {uncertain && <p role="alert" className="pb-3 text-sm text-red-700">{t("errors.retryBill")}</p>}
            </div>
            <div className="grid grid-cols-2 gap-2 border-t border-[var(--color-border)] p-4">
              <button
                type="button"
                onClick={() => setConfirming(false)}
                disabled={submitting || uncertain}
                className="min-h-[48px] rounded-xl border border-[var(--color-border)] text-sm font-semibold hover:bg-[var(--color-muted)] disabled:opacity-50"
              >
                {t("cancel")}
              </button>
              <button
                type="button"
                onClick={submit}
                disabled={submitting}
                className="min-h-[48px] rounded-xl bg-[var(--color-primary)] text-sm font-bold text-white hover:bg-[var(--color-primary-strong)] disabled:opacity-60"
              >
                {submitting ? t("processing") : uncertain ? t("retry") : t("confirm")}
              </button>
            </div>
          </div>
        </BillingDialog>
      ) : null}

      {/* ------------------------- success receipt ----------------------- */}
      {receipt ? (
        <BillingDialog titleId="billing-success-title" dismiss={resetBill}>
          <div className="max-h-[90dvh] w-full max-w-md overflow-y-auto rounded-2xl bg-[var(--color-card)] p-6 text-center shadow-xl">
            <CheckCircle2
              className="mx-auto h-14 w-14 text-[var(--color-primary)]"
              aria-hidden="true"
            />
            <h2 id="billing-success-title" className="mt-2 text-xl font-bold">
              {t("successTitle")}
            </h2>
            <p className="mt-1 text-sm text-[var(--color-muted-foreground)]">
              {t("successNumber", { number: receipt.invoice_number })}
            </p>
            <div className="mt-2"><Badge variant={receipt.payment_status === "paid" ? "success" : "warning"}>{customersText("paymentStatus." + receipt.payment_status)}</Badge></div>
            <dl className="mx-auto mt-4 max-w-xs space-y-1 text-sm">
              <div className="flex justify-between">
                <dt>{t("successTotal")}</dt>
                <dd className="font-bold tabular-nums">
                  {formatBDT(receipt.total, locale)}
                </dd>
              </div>
              {Number(receipt.loyalty_discount) > 0 && <div className="flex justify-between gap-2"><dt>{t("loyaltyDiscount")}</dt><dd>−{formatBDT(receipt.loyalty_discount, locale)}</dd></div>}
              <div className="flex justify-between gap-2"><dt>{t("amountReceived")}</dt><dd>{formatBDT(receipt.paid_total, locale)}</dd></div>
              <div className="flex justify-between gap-2"><dt>{t("remainingDue")}</dt><dd>{formatBDT(receipt.due_total, locale)}</dd></div>
              {receipt.loyalty_points_balance !== null && <>
                <div className="flex justify-between gap-2"><dt>{t("successPoints")}</dt><dd>+{receipt.loyalty_points_earned}</dd></div>
                <div className="flex justify-between gap-2"><dt>{t("successRedeemed")}</dt><dd>{receipt.loyalty_points_redeemed}</dd></div>
                <div className="flex justify-between gap-2"><dt>{t("successBalance")}</dt><dd>{receipt.loyalty_points_balance}</dd></div>
              </>}
            </dl>
            {Number(receipt.due_total) > 0 && receipt.loyalty_points_balance !== null && (
              <p className="mt-2 text-xs text-[var(--color-muted-foreground)]">{t("earnOnSettlement")}</p>
            )}
            <div className="mt-5 grid gap-2 sm:grid-cols-2">
              <Link className={primaryButton} href={`/invoices/${receipt.id}`}>{receiptsText("open")}</Link>
              <button type="button" onClick={resetBill} className={secondaryButton}>{t("newBill")}</button>
            </div>
          </div>
        </BillingDialog>
      ) : null}
    </div>
  );
}
