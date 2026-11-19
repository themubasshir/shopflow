import type { NextRequest } from "next/server";
import { apiProxy } from "../_lib/proxy";

export async function GET(request: NextRequest) {
  return apiProxy(`/customers${request.nextUrl.search}`);
}

export async function POST(request: NextRequest) {
  return apiProxy("/customers", { method: "POST", body: await request.text() });
}
