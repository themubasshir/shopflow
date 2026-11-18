import { type NextRequest } from "next/server";
import { apiProxy } from "../_lib/proxy";

/** POST /api/employees → create an employee (proxied with the cookie JWT). */
export async function POST(request: NextRequest) {
  const upstream = await request.text();
  return apiProxy("/employees", { method: "POST", body: upstream });
}
