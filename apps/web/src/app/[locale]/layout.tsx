import type { Metadata, Viewport } from "next";
import { notFound } from "next/navigation";
import { NextIntlClientProvider } from "next-intl";
import { getMessages, setRequestLocale } from "next-intl/server";
import { Plus_Jakarta_Sans, Noto_Sans_Bengali } from "next/font/google";
import { locales, type Locale } from "@/i18n/config";
import "../globals.css";

const jakarta = Plus_Jakarta_Sans({ subsets: ["latin"], variable: "--font-sans" });
const bengali = Noto_Sans_Bengali({ subsets: ["bengali", "latin"], variable: "--font-bengali" });

export const metadata: Metadata = {
  title: { default: "ShopFlow", template: "%s · ShopFlow" },
  description: "Grocery & pharmacy management for Bangladesh",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export function generateStaticParams() {
  return locales.map((locale) => ({ locale }));
}

/**
 * Root layout for the locale segment. Kept minimal: the (app) route group adds
 * the authenticated shell and the (auth) group adds its own centered chrome, so
 * neither shell leaks into the other.
 */
export default async function LocaleLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  if (!locales.includes(locale as Locale)) notFound();
  setRequestLocale(locale);
  const messages = await getMessages();

  return (
    <html lang={locale} className={`${jakarta.variable} ${bengali.variable}`}>
      <body>
        <NextIntlClientProvider messages={messages} locale={locale}>
          {children}
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
