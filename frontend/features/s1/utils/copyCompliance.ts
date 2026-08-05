const BLOCKED_UI_TERMS = [
  "confidence",
  "percentage",
  "verified",
  "all clear",
  "warning",
] as const;

export function findBlockedUiTerms(text: string): string[] {
  const normalized = text.toLowerCase();
  return BLOCKED_UI_TERMS.filter((term) => normalized.includes(term));
}
