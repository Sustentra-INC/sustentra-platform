export interface ResolveFieldKeyInput {
  candidateId?: string | null;
  documentId?: string | null;
  backendFieldId: string;
}

export function resolveFieldKey({
  candidateId,
  documentId,
  backendFieldId,
}: ResolveFieldKeyInput): string {
  if (candidateId) return `candidate:${candidateId}`;
  if (documentId) return `field:${documentId}::${backendFieldId}`;
  return `field:${backendFieldId}`;
}
