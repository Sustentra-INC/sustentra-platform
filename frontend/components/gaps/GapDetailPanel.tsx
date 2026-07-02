interface GapDetailPanelProps {
  findingId: string;
}

export function GapDetailPanel({ findingId }: GapDetailPanelProps) {
  return (
    <section>
      <h3>Gap Detail</h3>
      <p>Detail placeholder for finding: {findingId}</p>
    </section>
  );
}

