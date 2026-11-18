import { redirect } from "@/i18n/navigation";
import { verifySession } from "@/lib/session";
import { LoginForm } from "./login-form";
import type { Locale } from "@/i18n/config";

export const dynamic = "force-dynamic";

export default async function LoginPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  // Already signed in? Skip the form and go straight to the app.
  const session = await verifySession();
  if (session) {
    redirect({ href: "/", locale: locale as Locale });
  }

  return <LoginForm />;
}
