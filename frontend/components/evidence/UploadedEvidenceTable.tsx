import type { DocumentRecord } from "../../lib/types";

interface UploadedEvidenceTableProps {
  documents: DocumentRecord[];
}

export function UploadedEvidenceTable({ documents }: UploadedEvidenceTableProps) {
  return (
    <table style={{ width: "100%", borderCollapse: "collapse" }}>
      <thead>
        <tr>
          <th style={{ textAlign: "left" }}>Document ID</th>
          <th style={{ textAlign: "left" }}>File Name</th>
          <th style={{ textAlign: "left" }}>Status</th>
        </tr>
      </thead>
      <tbody>
        {documents.map((doc) => (
          <tr key={doc.document_id}>
            <td>{doc.document_id}</td>
            <td>{doc.file_name}</td>
            <td>{doc.processing_status}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

