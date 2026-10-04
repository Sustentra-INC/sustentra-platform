"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { ReactNode } from "react";

import { logout } from "../../lib/api/auth";
import { clearSession } from "../../lib/session";
import { useActor } from "../../lib/useActor";
import { AppSidebar } from "./AppSidebar";
import { PageHeader } from "./PageHeader";

interface AppShellProps {
  children: ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  const pathname = usePathname();
  const router = useRouter();
  const actor = useActor();
  const actorName = actor ? `${actor.username} (${actor.actor_type})` : null;
  const isAuthPage = pathname.startsWith("/login");

  async function handleLogout() {
    try {
      await logout();
    } catch {
      // local session is cleared either way
    }
    clearSession();
    router.push("/login");
  }

  if (isAuthPage) {
    return (
      <main style={{ maxWidth: 480, margin: "48px auto", padding: 24 }}>
        <h1>Sustentra</h1>
        {children}
      </main>
    );
  }

  return (
    <div style={{ display: "flex", minHeight: "100vh" }}>
      <AppSidebar />
      <main style={{ flex: 1, padding: 20 }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 16 }}>
          <PageHeader
            title="Sustentra Evidence Extraction"
            subtitle="Production skeleton: Next.js frontend + FastAPI backend"
          />
          <div style={{ fontSize: 14, color: "#444", paddingTop: 8 }}>
            {actorName ? (
              <>
                <span>{actorName}</span>
                {" · "}
                <Link href="/account">Account</Link>
                {" · "}
                <button type="button" onClick={handleLogout} style={{ border: 0, background: "none", color: "#0645ad", cursor: "pointer", padding: 0 }}>
                  Log out
                </button>
              </>
            ) : (
              <Link href="/login">Log in</Link>
            )}
          </div>
        </div>
        {children}
      </main>
    </div>
  );
}
