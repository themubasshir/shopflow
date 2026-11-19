import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

const nextConfig: NextConfig = {
  reactStrictMode: true,
  serverExternalPackages: ["playwright"],
  outputFileTracingIncludes: {
    "/api/invoices/\\[id\\]/receipt": ["./src/lib/receipt/assets/NotoSansBengali-*.ttf"],
  },
};

export default withNextIntl(nextConfig);
