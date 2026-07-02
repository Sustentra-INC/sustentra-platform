interface ClarificationDialogProps {
  open: boolean;
}

export function ClarificationDialog({ open }: ClarificationDialogProps) {
  if (!open) {
    return null;
  }

  return (
    <div style={{ border: "1px solid #ccc", borderRadius: 8, padding: 12, marginTop: 12 }}>
      <h4>Clarification Request</h4>
      <p>Clarification workflow is a placeholder in this skeleton.</p>
    </div>
  );
}

