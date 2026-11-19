"use client";

import { useState, type FormEvent } from "react";
import { useTranslations } from "next-intl";
import { Pencil, UserPlus } from "lucide-react";
import { useRouter } from "@/i18n/navigation";
import { browserRequest, fieldErrors } from "@/lib/api-client";
import { errorCode, fieldClass, localDigits, minorUnits, primaryButton, secondaryButton } from "@/components/ui/pos-form";
import { Card } from "@/components/ui/card";
import type { CustomerCreate, CustomerOut, CustomerUpdate } from "@/types";

export function CustomerForm({ customer }: { customer?: CustomerOut }) {
  const t = useTranslations("customers");
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [invalid, setInvalid] = useState<string[]>([]);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setInvalid([]);
    const fields = new FormData(event.currentTarget);
    const phone = String(fields.get("phone")).trim();
    const limit = String(fields.get("credit_limit")).trim();
    const name = String(fields.get("name")).trim();
    const newPhone = phone !== (customer?.phone ?? "") || !customer;
    const validMobile = /^(0|\+?880|00880)1[3-9]\d{8}$/.test(localDigits(phone).replace(/[\s().-]/g, ""));
    const errors = [
      ...(!name ? ["name"] : []),
      ...(newPhone && !validMobile ? ["phone"] : []),
      ...(limit && minorUnits(limit) === null ? ["credit_limit"] : []),
    ];
    if (errors.length) {
      setInvalid(errors);
      return;
    }
    const update: CustomerUpdate = {
      name,
      name_bn: String(fields.get("name_bn")).trim() || null,
      email: String(fields.get("email")).trim() || null,
      is_active: customer ? fields.get("is_active") === "true" : true,
      credit_limit: limit ? localDigits(limit) : "0",
      ...(newPhone ? { phone } : {}),
    };
    const body: CustomerCreate | CustomerUpdate = customer ? update : { ...update, name, phone };
    setSaving(true);
    try {
      const saved = await browserRequest<CustomerOut>(customer ? `/api/customers/${customer.id}` : "/api/customers", {
        method: customer ? "PATCH" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      setOpen(false);
      if (!customer) router.push(`/customers/${saved.id}`);
      router.refresh();
    } catch (err) {
      const code = errorCode(err);
      setError(code);
      setInvalid(code === "duplicate_mobile" ? ["phone"] : Object.keys(fieldErrors(err)));
    } finally {
      setSaving(false);
    }
  }

  if (!open) return (
    <button className={customer ? secondaryButton : primaryButton} onClick={() => { setError(""); setInvalid([]); setOpen(true); }}>
      {customer ? <Pencil size={16} aria-hidden="true" /> : <UserPlus size={18} aria-hidden="true" />}
      {t(customer ? "edit" : "add")}
    </button>
  );
  const fields = [
    { key: "name", label: "primaryName", value: customer?.name, required: true },
    { key: "name_bn", label: "banglaName", value: customer?.name_bn },
    { key: "phone", label: "phone", value: customer?.phone, type: "tel", required: !customer },
    { key: "email", label: "email", value: customer?.email, type: "email" },
    { key: "credit_limit", label: "creditLimit", value: customer?.credit_limit, inputMode: "decimal" as const },
  ] as const;

  return (
    <Card className="w-full">
      <form onSubmit={save} className="space-y-4" aria-label={t(customer ? "edit" : "add")}>
        <h2 className="font-bold">{t(customer ? "edit" : "add")}</h2>
        <fieldset disabled={saving} className="grid gap-3 sm:grid-cols-2">
          {fields.map((field) => (
            <label key={field.key} className="min-w-0 space-y-1 text-sm font-medium">
              <span>{t(field.label)}</span>
              <input
                name={field.key}
                type={"type" in field ? field.type : "text"}
                inputMode={"inputMode" in field ? field.inputMode : undefined}
                required={"required" in field ? field.required : undefined}
                maxLength={field.key === "email" ? 255 : field.key === "phone" ? 40 : 160}
                defaultValue={field.value ?? ""}
                className={fieldClass}
                aria-invalid={invalid.includes(field.key)}
                aria-describedby={invalid.includes(field.key) ? `customer-error-${field.key}` : undefined}
              />
              {invalid.includes(field.key) ? (
                <span id={`customer-error-${field.key}`} className="block text-red-700">
                  {t(field.key === "phone" ? (error === "duplicate_mobile" ? "errors.duplicate_mobile" : "errors.mobile") : "errors.field")}
                </span>
              ) : null}
            </label>
          ))}
          {customer && (
            <label className="space-y-1 text-sm font-medium">
              <span>{t("status")}</span>
              <select name="is_active" className={fieldClass} defaultValue={String(customer.is_active)}>
                <option value="true">{t("active")}</option>
                <option value="false">{t("inactive")}</option>
              </select>
            </label>
          )}
        </fieldset>
        <p className="text-xs text-[var(--color-muted-foreground)]">{t("limitHint")}</p>
        {error && !invalid.length && <p role="alert" className="text-sm text-red-700">{t.has(`errors.${error}`) ? t(`errors.${error}`) : t("errors.unknown")}</p>}
        <div className="flex flex-wrap gap-2">
          <button className={primaryButton} disabled={saving}>{t(saving ? "saving" : "save")}</button>
          <button className={secondaryButton} disabled={saving} type="button" onClick={() => setOpen(false)}>{t("cancel")}</button>
        </div>
      </form>
    </Card>
  );
}
