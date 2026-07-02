interface EvidenceRailItem {
  evidence_id: string;
  label: string;
}

interface EvidenceRailProps {
  items: EvidenceRailItem[];
}

export function EvidenceRail({ items }: EvidenceRailProps) {
  return (
    <section>
      <h3>Evidence Rail</h3>
      <ul>
        {items.map((item) => (
          <li key={item.evidence_id}>{item.label}</li>
        ))}
      </ul>
    </section>
  );
}

