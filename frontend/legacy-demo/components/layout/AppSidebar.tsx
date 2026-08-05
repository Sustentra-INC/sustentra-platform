import Link from "next/link";

const LINKS = [
  { href: "/", label: "Overview" },
  { href: "/audit-setup", label: "Audit Setup" },
  { href: "/evidence-intake", label: "Evidence Intake" },
  { href: "/extraction-review", label: "Extraction Review" },
  { href: "/validation", label: "Validation" },
  { href: "/calculation", label: "Calculation" },
  { href: "/gap-analysis", label: "Gap Analysis" },
  { href: "/assistant", label: "Assistant" }
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

