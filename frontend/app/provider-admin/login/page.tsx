import { LoginFlow } from "../../../features/auth/LoginFlow";

export default function ProviderLoginPage() {
  return <LoginFlow realm={{ kind: "provider" }} />;
}
