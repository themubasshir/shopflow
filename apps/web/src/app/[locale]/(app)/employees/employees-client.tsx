"use client";

import { useState } from "react";
import { UserPlus, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRouter } from "@/i18n/navigation";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { formatDate, localizedName } from "@/lib/format";
import type { CounterOut, EmployeeOut, RoleOut } from "@/types";
import type { Locale } from "@/i18n/config";

type DialogKind =
  | { type: "add" }
  | { type: "edit"; emp: EmployeeOut }
  | { type: "toggle"; emp: EmployeeOut }
  | { type: "reset"; emp: EmployeeOut }
  | { type: "counters"; emp: EmployeeOut }
  | null;

export function EmployeesClient({
  locale,
  employees,
  roles,
  counters,
}: {
  locale: Locale;
  employees: EmployeeOut[];
  roles: RoleOut[];
  counters: CounterOut[];
}) {
  const t = useTranslations("employees");
  const tStates = useTranslations("states");
  const router = useRouter();
  const [dialog, setDialog] = useState<DialogKind>(null);
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

  const counterName = (id: string) => {
    const c = counters.find((x) => x.id === id);
    return c ? `${c.code} · ${localizedName(c.name_en, c.name_bn, locale)}` : id;
  };

  return (
    <>
      <div className="flex justify-end">
        <button
          type="button"
          onClick={() => setDialog({ type: "add" })}
          className="inline-flex min-h-[44px] items-center gap-2 rounded-xl bg-[var(--color-primary)] px-4 text-sm font-bold text-white hover:bg-[var(--color-primary-strong)]"
        >
          <UserPlus className="h-4 w-4" aria-hidden="true" />
          {t("add")}
        </button>
      </div>

      {error ? (
        <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm font-medium text-red-700">
          {t(`errors.${error}` as never)}
        </p>
      ) : null}

      {employees.length === 0 ? (
        <EmptyState title={tStates("empty")} hint={tStates("emptyHint")} />
      ) : (
        <Card className="p-0">
          <div className="table-scroll overflow-x-auto">
            <table className="w-full min-w-[760px] text-left text-sm">
              <thead>
                <tr className="border-b border-[var(--color-border)] text-xs uppercase tracking-wide text-[var(--color-muted-foreground)]">
                  <th className="px-4 py-3 font-medium">{t("colName")}</th>
                  <th className="px-4 py-3 font-medium">{t("colEmail")}</th>
                  <th className="px-4 py-3 font-medium">{t("colRole")}</th>
                  <th className="px-4 py-3 font-medium">{t("colCounters")}</th>
                  <th className="px-4 py-3 font-medium">{t("colStatus")}</th>
                  <th className="px-4 py-3 font-medium">{t("colLastLogin")}</th>
                  <th className="px-4 py-3 text-right font-medium">{t("colActions")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--color-border)]">
                {employees.map((e) => (
                  <tr key={e.id} className={!e.is_active ? "opacity-60" : undefined}>
                    <td className="px-4 py-3 font-semibold">{e.name}</td>
                    <td className="px-4 py-3 text-xs text-[var(--color-muted-foreground)]">
                      {e.email}
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant="default">
                        {localizedName(e.role_name_en, e.role_name_bn, locale)}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 text-xs">
                      {e.assigned_counter_ids.length
                        ? e.assigned_counter_ids.map(counterName).join(", ")
                        : t("allCounters")}
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant={e.is_active ? "success" : "danger"}>
                        {e.is_active ? t("active") : t("disabled")}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 text-xs tabular-nums">
                      {formatDate(e.last_login_at, locale)}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex justify-end gap-1">
                        <RowBtn onClick={() => setDialog({ type: "edit", emp: e })}>
                          {t("edit")}
                        </RowBtn>
                        <RowBtn onClick={() => setDialog({ type: "counters", emp: e })}>
                          {t("assignCounters")}
                        </RowBtn>
                        <RowBtn onClick={() => setDialog({ type: "reset", emp: e })}>
                          {t("resetPassword")}
                        </RowBtn>
                        <RowBtn
                          danger={e.is_active}
                          onClick={() => setDialog({ type: "toggle", emp: e })}
                        >
                          {e.is_active ? t("disable") : t("enable")}
                        </RowBtn>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {dialog?.type === "add" ? (
        <EmployeeForm
          roles={roles}
          counters={counters}
          locale={locale}
          onClose={() => setDialog(null)}
          onSaved={refresh}
        />
      ) : null}
      {dialog?.type === "edit" ? (
        <EmployeeForm
          roles={roles}
          counters={counters}
          locale={locale}
          emp={dialog.emp}
          onClose={() => setDialog(null)}
          onSaved={refresh}
        />
      ) : null}
      {dialog?.type === "toggle" ? (
        <ConfirmToggle
          emp={dialog.emp}
          onClose={() => setDialog(null)}
          onDone={refresh}
          call={call}
        />
      ) : null}
      {dialog?.type === "reset" ? (
        <ResetPassword emp={dialog.emp} onClose={() => setDialog(null)} onDone={refresh} />
      ) : null}
      {dialog?.type === "counters" ? (
        <AssignCounters
          emp={dialog.emp}
          counters={counters}
          locale={locale}
          onClose={() => setDialog(null)}
          onDone={refresh}
        />
      ) : null}
    </>
  );
}

function RowBtn({
  children,
  onClick,
  danger,
}: {
  children: React.ReactNode;
  onClick: () => void;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`min-h-[36px] rounded-lg px-2.5 text-xs font-semibold transition-colors ${
        danger
          ? "text-red-600 hover:bg-red-50"
          : "text-[var(--color-primary)] hover:bg-[var(--color-primary-100)]"
      }`}
    >
      {children}
    </button>
  );
}

/** Shared dialog shell. */
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

const inputCls =
  "min-h-[44px] w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-card)] px-3 text-sm outline-none focus:border-[var(--color-primary)]";
const labelCls = "mb-1 block text-xs font-semibold";

function EmployeeForm({
  roles,
  counters,
  locale,
  emp,
  onClose,
  onSaved,
}: {
  roles: RoleOut[];
  counters: CounterOut[];
  locale: Locale;
  emp?: EmployeeOut;
  onClose: () => void;
  onSaved: () => void;
}) {
  const t = useTranslations("employees");
  const router = useRouter();
  const isEdit = Boolean(emp);
  const [name, setName] = useState(emp?.name ?? "");
  const [email, setEmail] = useState(emp?.email ?? "");
  const [phone, setPhone] = useState(emp?.phone ?? "");
  const [roleId, setRoleId] = useState(
    emp ? (roles.find((r) => r.code === emp.role_code)?.id ?? roles[0]?.id ?? "") : roles[0]?.id ?? "",
  );
  const [password, setPassword] = useState("");
  const [prefLocale, setPrefLocale] = useState<"en" | "bn">(emp?.preferred_locale ?? "en");
  const [counterIds, setCounterIds] = useState<string[]>(emp?.assigned_counter_ids ?? []);
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function toggleCounter(id: string) {
    setCounterIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setErr(null);
    const url = isEdit ? `/api/employees/${emp!.id}` : "/api/employees";
    const method = isEdit ? "PATCH" : "POST";
    const body = isEdit
      ? { name, phone: phone || null, role_id: roleId, preferred_locale: prefLocale }
      : {
          name,
          email,
          phone: phone || null,
          role_id: roleId,
          password,
          preferred_locale: prefLocale,
          counter_ids: counterIds,
        };
    const res = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    setSubmitting(false);
    if (!res.ok) {
      const p = await res.json().catch(() => ({}));
      setErr(p.code ?? "unknown");
      return;
    }
    router.refresh();
    onSaved();
  }

  return (
    <Dialog title={isEdit ? t("editTitle") : t("addTitle")} onClose={onClose}>
      <form onSubmit={submit} className="space-y-3">
        <div>
          <label className={labelCls} htmlFor="ef-name">{t("name")}</label>
          <input id="ef-name" required value={name} onChange={(e) => setName(e.target.value)} className={inputCls} />
        </div>
        {!isEdit ? (
          <div>
            <label className={labelCls} htmlFor="ef-email">{t("email")}</label>
            <input id="ef-email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} className={inputCls} />
          </div>
        ) : null}
        <div>
          <label className={labelCls} htmlFor="ef-phone">{t("phone")}</label>
          <input id="ef-phone" value={phone} onChange={(e) => setPhone(e.target.value)} className={inputCls} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelCls} htmlFor="ef-role">{t("role")}</label>
            <select id="ef-role" value={roleId} onChange={(e) => setRoleId(e.target.value)} className={inputCls}>
              {roles.map((r) => (
                <option key={r.id} value={r.id}>
                  {localizedName(r.name_en, r.name_bn, locale)}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className={labelCls} htmlFor="ef-locale">{t("prefLocale")}</label>
            <select id="ef-locale" value={prefLocale} onChange={(e) => setPrefLocale(e.target.value as "en" | "bn")} className={inputCls}>
              <option value="en">English</option>
              <option value="bn">বাংলা</option>
            </select>
          </div>
        </div>
        {!isEdit ? (
          <div>
            <label className={labelCls} htmlFor="ef-pw">{t("password")}</label>
            <input id="ef-pw" type="password" required value={password} onChange={(e) => setPassword(e.target.value)} className={inputCls} autoComplete="new-password" />
          </div>
        ) : null}
        <fieldset>
          <legend className={labelCls}>{t("counters")}</legend>
          <div className="flex flex-wrap gap-2">
            {counters.map((c) => {
              const on = counterIds.includes(c.id);
              return (
                <button
                  key={c.id}
                  type="button"
                  onClick={() => toggleCounter(c.id)}
                  aria-pressed={on}
                  className={`min-h-[40px] rounded-lg border px-3 text-xs font-semibold transition-colors ${
                    on
                      ? "border-[var(--color-primary)] bg-[var(--color-primary)] text-white"
                      : "border-[var(--color-border)] hover:bg-[var(--color-primary-100)]"
                  }`}
                >
                  {c.code}
                </button>
              );
            })}
          </div>
          <p className="mt-1 text-xs text-[var(--color-muted-foreground)]">{t("counterHint")}</p>
        </fieldset>
        {err ? (
          <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm font-medium text-red-700">
            {t(`errors.${err}` as never)}
          </p>
        ) : null}
        <div className="grid grid-cols-2 gap-2 pt-1">
          <button type="button" onClick={onClose} disabled={submitting} className="min-h-[44px] rounded-xl border border-[var(--color-border)] text-sm font-semibold hover:bg-[var(--color-muted)] disabled:opacity-50">
            {t("cancel")}
          </button>
          <button type="submit" disabled={submitting} className="min-h-[44px] rounded-xl bg-[var(--color-primary)] text-sm font-bold text-white hover:bg-[var(--color-primary-strong)] disabled:opacity-60">
            {submitting ? t("saving") : t("save")}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function ConfirmToggle({
  emp,
  onClose,
  onDone,
  call,
}: {
  emp: EmployeeOut;
  onClose: () => void;
  onDone: () => void;
  call: (path: string, init: RequestInit) => Promise<boolean>;
}) {
  const t = useTranslations("employees");
  const [busy, setBusy] = useState(false);
  const disable = emp.is_active;

  async function confirm() {
    setBusy(true);
    const ok = await call(`/api/employees/${emp.id}/${disable ? "disable" : "enable"}`, {
      method: "POST",
    });
    setBusy(false);
    if (ok) onDone();
  }

  return (
    <Dialog title={disable ? t("disableTitle") : t("enableTitle")} onClose={onClose}>
      <p className="text-sm text-[var(--color-muted-foreground)]">
        {disable ? t("disableBody", { name: emp.name }) : t("enableBody", { name: emp.name })}
      </p>
      <div className="mt-4 grid grid-cols-2 gap-2">
        <button type="button" onClick={onClose} disabled={busy} className="min-h-[44px] rounded-xl border border-[var(--color-border)] text-sm font-semibold hover:bg-[var(--color-muted)] disabled:opacity-50">
          {t("cancel")}
        </button>
        <button
          type="button"
          onClick={confirm}
          disabled={busy}
          className={`min-h-[44px] rounded-xl text-sm font-bold text-white disabled:opacity-60 ${
            disable ? "bg-[var(--color-destructive)] hover:bg-red-700" : "bg-[var(--color-primary)] hover:bg-[var(--color-primary-strong)]"
          }`}
        >
          {busy ? t("working") : disable ? t("disable") : t("enable")}
        </button>
      </div>
    </Dialog>
  );
}

function ResetPassword({
  emp,
  onClose,
  onDone,
}: {
  emp: EmployeeOut;
  onClose: () => void;
  onDone: () => void;
}) {
  const t = useTranslations("employees");
  const router = useRouter();
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    const res = await fetch(`/api/employees/${emp.id}/reset-password`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ new_password: pw }),
    });
    setBusy(false);
    if (!res.ok) {
      const p = await res.json().catch(() => ({}));
      setErr(p.code ?? "unknown");
      return;
    }
    router.refresh();
    onDone();
  }

  return (
    <Dialog title={t("resetTitle", { name: emp.name })} onClose={onClose}>
      <form onSubmit={submit} className="space-y-3">
        <div>
          <label className={labelCls} htmlFor="rp-pw">{t("newPassword")}</label>
          <input id="rp-pw" type="password" required value={pw} onChange={(e) => setPw(e.target.value)} className={inputCls} autoComplete="new-password" />
        </div>
        {err ? (
          <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm font-medium text-red-700">
            {t(`errors.${err}` as never)}
          </p>
        ) : null}
        <div className="grid grid-cols-2 gap-2">
          <button type="button" onClick={onClose} disabled={busy} className="min-h-[44px] rounded-xl border border-[var(--color-border)] text-sm font-semibold hover:bg-[var(--color-muted)] disabled:opacity-50">
            {t("cancel")}
          </button>
          <button type="submit" disabled={busy} className="min-h-[44px] rounded-xl bg-[var(--color-primary)] text-sm font-bold text-white hover:bg-[var(--color-primary-strong)] disabled:opacity-60">
            {busy ? t("working") : t("resetPassword")}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function AssignCounters({
  emp,
  counters,
  locale,
  onClose,
  onDone,
}: {
  emp: EmployeeOut;
  counters: CounterOut[];
  locale: Locale;
  onClose: () => void;
  onDone: () => void;
}) {
  const t = useTranslations("employees");
  const router = useRouter();
  const [ids, setIds] = useState<string[]>(emp.assigned_counter_ids);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function toggle(id: string) {
    setIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  async function submit() {
    setBusy(true);
    setErr(null);
    const res = await fetch(`/api/employees/${emp.id}/counters`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ counter_ids: ids }),
    });
    setBusy(false);
    if (!res.ok) {
      const p = await res.json().catch(() => ({}));
      setErr(p.code ?? "unknown");
      return;
    }
    router.refresh();
    onDone();
  }

  return (
    <Dialog title={t("countersTitle", { name: emp.name })} onClose={onClose}>
      <div className="flex flex-wrap gap-2">
        {counters.map((c) => {
          const on = ids.includes(c.id);
          return (
            <button
              key={c.id}
              type="button"
              onClick={() => toggle(c.id)}
              aria-pressed={on}
              className={`min-h-[44px] rounded-lg border px-3 text-sm font-semibold transition-colors ${
                on
                  ? "border-[var(--color-primary)] bg-[var(--color-primary)] text-white"
                  : "border-[var(--color-border)] hover:bg-[var(--color-primary-100)]"
              }`}
            >
              {c.code} · {localizedName(c.name_en, c.name_bn, locale)}
            </button>
          );
        })}
      </div>
      <p className="mt-2 text-xs text-[var(--color-muted-foreground)]">{t("counterHint")}</p>
      {err ? (
        <p role="alert" className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm font-medium text-red-700">
          {t(`errors.${err}` as never)}
        </p>
      ) : null}
      <div className="mt-4 grid grid-cols-2 gap-2">
        <button type="button" onClick={onClose} disabled={busy} className="min-h-[44px] rounded-xl border border-[var(--color-border)] text-sm font-semibold hover:bg-[var(--color-muted)] disabled:opacity-50">
          {t("cancel")}
        </button>
        <button type="button" onClick={submit} disabled={busy} className="min-h-[44px] rounded-xl bg-[var(--color-primary)] text-sm font-bold text-white hover:bg-[var(--color-primary-strong)] disabled:opacity-60">
          {busy ? t("saving") : t("save")}
        </button>
      </div>
    </Dialog>
  );
}
