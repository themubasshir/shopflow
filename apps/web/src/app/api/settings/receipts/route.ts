import { apiProxy } from "@/app/api/_lib/proxy";

export async function PUT(request: Request) {
  return apiProxy("/settings/receipts", { method: "PUT", body: await request.text() });
}
