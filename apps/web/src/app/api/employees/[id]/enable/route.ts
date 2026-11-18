import { apiProxy } from "../../../_lib/proxy";

type Ctx = { params: Promise<{ id: string }> };

/** POST /api/employees/[id]/enable → reactivate an employee. */
export async function POST(_request: Request, { params }: Ctx) {
  const { id } = await params;
  return apiProxy(`/employees/${id}/enable`, { method: "POST" });
}
