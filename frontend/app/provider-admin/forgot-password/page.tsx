import { ForgotPasswordForm } from "../../../features/auth/ForgotPasswordForm";

export default function ProviderForgotPasswordPage() {
  return <ForgotPasswordForm realm={{ kind: "provider" }} />;
}
