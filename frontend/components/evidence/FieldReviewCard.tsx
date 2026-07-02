interface FieldReviewCardProps {
  fieldName: string;
  candidateValue: string;
}

export function FieldReviewCard({ fieldName, candidateValue }: FieldReviewCardProps) {
  return (
    <article style={{ border: "1px solid #ddd", borderRadius: 8, padding: 12 }}>
      <h4>{fieldName}</h4>
      <p>Candidate: {candidateValue}</p>
      <p>Review controls will be wired in implementation phase.</p>
    </article>
  );
}

