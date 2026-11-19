import createMiddleware from "next-intl/middleware";
import { NextResponse, type NextRequest } from "next/server";
import { routing } from "./i18n/routing";

const localize = createMiddleware(routing);
const safeMethods = new Set(["GET", "HEAD", "OPTIONS"]);

export default function proxy(request: NextRequest) {
  if (request.nextUrl.pathname.startsWith("/api/")) {
    if (safeMethods.has(request.method)) return NextResponse.next();
    const expectedOrigin = process.env.SHOPFLOW_WEB_ORIGIN ||
      (process.env.NODE_ENV !== "production" ? request.nextUrl.origin : undefined);
    if (!expectedOrigin || request.headers.get("origin") !== expectedOrigin) {
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
