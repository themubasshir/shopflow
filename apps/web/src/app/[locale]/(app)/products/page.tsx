import { api } from "@/lib/api";
import { hasPermission, verifySession } from "@/lib/session";
import { ProductsClient } from "./products-client";

export const dynamic = "force-dynamic";

export default async function ProductsPage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string }>;
  searchParams: Promise<{ q?: string; tab?: string }>;
}) {
  const { locale } = await params;
  const { q = "", tab = "products" } = await searchParams;
  const session = await verifySession();

  const canWrite = session ? hasPermission(session.me, "catalog:write") : false;

  const [products, categories, categoriesManage] = await Promise.all([
    api.products(q ? { q, limit: 200 } : { limit: 200 }).catch(() => null),
    api.categories().catch(() => []),
    canWrite ? api.categoriesManage().catch(() => []) : Promise.resolve([]),
  ]);

  return (
    <ProductsClient
      locale={locale}
      canWrite={canWrite}
      initialTab={tab}
      initialQuery={q}
      products={products?.items ?? []}
      categories={categories}
      categoriesManage={categoriesManage}
    />
  );
}
