"use client";

import { useState, type FormEvent } from "react";
import {
  Copy,
  MonitorSmartphone,
  Plus,
  Printer as PrinterIcon,
  X,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { useRouter } from "@/i18n/navigation";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import {
  fieldClass,
  primaryButton,
  secondaryButton,
} from "@/components/ui/pos-form";
import { localizedName } from "@/lib/format";
import { cn } from "@/lib/utils";
import type {
  CounterOut,
  PrinterCreate,
  PrinterOut,
  PrinterUpdate,
} from "@/types";
import type { Locale } from "@/i18n/config";

type DialogKind =
  | { type: "add" }
  | { type: "edit"; printer: PrinterOut }
  | { type: "token"; printer: PrinterOut; token: string | null }
  | null;

export function PrintersClient({
  locale,
  printers,
  counters,
}: {
  locale: Locale;
  printers: PrinterOut[];
  counters: CounterOut[];
}) {
  const t = useTranslations("printers");
  const router = useRouter();
  const [dialog, setDialog] = useState<DialogKind>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  function refresh() {
    setDialog(null);
    router.refresh();
  }

  async function call(path: string, init: RequestInit): Promise<boolean> {
    setError(null);
    try {
      const res = await fetch(path, {
        headers: { "Content-Type": "application/json" },
        ...init,
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setError(body.code ?? "unknown");
        return false;
      }
      return true;
    } catch {
      setError("network");
      return false;
    }
  }

  async function toggleEnabled(printer: PrinterOut) {
    if (pendingId) return;
    setPendingId(printer.id);
    await call(`/api/printing/printers/${printer.id}`, {
      method: "PATCH",
      body: JSON.stringify({ is_enabled: !printer.is_enabled }),
    });
    setPendingId(null);
    router.refresh();
  }

  async function testPage(printer: PrinterOut) {
    if (pendingId) return;
    setPendingId(printer.id);
    await call(`/api/printing/printers/${printer.id}/test-page`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    setPendingId(null);
    router.refresh();
  }

  const counterName = (id: string) => {
    const c = counters.find((x) => x.id === id);
    return c ? `${c.code} · ${localizedName(c.name_en, c.name_bn, locale)}` : id;
  };

  return (
    <>
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-[var(--color-muted-foreground)]">
          {printers.length === 0 ? t("none") : t("count", { count: printers.length })}
        </p>
        <button
          type="button"
          onClick={() => setDialog({ type: "add" })}
          className={primaryButton}
        >
          <Plus size={18} aria-hidden="true" />
          {t("add")}
        </button>
      </div>

      {error ? (
        <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm font-medium text-red-700">
          {t(`errors.${error}` as never)}
        </p>
      ) : null}

      {printers.length === 0 ? (
        <EmptyState title={t("empty")} hint={t("emptyHint")} />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {printers.map((p) => (
            <Card
              key={p.id}
              data-printer-id={p.id}
              className={cn("min-w-0", !p.is_enabled && "opacity-70")}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 items-center gap-3">
                  <div
                    className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl ${
                      p.is_enabled
                        ? "bg-[var(--color-primary-100)] text-[var(--color-primary-strong)]"
                        : "bg-[var(--color-muted)] text-[var(--color-muted-foreground)]"
                    }`}
                  >
                    <PrinterIcon className="h-5 w-5" aria-hidden="true" />
                  </div>
                  <div className="min-w-0">
                    <p className="truncate font-semibold">{p.name}</p>
                    <div className="mt-1 flex flex-wrap items-center gap-1">
                      <Badge variant={p.is_enabled ? "success" : "danger"}>
                        {p.is_enabled ? t("enabled") : t("disabled")}
                      </Badge>
                      <Badge variant="outline">{t(`transport.${p.transport}`)}</Badge>
                    </div>
                  </div>
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-checked={p.is_enabled}
                  aria-label={p.is_enabled ? t("disable") : t("enable")}
                  disabled={pendingId === p.id}
                  onClick={() => void toggleEnabled(p)}
                  className={`relative h-7 w-12 shrink-0 rounded-full transition-colors disabled:opacity-50 ${
                    p.is_enabled ? "bg-[var(--color-primary)]" : "bg-[var(--color-muted)]"
                  }`}
                >
                  <span
                    className={`absolute top-1 h-5 w-5 rounded-full bg-white shadow transition-transform ${
                      p.is_enabled ? "left-6" : "left-1"
                    }`}
                  />
                </button>
              </div>

              <dl className="mt-3 space-y-1 border-t border-[var(--color-border)] pt-3 text-xs">
                <div className="flex flex-wrap justify-between gap-x-3">
                  <dt className="text-[var(--color-muted-foreground)]">{t("agentId")}</dt>
                  <dd className="min-w-0 break-all text-right font-mono font-medium">
                    {p.agent_id}
                  </dd>
                </div>
                <div className="flex flex-wrap justify-between gap-x-3">
                  <dt className="text-[var(--color-muted-foreground)]">{t("paper")}</dt>
                  <dd className="min-w-0 text-right">
                    {p.paper_width_mm} mm · {p.dots_width} dots · {p.dpi} dpi
                    {p.has_cutter ? " · " + t("cutter") : ""}
                  </dd>
                </div>
                <div className="flex flex-wrap justify-between gap-x-3">
                  <dt className="text-[var(--color-muted-foreground)]">{t("language")}</dt>
                  <dd className="min-w-0 text-right">{t(`languages.${p.default_language}`)}</dd>
                </div>
                <div className="flex flex-wrap justify-between gap-x-3">
                  <dt className="text-[var(--color-muted-foreground)]">{t("counters")}</dt>
                  <dd className="min-w-0 text-right">
                    {p.counter_ids.length
                      ? p.counter_ids.map(counterName).join(", ")
                      : t("noCounters")}
                  </dd>
                </div>
              </dl>

              <div className="mt-3 flex flex-wrap gap-1 border-t border-[var(--color-border)] pt-3">
                <RowBtn onClick={() => setDialog({ type: "edit", printer: p })}>
                  {t("edit")}
                </RowBtn>
                <RowBtn onClick={() => void testPage(p)} disabled={pendingId === p.id}>
                  {pendingId === p.id ? t("printing") : t("testPage")}
                </RowBtn>
                <RowBtn
                  onClick={async () => {
                    const res = await fetch(
                      `/api/printing/printers/${p.id}/rotate-token`,
                      { method: "POST" },
                    );
                    if (res.ok) {
                      const body = await res.json();
                      setDialog({
                        type: "token",
                        printer: p,
                        token: body.agent_token ?? null,
                      });
                    } else {
                      setError("unknown");
                    }
                  }}
                >
                  {t("rotate")}
                </RowBtn>
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* Counter ↔ printer assignment */}
      <Card>
        <h2 className="mb-3 flex items-center gap-2 text-base font-semibold">
          <MonitorSmartphone size={18} aria-hidden="true" />
          {t("assign")}
        </h2>
        <p className="mb-3 text-xs text-[var(--color-muted-foreground)]">{t("assignHint")}</p>
        <ul className="divide-y divide-[var(--color-border)]">
          {counters.map((counter) => (
            <li key={counter.id} className="flex items-center justify-between gap-3 py-2.5">
              <span className="min-w-0 truncate text-sm font-medium">
                {counter.code} · {localizedName(counter.name_en, counter.name_bn, locale)}
                {!counter.is_active ? (
                  <Badge variant="outline" className="ml-2">
                    {t("inactive")}
                  </Badge>
                ) : null}
              </span>
              <select
                className={fieldClass + " max-w-48"}
                aria-label={t("assign") + " " + counter.code}
                value={printers.find((p) => p.counter_ids.includes(counter.id))?.id ?? ""}
                onChange={async (event) => {
                  const printerId = event.target.value || null;
                  await call(`/api/printing/counters/${counter.id}/printer`, {
                    method: "PUT",
                    body: JSON.stringify({ printer_id: printerId }),
                  });
                  router.refresh();
                }}
              >
                <option value="">{t("unassigned")}</option>
                {printers.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </li>
          ))}
        </ul>
      </Card>

      {dialog?.type === "add" || dialog?.type === "edit" ? (
        <PrinterForm
          locale={locale}
          printer={dialog.type === "edit" ? dialog.printer : undefined}
          onClose={() => setDialog(null)}
          onSaved={refresh}
          onToken={(printer, token) => setDialog({ type: "token", printer, token })}
        />
      ) : null}
      {dialog?.type === "token" ? (
        <TokenDialog
          printer={dialog.printer}
          token={dialog.token}
          onClose={() => setDialog(null)}
        />
      ) : null}
    </>
  );
}

function RowBtn({
  children,
  onClick,
  disabled,
  danger,
}: {
  children: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`min-h-[36px] rounded-lg px-2.5 text-xs font-semibold transition-colors disabled:opacity-50 ${
        danger
          ? "text-red-600 hover:bg-red-50"
          : "text-[var(--color-primary)] hover:bg-[var(--color-primary-100)]"
      }`}
    >
      {children}
    </button>
  );
}

function Dialog({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-4 sm:items-center"
    >
      <div className="flex max-h-[90dvh] w-full max-w-lg flex-col rounded-2xl bg-[var(--color-card)] shadow-xl">
        <div className="flex items-start justify-between p-5 pb-0">
          <h2 className="text-lg font-bold">{title}</h2>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="rounded-lg p-1 hover:bg-[var(--color-muted)]"
          >
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-5">{children}</div>
      </div>
    </div>
  );
}

function PrinterForm({
  locale,
  printer,
  onClose,
  onSaved,
  onToken,
}: {
  locale: Locale;
  printer?: PrinterOut;
  onClose: () => void;
  onSaved: () => void;
  onToken: (printer: PrinterOut, token: string) => void;
}) {
  const t = useTranslations("printers");
  const isEdit = Boolean(printer);
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const value = (key: string) => String(data.get(key) ?? "").trim();
    const num = (key: string) => {
      const n = Number(value(key));
      return Number.isFinite(n) && n > 0 ? n : undefined;
    };
    setSubmitting(true);
    setErr(null);
    try {
      const config =
        value("host") || value("port")
          ? {
              host: value("host") || undefined,
              port: num("port") ?? 9100,
            }
          : null;
      if (isEdit) {
        const body: PrinterUpdate = {
          name: value("name"),
          transport: value("transport") as PrinterUpdate["transport"],
          agent_id: value("agent_id"),
          paper_width_mm: num("paper_width_mm"),
          dots_width: num("dots_width"),
          dpi: num("dpi"),
          has_cutter: data.get("has_cutter") === "on",
          is_enabled: data.get("is_enabled") === "on",
          default_language: value("default_language") as PrinterUpdate["default_language"],
          config,
        };
        const res = await fetch(`/api/printing/printers/${printer!.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!res.ok) {
          const p = await res.json().catch(() => ({}));
          setErr(p.code ?? "unknown");
          return;
        }
      } else {
        const body: PrinterCreate = {
          name: value("name"),
          transport: value("transport") as PrinterCreate["transport"],
          agent_id: value("agent_id"),
          paper_width_mm: num("paper_width_mm"),
          dots_width: num("dots_width"),
          dpi: num("dpi"),
          has_cutter: data.get("has_cutter") === "on",
          is_enabled: data.get("is_enabled") === "on",
          default_language: value("default_language") as PrinterCreate["default_language"],
          config,
        };
        const res = await fetch("/api/printing/printers", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!res.ok) {
          const p = await res.json().catch(() => ({}));
          setErr(p.code ?? "unknown");
          return;
        }
        const created = (await res.json()) as { printer: PrinterOut; agent_token: string };
        onToken(created.printer, created.agent_token);
        return;
      }
      onSaved();
    } catch {
      setErr("network");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog title={isEdit ? t("editTitle") : t("addTitle")} onClose={onClose}>
      <form onSubmit={submit} className="space-y-3">
        <div>
          <label className="mb-1 block text-xs font-semibold" htmlFor="pf-name">
            {t("fields.name")}
          </label>
          <input
            id="pf-name"
            name="name"
            required
            defaultValue={printer?.name ?? ""}
            className={fieldClass}
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="mb-1 block text-xs font-semibold" htmlFor="pf-transport">
              {t("fields.transport")}
            </label>
            <select
              id="pf-transport"
              name="transport"
              defaultValue={printer?.transport ?? "network"}
              className={fieldClass}
            >
              <option value="network">{t("transport.network")}</option>
              <option value="bluetooth">{t("transport.bluetooth")}</option>
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs font-semibold" htmlFor="pf-agent">
              {t("fields.agentId")}
            </label>
            <input
              id="pf-agent"
              name="agent_id"
              required
              defaultValue={printer?.agent_id ?? ""}
              className={fieldClass}
            />
          </div>
        </div>
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="mb-1 block text-xs font-semibold" htmlFor="pf-paper">
              {t("fields.paperWidth")}
            </label>
            <input
              id="pf-paper"
              name="paper_width_mm"
              type="number"
              min={48}
              max={210}
              defaultValue={printer?.paper_width_mm ?? 80}
              className={fieldClass}
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-semibold" htmlFor="pf-dots">
              {t("fields.dotsWidth")}
            </label>
            <input
              id="pf-dots"
              name="dots_width"
              type="number"
              min={200}
              max={2048}
              defaultValue={printer?.dots_width ?? 576}
              className={fieldClass}
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-semibold" htmlFor="pf-dpi">
              {t("fields.dpi")}
            </label>
            <input
              id="pf-dpi"
              name="dpi"
              type="number"
              min={100}
              max={1200}
              defaultValue={printer?.dpi ?? 203}
              className={fieldClass}
            />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="mb-1 block text-xs font-semibold" htmlFor="pf-host">
              {t("fields.host")}
            </label>
            <input
              id="pf-host"
              name="host"
              placeholder={locale === "bn" ? "192.168.0.50" : "192.168.0.50"}
              defaultValue={(printer as unknown as PrinterCreate)?.config?.host ?? ""}
              className={fieldClass}
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-semibold" htmlFor="pf-port">
              {t("fields.port")}
            </label>
            <input
              id="pf-port"
              name="port"
              type="number"
              min={1}
              max={65535}
              placeholder="9100"
              defaultValue={(printer as unknown as PrinterCreate)?.config?.port ?? 9100}
              className={fieldClass}
            />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="mb-1 block text-xs font-semibold" htmlFor="pf-lang">
              {t("fields.language")}
            </label>
            <select
              id="pf-lang"
              name="default_language"
              defaultValue={printer?.default_language ?? "bilingual"}
              className={fieldClass}
            >
              <option value="en">{t("languages.en")}</option>
              <option value="bn">{t("languages.bn")}</option>
              <option value="bilingual">{t("languages.bilingual")}</option>
            </select>
          </div>
          <div className="flex items-end gap-4 pb-1">
            <label className="flex items-center gap-2 text-sm font-medium">
              <input
                type="checkbox"
                name="has_cutter"
                defaultChecked={printer?.has_cutter ?? true}
                className="h-4 w-4 accent-[var(--color-primary)]"
              />
              {t("fields.cutter")}
            </label>
            <label className="flex items-center gap-2 text-sm font-medium">
              <input
                type="checkbox"
                name="is_enabled"
                defaultChecked={printer?.is_enabled ?? true}
                className="h-4 w-4 accent-[var(--color-primary)]"
              />
              {t("fields.enabled")}
            </label>
          </div>
        </div>
        {err ? (
          <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm font-medium text-red-700">
            {t(`errors.${err}` as never)}
          </p>
        ) : null}
        <div className="grid grid-cols-2 gap-2 pt-1">
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className={secondaryButton}
          >
            {t("cancel")}
          </button>
          <button type="submit" disabled={submitting} className={primaryButton}>
            {submitting ? t("saving") : isEdit ? t("save") : t("create")}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function TokenDialog({
  printer,
  token,
  onClose,
}: {
  printer: PrinterOut;
  token: string | null;
  onClose: () => void;
}) {
  const t = useTranslations("printers");
  const [copied, setCopied] = useState(false);

  async function copy() {
    if (!token) return;
    try {
      await navigator.clipboard.writeText(`${printer.agent_id}\n${token}`);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <Dialog title={t("tokenTitle")} onClose={onClose}>
      <p className="mb-3 text-sm text-[var(--color-muted-foreground)]">
        {t("tokenBody", { name: printer.name })}
      </p>
      <div className="space-y-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-muted)] p-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-[var(--color-muted-foreground)]">
            {t("agentId")}
          </p>
          <p className="break-all font-mono text-sm">{printer.agent_id}</p>
        </div>
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-[var(--color-muted-foreground)]">
            {t("token")}
          </p>
          <p className="break-all font-mono text-sm">{token ?? t("tokenHidden")}</p>
        </div>
      </div>
      <p className="mt-3 text-xs text-[var(--color-muted-foreground)]">{t("tokenHint")}</p>
      <div className="mt-4 grid grid-cols-2 gap-2">
        <button type="button" onClick={onClose} className={secondaryButton}>
          {t("done")}
        </button>
        <button
          type="button"
          onClick={() => void copy()}
          disabled={!token}
          className={primaryButton}
        >
          <Copy size={16} aria-hidden="true" />
          {copied ? t("copied") : t("copy")}
        </button>
      </div>
    </Dialog>
  );
}
