import Link from "next/link";

/**
 * Internal navigation.
 *
 * `built: false` marks a route that is still a placeholder - the page renders a
 * sentence saying so and nothing else. Those are hidden rather than deleted:
 * anyone who has the link can still reach them, and each comes back by flipping
 * one flag when it is real.
 *
 * They are hidden because this sidebar is visible on every internal page, and a
 * client or design partner clicking through to "Calculation and reconciliation
 * view is a placeholder in this skeleton" learns something true but unhelpful
 * about a product being demonstrated to them.
 */
const LINKS = [
  { href: "/intake/login", label: "Client onboarding", built: true },
  { href: "/intake/review", label: "Review queue", built: true },
  { href: "/intake/review/metrics", label: "Onboarding metrics", built: true },
  { href: "/audit-setup", label: "Audit Setup", built: false },
  { href: "/evidence-intake", label: "Evidence Intake", built: false },
  { href: "/extraction-review", label: "Extraction Review", built: false },
  { href: "/validation", label: "Validation", built: false },
  { href: "/calculation", label: "Calculation", built: false },
  { href: "/gap-analysis", label: "Gap Analysis", built: false },
  { href: "/assistant", label: "Assistant", built: false }
];

export function AppSidebar() {
  const visible = LINKS.filter((link) => link.built);

  return (
    <aside style={{ width: 240, borderRight: "1px solid #ddd", padding: 16 }}>
      <h2>Sustentra</h2>
      <nav aria-label="Primary navigation">
        <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gap: 8 }}>
          {visible.map((link) => (
            <li key={link.href}>
              <Link href={link.href}>{link.label}</Link>
            </li>
          ))}
        </ul>
      </nav>
    </aside>
  );
}
