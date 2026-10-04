import Link from "next/link";

// Sustentra-internal admin nav. The audit product itself (evidence, extraction,
// calculation, gaps, assistant) lives in the workpaper at "/" with its own
// in-app navigation, so those former placeholder routes are not linked here.
const LINKS = [
  { href: "/", label: "Workpaper" },
  { href: "/users", label: "Sustentra Users" },
  { href: "/clients", label: "Clients" }
];

export function AppSidebar() {
  return (
    <aside style={{ width: 240, borderRight: "1px solid #ddd", padding: 16 }}>
      <h2>Sustentra</h2>
      <nav aria-label="Primary navigation">
        <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gap: 8 }}>
          {LINKS.map((link) => (
            <li key={link.href}>
              <Link href={link.href}>{link.label}</Link>
            </li>
          ))}
        </ul>
      </nav>
    </aside>
  );
}

