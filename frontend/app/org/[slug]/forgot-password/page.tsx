import { ForgotPasswordForm } from "../../../../features/auth/ForgotPasswordForm";

export default async function OrgForgotPasswordPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return <ForgotPasswordForm realm={{ kind: "org", slug }} />;
}
