import { getTranslations } from "next-intl/server";
import { Link } from "@/i18n/navigation";
import { secondaryButton } from "@/components/ui/pos-form";

export async function Pager({ path, query, offset, limit, total }: {
  path: string;
  query: Record<string, string>;
  offset: number;
  limit: number;
  total: number;
}) {
  const t = await getTranslations("customers");
  if (total <= limit && !offset) return null;
  const href = (start: number) => ({ pathname: path, query: { ...query, offset: String(start) } });
  return (
    <nav aria-label={t("pagination")} className="flex flex-wrap items-center gap-2 text-sm">
      {offset > 0 && <Link className={secondaryButton} href={href(Math.max(0, offset - limit))}>{t("previous")}</Link>}
      {offset < total && <span className="px-1">{t("results", { first: offset + 1, last: Math.min(offset + limit, total), total })}</span>}
      {offset + limit < total && <Link className={secondaryButton} href={href(offset + limit)}>{t("next")}</Link>}
    </nav>
  );
}
