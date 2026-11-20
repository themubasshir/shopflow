import { api } from "@/lib/api";
import { hasPermission, verifySession } from "@/lib/session";
import { ProductsClient } from "./products-client";

export const dynamic = "force-dynamic";

const PAGE_SIZE_OPTIONS = [25, 50, 100, 200] as const;
const DEFAULT_PAGE_SIZE = 50;
const MAX_PAGE_SIZE = 200; // matches the API's le=200 cap on /catalog/products

export default async function ProductsPage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string }>;
  searchParams: Promise<{
    q?: string;
    tab?: string;
    view?: string;
    page?: string;
    pageSize?: string;
  }>;
}) {
  const { locale } = await params;
  const {
    q = "",
    tab = "products",
    view = "",
    page: pageParam = "",
    pageSize: pageSizeParam = "",
  } = await searchParams;
  const session = await verifySession();

  const canWrite = session ? hasPermission(session.me, "catalog:write") : false;

  // Pagination is server-driven: the API returns { items, total, limit, offset }.
  const pageSize = Math.min(
    Math.max(parseInt(pageSizeParam, 10) || DEFAULT_PAGE_SIZE, 1),
    MAX_PAGE_SIZE,
  );
  const page = Math.max(parseInt(pageParam, 10) || 1, 1);
  const offset = (page - 1) * pageSize;

  const prodParams: Record<string, string | number | boolean> = {
    limit: pageSize,
    offset,
  };
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
      total={products?.total ?? 0}
      page={page}
      pageSize={pageSize}
      pageSizeOptions={[...PAGE_SIZE_OPTIONS]}
      categories={categories}
      categoriesManage={categoriesManage}
    />
  );
}
