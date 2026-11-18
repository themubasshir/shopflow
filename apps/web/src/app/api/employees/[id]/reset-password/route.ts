import { type NextRequest } from "next/server";
import { apiProxy } from "../../../_lib/proxy";

type Ctx = { params: Promise<{ id: string }> };

/** POST /api/employees/[id]/reset-password → set a new password. */
export async function POST(request: NextRequest, { params }: Ctx) {
  const { id } = await params;
  const upstream = await request.text();
  return apiProxy(`/employees/${id}/reset-password`, {
    method: "POST",
    body: upstream,
  });
}
