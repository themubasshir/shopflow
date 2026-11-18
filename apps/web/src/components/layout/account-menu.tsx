"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown, KeyRound, LogOut, UserCircle2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRouter } from "@/i18n/navigation";
import { Badge } from "@/components/ui/badge";
import type { Me } from "@/lib/session";

/**
 * Header account menu: shows the signed-in name + role, and exposes
 * "Change password" (opens a dialog) and "Sign out". All writes go through
 * /api/auth — the JWT never touches browser JS.
 */
export function AccountMenu({ me }: { me: Me }) {
  const t = useTranslations("account");
  const tNav = useTranslations("nav");
  const router = useRouter();

  const [open, setOpen] = useState(false);
  const [pwOpen, setPwOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // close on outside click / escape
  useEffect(() => {
    if (!open) return;
    function onClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  async function signOut() {
    if (signingOut) return;
    setSigningOut(true);
    await fetch("/api/auth", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "logout" }),
    }).catch(() => {});
    router.refresh();
    router.replace("/login");
  }

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="flex min-h-[44px] items-center gap-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-card)] px-3 text-sm font-semibold text-[var(--color-ink)] transition-colors hover:bg-[var(--color-primary-100)]"
      >
        <UserCircle2 className="h-5 w-5 text-[var(--color-primary)]" aria-hidden="true" />
        <span className="hidden max-w-[140px] truncate sm:inline">{me.name}</span>
        <ChevronDown className="h-4 w-4 text-[var(--color-muted-foreground)]" aria-hidden="true" />
      </button>

      {open ? (
        <div
          role="menu"
          className="absolute right-0 z-50 mt-2 w-60 overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] shadow-lg"
        >
          <div className="border-b border-[var(--color-border)] px-4 py-3">
            <p className="truncate text-sm font-bold text-[var(--color-ink)]">{me.name}</p>
            <p className="truncate text-xs text-[var(--color-muted-foreground)]">{me.email}</p>
            <Badge variant="success" className="mt-2">
              {tNav(`roles.${me.role}` as never)}
            </Badge>
          </div>
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              setPwOpen(true);
            }}
            className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm font-medium hover:bg-[var(--color-primary-050)]"
          >
            <KeyRound className="h-4 w-4" aria-hidden="true" />
            {t("changePassword")}
          </button>
          <button
            type="button"
            role="menuitem"
            onClick={signOut}
            disabled={signingOut}
            className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm font-medium text-red-600 hover:bg-red-50 disabled:opacity-60"
          >
            <LogOut className="h-4 w-4" aria-hidden="true" />
            {signingOut ? t("signingOut") : t("signOut")}
          </button>
        </div>
      ) : null}

      {pwOpen ? <ChangePasswordDialog onClose={() => setPwOpen(false)} /> : null}
    </div>
  );
}

function ChangePasswordDialog({ onClose }: { onClose: () => void }) {
  const t = useTranslations("account");
  const router = useRouter();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [errorCode, setErrorCode] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setErrorCode(null);
    try {
      const res = await fetch("/api/auth", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "password",
          current_password: current,
          new_password: next,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setErrorCode(body.code ?? "unknown");
        return;
      }
      setDone(true);
      router.refresh();
    } catch {
      setErrorCode("network");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="change-pw-title"
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-4 sm:items-center"
    >
      <div className="w-full max-w-md rounded-2xl bg-[var(--color-card)] p-5 shadow-xl">
        <h2 id="change-pw-title" className="text-lg font-bold">
          {t("changePassword")}
        </h2>
        {done ? (
          <div className="py-4">
            <p className="text-sm font-medium text-[var(--color-primary-strong)]">
              {t("passwordChanged")}
            </p>
            <button
              type="button"
              onClick={onClose}
              className="mt-4 min-h-[44px] w-full rounded-xl bg-[var(--color-primary)] text-sm font-bold text-white hover:bg-[var(--color-primary-strong)]"
            >
              {t("done")}
            </button>
          </div>
        ) : (
          <form onSubmit={submit} className="mt-3 space-y-3">
            <div>
              <label htmlFor="pw-current" className="mb-1 block text-xs font-semibold">
                {t("currentPassword")}
              </label>
              <input
                id="pw-current"
                type="password"
                required
                autoComplete="current-password"
                value={current}
                onChange={(e) => setCurrent(e.target.value)}
                className="min-h-[44px] w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-card)] px-3 text-base outline-none focus:border-[var(--color-primary)]"
              />
            </div>
            <div>
              <label htmlFor="pw-new" className="mb-1 block text-xs font-semibold">
                {t("newPassword")}
              </label>
              <input
                id="pw-new"
                type="password"
                required
                autoComplete="new-password"
                value={next}
                onChange={(e) => setNext(e.target.value)}
                className="min-h-[44px] w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-card)] px-3 text-base outline-none focus:border-[var(--color-primary)]"
              />
            </div>
            {errorCode ? (
              <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm font-medium text-red-700">
                {t(`errors.${errorCode}` as never)}
              </p>
            ) : null}
            <div className="grid grid-cols-2 gap-2 pt-1">
              <button
                type="button"
                onClick={onClose}
                disabled={submitting}
                className="min-h-[44px] rounded-xl border border-[var(--color-border)] text-sm font-semibold hover:bg-[var(--color-muted)] disabled:opacity-50"
              >
                {t("cancel")}
              </button>
              <button
                type="submit"
                disabled={submitting}
                className="min-h-[44px] rounded-xl bg-[var(--color-primary)] text-sm font-bold text-white hover:bg-[var(--color-primary-strong)] disabled:opacity-60"
              >
                {submitting ? t("saving") : t("save")}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
