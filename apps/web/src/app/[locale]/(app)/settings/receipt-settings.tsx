"use client";

import { useState, type FormEvent } from "react";
import { useTranslations } from "next-intl";
import { Check, Printer } from "lucide-react";
import { Card } from "@/components/ui/card";
import { fieldClass, primaryButton } from "@/components/ui/pos-form";
import { browserRequest } from "@/lib/api-client";
import { receiptLanguage, receiptLanguages } from "@/lib/receipt/paper";
import type { ReceiptSettings } from "@/types";

const fields = [
  ["shop_name_en", 160], ["shop_name_bn", 160], ["address", 400], ["phone", 40],
  ["trade_license", 64], ["tax_registration", 64], ["heading_en", 100], ["heading_bn", 100],
  ["footer_en", 500], ["footer_bn", 500], ["return_policy_en", 500], ["return_policy_bn", 500],
] as const;

export function ReceiptSettingsEditor({ settings }: { settings: ReceiptSettings }) {
  const t = useTranslations("receipts");
  const [status, setStatus] = useState<"idle" | "saving" | "saved" | "failed">("idle");
  const [invalid, setInvalid] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const field = (key: string) => String(data.get(key) ?? "").trim() || null;
    const shop = field("shop_name_en");
    if (!shop) { setInvalid(true); return; }
    setInvalid(false);
    const body: ReceiptSettings = {
      ...settings,
      ...Object.fromEntries(fields.map(([key]) => [key, field(key)])),
      shop_name_en: shop,
      preferred_language: receiptLanguage(field("preferred_language")),
      printable_width_mm: Number(field("printable_width_mm")),
    };
    setStatus("saving");
    try {
      await browserRequest<ReceiptSettings>("/api/settings/receipts", {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      setStatus("saved");
    } catch {
      setStatus("failed");
    }
  }

  return (
    <Card>
      <form onSubmit={submit} className="space-y-4">
        <h2 className="flex items-center gap-2 text-lg font-bold"><Printer size={20} aria-hidden="true" />{t("settings")}</h2>
        <fieldset disabled={status === "saving"} className="grid gap-3 sm:grid-cols-2">
          {fields.map(([key, max]) => (
            <label key={key} className="grid min-w-0 content-start gap-1 text-sm font-medium">
              <span>{t("fields." + key)}</span>
              {max >= 400 ? <textarea name={key} className={fieldClass + " min-h-20 py-2"} maxLength={max} defaultValue={settings[key] ?? ""} /> :
                <input name={key} className={fieldClass} maxLength={max} defaultValue={settings[key] ?? ""}
                  type={key === "phone" ? "tel" : "text"} required={key === "shop_name_en"}
                  aria-invalid={key === "shop_name_en" && invalid} />}
            </label>
          ))}
          <label className="grid gap-1 text-sm font-medium">
            <span>{t("fields.preferred_language")}</span>
            <select name="preferred_language" className={fieldClass} defaultValue={settings.preferred_language}>
              {receiptLanguages.map((language) => <option key={language} value={language}>{t("languages." + language)}</option>)}
            </select>
          </label>
          <div className="grid grid-cols-2 gap-2">
            <label className="grid gap-1 text-sm font-medium">
              <span>{t("fields.paper_width_mm")}</span>
              <input value="80" readOnly className={fieldClass} />
            </label>
            <label className="grid gap-1 text-sm font-medium">
              <span>{t("fields.printable_width_mm")}</span>
              <input name="printable_width_mm" type="number" min={58} max={76} required defaultValue={settings.printable_width_mm} className={fieldClass} />
            </label>
          </div>
        </fieldset>
        <p className="text-sm text-[var(--color-muted-foreground)]">{t("settingsHint")}</p>
        {(invalid || status === "failed") && <p role="alert" className="text-sm text-red-700">{t(invalid ? "nameRequired" : "saveError")}</p>}
        {status === "saved" && <p role="status" className="flex items-center gap-1 text-sm font-semibold text-[var(--color-primary-strong)]"><Check size={16} aria-hidden="true" />{t("saved")}</p>}
        <button className={primaryButton} disabled={status === "saving"}>{t(status === "saving" ? "saving" : "save")}</button>
      </form>
    </Card>
  );
}
