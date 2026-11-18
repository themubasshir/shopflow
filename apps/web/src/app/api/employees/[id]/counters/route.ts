import { type NextRequest } from "next/server";
import { apiProxy } from "../../../_lib/proxy";

type Ctx = { params: Promise<{ id: string }> };

/** PUT /api/employees/[id]/counters → assign counter access. */
export async function PUT(request: NextRequest, { params }: Ctx) {
  const { id } = await params;
  const upstream = await request.text();
  return apiProxy(`/employees/${id}/counters`, { method: "PUT", body: upstream });
}
