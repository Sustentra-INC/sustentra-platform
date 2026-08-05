import { ClarificationDialog } from "../../components/gaps/ClarificationDialog";
import { GapDetailPanel } from "../../components/gaps/GapDetailPanel";
import { GapFindingList } from "../../components/gaps/GapFindingList";

export default function GapAnalysisPage() {
  const findings = [{ id: "gap_001", title: "Missing utility invoice", severity: "high" }];

  return (
    <section>
      <h2>Gap Analysis</h2>
      <GapFindingList findings={findings} />
      <GapDetailPanel findingId="gap_001" />
      <ClarificationDialog open={false} />
    </section>
  );
}

