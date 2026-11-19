import { apiProxy } from "../../_lib/proxy";

export async function PATCH(request: Request, { params }: RouteContext<"/api/customers/[id]">) {
  const { id } = await params;
  return apiProxy(`/customers/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: await request.text(),
  });
}
