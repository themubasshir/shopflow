"use client";

import { useState } from "react";
import { LogIn, AlertTriangle } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRouter } from "@/i18n/navigation";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";

export function LoginForm() {
  const t = useTranslations("login");
  const router = useRouter();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [errorCode, setErrorCode] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setErrorCode(null);
    try {
      const res = await fetch("/api/auth", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "login", email, password }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setErrorCode(body.code ?? mapStatus(res.status));
        return;
      }
      // Fresh cookie is set — refresh so the (app) layout re-verifies, then
      // land on the dashboard.
      router.refresh();
      router.replace("/");
    } catch {
      setErrorCode("network");
    } finally {
      setSubmitting(false);
    }
  }

  function mapStatus(status: number): string {
    if (status === 401) return "unauthenticated";
    if (status === 403) return "forbidden";
    if (status === 429) return "rate_limited";
    return "unknown";
  }

  return (
    <Card className="w-full max-w-md">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <LogIn className="h-5 w-5 text-[var(--color-primary)]" aria-hidden="true" />
          {t("title")}
        </CardTitle>
      </CardHeader>
      <p className="mb-4 text-sm text-[var(--color-muted-foreground)]">{t("subtitle")}</p>
      <form onSubmit={onSubmit} className="space-y-3" noValidate={false}>
        <div>
          <label htmlFor="login-email" className="mb-1 block text-xs font-semibold">
            {t("email")}
          </label>
          <input
            id="login-email"
            type="email"
            required
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="min-h-[44px] w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-card)] px-3 text-base outline-none focus:border-[var(--color-primary)]"
          />
        </div>
        <div>
          <label htmlFor="login-password" className="mb-1 block text-xs font-semibold">
            {t("password")}
          </label>
          <input
            id="login-password"
            type="password"
            required
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="min-h-[44px] w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-card)] px-3 text-base outline-none focus:border-[var(--color-primary)]"
          />
        </div>
        {errorCode ? (
          <p
            role="alert"
            className="flex items-start gap-2 rounded-lg bg-red-50 px-3 py-2 text-sm font-medium text-red-700"
          >
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            {t(`errors.${errorCode}` as never)}
          </p>
        ) : null}
        <button
          type="submit"
          disabled={submitting}
          className="min-h-[48px] w-full rounded-xl bg-[var(--color-primary)] text-base font-bold text-white transition-colors hover:bg-[var(--color-primary-strong)] disabled:opacity-60"
        >
          {submitting ? t("signingIn") : t("signIn")}
        </button>
      </form>
    </Card>
  );
}
