import createMiddleware from "next-intl/middleware";
import { NextResponse, type NextRequest } from "next/server";
import { routing } from "./i18n/routing";

const localize = createMiddleware(routing);
const safeMethods = new Set(["GET", "HEAD", "OPTIONS"]);

export default function proxy(request: NextRequest) {
  if (request.nextUrl.pathname.startsWith("/api/")) {
    if (safeMethods.has(request.method)) return NextResponse.next();
    // Comma-separated allowlist (e.g. "http://localhost:3000,http://127.0.0.1:3000").
    const allowed = (process.env.SHOPFLOW_WEB_ORIGIN || "")
      .split(",")
      .map((o) => o.trim())
      .filter(Boolean);
    if (process.env.NODE_ENV !== "production") allowed.push(request.nextUrl.origin);
    const origin = request.headers.get("origin");
    if (!origin || !allowed.includes(origin)) {
      return NextResponse.json(
        { error: "Request origin is not allowed", code: "forbidden", details: {} },
        { status: 403 },
      );
    }
    return NextResponse.next();
  }

  return localize(request);
}

export const config = {
  matcher: ["/api/:path*", "/((?!api|_next|_vercel|.*\\..*).*)"],
};
