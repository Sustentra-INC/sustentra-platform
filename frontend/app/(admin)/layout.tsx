import type { ReactNode } from "react";

import { AppShell } from "../../components/layout/AppShell";

/**
 * Admin layout for the Sustentra-internal pages (login / clients / users /
 * account). These keep Jerome's `AppShell` (sidebar + session header). The
 * product surface at `/` deliberately does NOT use this shell — it has its own
 * in-app chrome.
 */
export default function AdminLayout({ children }: { children: ReactNode }) {
  return <AppShell>{children}</AppShell>;
}
