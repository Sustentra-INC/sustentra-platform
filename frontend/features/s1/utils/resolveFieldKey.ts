export interface ResolveFieldKeyInput {
  canonicalTypeId: string;
  backendFieldId: string;
}

export function resolveFieldKey({
  canonicalTypeId,
  backendFieldId,
}: ResolveFieldKeyInput): string {
  return `${canonicalTypeId}::${backendFieldId}`;
}
