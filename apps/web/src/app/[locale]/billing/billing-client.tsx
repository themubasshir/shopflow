"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Search,
  User,
  Minus,
  Plus,
  Trash2,
  CheckCircle2,
  AlertTriangle,
  LogIn,
  LogOut,
  X,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { useRouter } from "@/i18n/navigation";
import { ApiError, newIdempotencyKey } from "@/lib/api-client";
import { formatBDT, localizedName, formatNumber } from "@/lib/format";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import type {
  CounterOut,
  CustomerOut,
  InvoiceCreate,
  InvoiceCreateOut,
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

export function BillingClient({
  locale,
  signedIn,
  products,
  counters,
  customers,
}: {
  locale: Locale;
  signedIn: boolean;
  products: ProductOut[];
  counters: CounterOut[];
  customers: CustomerOut[];
}) {
  const t = useTranslations("billing");
  const router = useRouter();

  // ----- session / sign-in -------------------------------------------------
  const [authed, setAuthed] = useState(signedIn);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [signingIn, setSigningIn] = useState(false);

  // ----- cart state --------------------------------------------------------
  const [query, setQuery] = useState("");
  const [cart, setCart] = useState<CartLine[]>([]);
  const [counterId, setCounterId] = useState(counters[0]?.id ?? "");
  const [customerId, setCustomerId] = useState("");
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

  const subtotal = useMemo(
    () => cart.reduce((sum, l) => sum + parseDecimal(l.product.price) * l.qty, 0),
    [cart],
  );
  const discountNum = Math.max(0, parseDecimal(discount));
  const total = Math.max(0, subtotal - discountNum);
  const canSubmit =
    authed && cart.length > 0 && counterId !== "" && total > 0 && !submitting;

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
    setCustomerId("");
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

  // ----- session ------------------------------------------------------------
  async function signIn(e: React.FormEvent) {
    e.preventDefault();
    setSigningIn(true);
    setErrorCode(null);
    try {
      const res = await fetch("/api/auth", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "login", email, password }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setErrorCode(body.code ?? "unauthenticated");
        return;
      }
      setAuthed(true);
      setPassword("");
    } catch {
      setErrorCode("network");
    } finally {
      setSigningIn(false);
    }
  }

  async function signOut() {
    await fetch("/api/auth", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "logout" }),
    }).catch(() => {});
    setAuthed(false);
    resetBill();
    router.refresh();
  }

  // ----- submit -------------------------------------------------------------
  async function submit() {
    setSubmitting(true);
    setErrorCode(null);
    const body: InvoiceCreate = {
      counter_id: counterId,
      customer_id: customerId || null,
      items: cart.map((l) => ({
        product_id: l.product.id,
        quantity: String(l.qty),
      })),
      discount_total: discountNum.toFixed(2),
      payments: [{ method: payMethod }],
    };
    try {
      const res = await fetch("/api/billing/invoices", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": idemKey,
        },
        body: JSON.stringify(body),
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new ApiError(
          payload.error ?? `HTTP ${res.status}`,
          res.status,
          payload.code ?? "unknown",
          payload.details ?? {},
        );
      }
      setReceipt(payload as InvoiceCreateOut);
      setConfirming(false);
      setCart([]);
    } catch (err) {
      setConfirming(false);
      if (err instanceof ApiError) {
        if (err.status === 401) setAuthed(false);
        setErrorCode(err.code || "unknown");
      } else {
        setErrorCode("network");
      }
    } finally {
      setSubmitting(false);
    }
  }

  // =========================================================================
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      {/* ------------------------- left: catalog ------------------------- */}
      <div className="min-w-0 lg:col-span-2">
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h1 className="text-xl font-bold text-[var(--color-ink)] sm:text-2xl">
              {t("title")}
            </h1>
            <p className="text-sm text-[var(--color-muted-foreground)]">
              {t("subtitle")}
            </p>
          </div>
          {authed ? (
            <button
              type="button"
              onClick={signOut}
              className="flex min-h-[40px] items-center gap-2 rounded-lg border border-[var(--color-border)] px-3 text-xs font-semibold text-[var(--color-muted-foreground)] hover:bg-[var(--color-muted)]"
            >
              <LogOut className="h-4 w-4" aria-hidden="true" />
              {t("signOut")}
            </button>
          ) : null}
        </div>

        {!authed ? (
          <Card className="mx-auto max-w-md">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <LogIn className="h-5 w-5 text-[var(--color-primary)]" aria-hidden="true" />
                {t("signInTitle")}
              </CardTitle>
            </CardHeader>
            <p className="mb-4 text-sm text-[var(--color-muted-foreground)]">
              {t("signInHint")}
            </p>
            <form onSubmit={signIn} className="space-y-3">
              <div>
                <label htmlFor="billing-email" className="mb-1 block text-xs font-semibold">
                  {t("email")}
                </label>
                <input
                  id="billing-email"
                  type="email"
                  required
                  autoComplete="username"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="min-h-[44px] w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-card)] px-3 text-base outline-none focus:border-[var(--color-primary)]"
                />
              </div>
              <div>
                <label htmlFor="billing-password" className="mb-1 block text-xs font-semibold">
                  {t("password")}
                </label>
                <input
                  id="billing-password"
                  type="password"
                  required
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="min-h-[44px] w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-card)] px-3 text-base outline-none focus:border-[var(--color-primary)]"
                />
              </div>
              {errorCode ? (
                <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm font-medium text-red-700">
                  {t(`errors.${errorCode}` as never)}
                </p>
              ) : null}
              <button
                type="submit"
                disabled={signingIn}
                className="min-h-[48px] w-full rounded-xl bg-[var(--color-primary)] text-base font-bold text-white transition-colors hover:bg-[var(--color-primary-strong)] disabled:opacity-60"
              >
                {signingIn ? t("signingIn") : t("signIn")}
              </button>
            </form>
          </Card>
        ) : (
          <>
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
                      className="min-h-[96px] rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] p-3 text-left transition-colors duration-150 hover:border-[var(--color-primary)] hover:bg-[var(--color-primary-050)] disabled:opacity-50"
                    >
                      <p className="line-clamp-2 text-sm font-semibold">
                        {localizedName(p.name_en, p.name_bn, locale)}
                      </p>
                      <p className="mt-1 text-xs text-[var(--color-muted-foreground)]">
                        {p.sku} · {formatNumber(p.stock_on_hand)} {p.unit}
                      </p>
                      <p className="mt-1 text-base font-bold text-[var(--color-primary)]">
                        {formatBDT(p.price)}
                      </p>
                    </button>
                  );
                })}
              </div>
            ) : (
              <EmptyState title={t("emptyCart")} hint={t("emptyCartHint")} />
            )}
          </>
        )}
      </div>

      {/* ------------------------- right: cart -------------------------- */}
      <Card className="h-fit min-w-0 lg:sticky lg:top-20">
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

        {/* customer selector */}
        <label className="mb-3 block">
          <span className="mb-1 flex items-center gap-1 text-xs font-semibold uppercase tracking-wide text-[var(--color-muted-foreground)]">
            <User className="h-3.5 w-3.5" aria-hidden="true" /> {t("customer")}
          </span>
          <select
            value={customerId}
            onChange={(e) => setCustomerId(e.target.value)}
            className="min-h-[44px] w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-card)] px-3 text-sm font-medium"
          >
            <option value="">{t("noCustomer")}</option>
            {customers.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
                {c.points_balance ? ` (${c.points_balance} pts)` : ""}
              </option>
            ))}
          </select>
        </label>

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
                    {formatBDT(l.product.price)} {t("each")}
                  </p>
                </div>
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    aria-label={`${t("qty")} −`}
                    onClick={() => setQty(l.product.id, l.qty - 1)}
                    className="flex h-8 w-8 items-center justify-center rounded-lg border border-[var(--color-border)] hover:bg-[var(--color-muted)]"
                  >
                    <Minus className="h-4 w-4" aria-hidden="true" />
                  </button>
                  <span className="w-10 text-center text-sm font-bold tabular-nums">
                    {l.qty}
                  </span>
                  <button
                    type="button"
                    aria-label={`${t("qty")} +`}
                    onClick={() => setQty(l.product.id, l.qty + 1)}
                    className="flex h-8 w-8 items-center justify-center rounded-lg border border-[var(--color-border)] hover:bg-[var(--color-muted)]"
                  >
                    <Plus className="h-4 w-4" aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    aria-label={t("remove")}
                    onClick={() => removeLine(l.product.id)}
                    className="ml-1 flex h-8 w-8 items-center justify-center rounded-lg text-red-600 hover:bg-red-50"
                  >
                    <Trash2 className="h-4 w-4" aria-hidden="true" />
                  </button>
                </div>
                <p className="w-16 text-right text-sm font-bold tabular-nums">
                  {formatBDT(parseDecimal(l.product.price) * l.qty)}
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
            type="number"
            min={0}
            step="0.01"
            value={discount}
            onChange={(e) => setDiscount(e.target.value)}
            className="min-h-[44px] w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-card)] px-3 text-sm font-medium tabular-nums"
          />
        </label>

        {/* totals */}
        <dl className="mt-4 space-y-2 border-t border-[var(--color-border)] pt-4 text-sm">
          <div className="flex justify-between">
            <dt>{t("subtotal")}</dt>
            <dd className="tabular-nums">{formatBDT(subtotal)}</dd>
          </div>
          <div className="flex justify-between">
            <dt>{t("discount")}</dt>
            <dd className="tabular-nums text-red-600">−{formatBDT(discountNum)}</dd>
          </div>
          <div className="flex justify-between text-base font-bold">
            <dt>{t("total")}</dt>
            <dd className="tabular-nums text-[var(--color-primary)]">
              {formatBDT(total)}
            </dd>
          </div>
        </dl>

        {/* payment method */}
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
              className={`min-h-[44px] rounded-lg border text-xs font-semibold transition-colors duration-150 ${
                payMethod === m
                  ? "border-[var(--color-primary)] bg-[var(--color-primary)] text-white"
                  : "border-[var(--color-border)] hover:bg-[var(--color-primary-100)]"
              }`}
            >
              {t(`pay${m[0].toUpperCase()}${m.slice(1)}` as never)}
            </button>
          ))}
        </div>

        {/* error surface */}
        {errorCode ? (
          <p
            role="alert"
            data-testid="billing-error"
            className="mt-3 flex items-start gap-2 rounded-lg bg-red-50 px-3 py-2 text-sm font-medium text-red-700"
          >
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            {t(`errors.${errorCode}` as never)}
          </p>
        ) : null}

        {/* finalize */}
        <button
          type="button"
          disabled={!canSubmit}
          onClick={() => setConfirming(true)}
          className="mt-4 min-h-[52px] w-full rounded-xl bg-[var(--color-primary)] text-base font-bold text-white transition-colors duration-150 hover:bg-[var(--color-primary-strong)] disabled:cursor-not-allowed disabled:opacity-50"
        >
          {t("finalize")}
        </button>
      </Card>

      {/* ------------------------- confirm dialog ------------------------ */}
      {confirming && !receipt ? (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="billing-confirm-title"
          className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-4 sm:items-center"
        >
          <div className="flex max-h-[90dvh] w-full max-w-md flex-col rounded-2xl bg-[var(--color-card)] shadow-xl">
            <div className="flex items-start justify-between p-5 pb-0">
              <h2 id="billing-confirm-title" className="text-lg font-bold">
                {t("reviewTitle")}
              </h2>
              <button
                type="button"
                aria-label={t("cancel")}
                onClick={() => setConfirming(false)}
                className="rounded-lg p-1 hover:bg-[var(--color-muted)]"
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
                  <dd className="tabular-nums">{formatBDT(subtotal)}</dd>
                </div>
                <div className="flex justify-between">
                  <dt>{t("discount")}</dt>
                  <dd className="tabular-nums">−{formatBDT(discountNum)}</dd>
                </div>
                <div className="flex justify-between text-base font-bold">
                  <dt>{t("total")}</dt>
                  <dd className="tabular-nums text-[var(--color-primary)]">
                    {formatBDT(total)}
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt>{t("payWith")}</dt>
                  <dd className="font-medium">
                    {t(`pay${payMethod[0].toUpperCase()}${payMethod.slice(1)}` as never)}
                  </dd>
                </div>
              </dl>
            </div>
            <div className="grid grid-cols-2 gap-2 border-t border-[var(--color-border)] p-4">
              <button
                type="button"
                onClick={() => setConfirming(false)}
                disabled={submitting}
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
                {submitting ? t("processing") : t("confirm")}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {/* ------------------------- success receipt ----------------------- */}
      {receipt ? (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="billing-success-title"
          className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-4 sm:items-center"
        >
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
            <dl className="mx-auto mt-4 max-w-xs space-y-1 text-sm">
              <div className="flex justify-between">
                <dt>{t("successTotal")}</dt>
                <dd className="font-bold tabular-nums">
                  {formatBDT(receipt.total)}
                </dd>
              </div>
              {receipt.loyalty_points_earned > 0 ? (
                <>
                  <div className="flex justify-between">
                    <dt>{t("successPoints")}</dt>
                    <dd className="font-medium">
                      +{receipt.loyalty_points_earned} pts
                    </dd>
                  </div>
                  <div className="flex justify-between">
                    <dt>{t("successBalance")}</dt>
                    <dd className="font-medium">
                      {receipt.loyalty_points_balance} pts
                    </dd>
                  </div>
                </>
              ) : null}
            </dl>
            <button
              type="button"
              onClick={resetBill}
              className="mt-6 min-h-[52px] w-full rounded-xl bg-[var(--color-primary)] text-base font-bold text-white hover:bg-[var(--color-primary-strong)]"
            >
              {t("newBill")}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
