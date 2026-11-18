import { type NextRequest } from "next/server";
import { apiProxy } from "../../../_lib/proxy";

type Ctx = { params: Promise<{ id: string }> };

/** PATCH /api/manage/counters/[id] → toggle is_active / rename a counter. */
export async function PATCH(request: NextRequest, { params }: Ctx) {
  const { id } = await params;
  const upstream = await request.text();
  return apiProxy(`/manage/counters/${id}`, { method: "PATCH", body: upstream });
}
