interface GapFinding {
  id: string;
  title: string;
  severity: string;
}

interface GapFindingListProps {
  findings: GapFinding[];
}

export function GapFindingList({ findings }: GapFindingListProps) {
  return (
    <section>
      <h3>Gap Findings</h3>
      <ul>
        {findings.map((finding) => (
          <li key={finding.id}>{finding.title} ({finding.severity})</li>
        ))}
      </ul>
    </section>
  );
}

