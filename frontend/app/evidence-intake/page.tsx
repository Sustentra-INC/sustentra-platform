import { UploadedEvidenceTable } from "../../components/evidence/UploadedEvidenceTable";

export default function EvidenceIntakePage() {
  return (
    <section>
      <h2>Evidence Intake</h2>
      <UploadedEvidenceTable
        documents={[
          {
            document_id: "doc_demo_001",
            engagement_id: "eng_demo_001",
            file_name: "sample.pdf",
            processing_status: "queued"
          }
        ]}
      />
    </section>
  );
}

