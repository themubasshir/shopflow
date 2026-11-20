import { api } from "@/lib/api";
import { hasPermission, verifySession } from "@/lib/session";
import { ProductsClient } from "./products-client";

export const dynamic = "force-dynamic";

export default async function ProductsPage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string }>;
  searchParams: Promise<{ q?: string; tab?: string; view?: string }>;
}) {
  const { locale } = await params;
  const { q = "", tab = "products", view = "" } = await searchParams;
  const session = await verifySession();

  const canWrite = session ? hasPermission(session.me, "catalog:write") : false;

  const prodParams: Record<string, string | number | boolean> = { limit: 200 };
  if (q) prodParams.q = q;
  if (view) prodParams.view = view;
  const [products, categories, categoriesManage] = await Promise.all([
    api.products(prodParams).catch(() => null),
    api.categories().catch(() => []),
    canWrite ? api.categoriesManage().catch(() => []) : Promise.resolve([]),
  ]);

  return (
    <ProductsClient
      locale={locale}
      canWrite={canWrite}
      initialTab={tab}
      initialQuery={q}
      initialView={view}
      products={products?.items ?? []}
      categories={categories}
      categoriesManage={categoriesManage}
    />
  );
}
