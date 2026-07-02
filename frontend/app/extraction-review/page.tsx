import { DocumentPreview } from "../../components/evidence/DocumentPreview";
import { EvidenceRail } from "../../components/evidence/EvidenceRail";
import { FieldReviewCard } from "../../components/evidence/FieldReviewCard";
import { SourceSnippet } from "../../components/evidence/SourceSnippet";

export default function ExtractionReviewPage() {
  return (
    <section>
      <h2>Extraction Review</h2>
      <EvidenceRail items={[{ evidence_id: "ev_demo_001", label: "Utility Bill - June" }]} />
      <DocumentPreview documentId="doc_demo_001" />
      <FieldReviewCard fieldName="kwh_consumed" candidateValue="1500" />
      <SourceSnippet snippet="Total usage: 1,500 kWh" location="Page 2, table row 4" />
    </section>
  );
}

