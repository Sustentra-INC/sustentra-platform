interface DocumentPreviewProps {
  documentId: string;
}

export function DocumentPreview({ documentId }: DocumentPreviewProps) {
  return (
    <section>
      <h3>Document Preview</h3>
      <p>Preview placeholder for document: {documentId}</p>
    </section>
  );
}

