const BLOCKED_UI_TERMS = [
  "confidence",
  "percentage",
  "complete",
  "verified",
  "all clear",
  "warning",
] as const;

export function findBlockedUiTerms(text: string): string[] {
  const normalized = text.toLowerCase();
  const blocked: string[] = BLOCKED_UI_TERMS.filter((term) => {
    if (term === "complete") {
      return /\bcomplete\b/.test(normalized.replace(/\bcompleteness\b/g, ""));
    }
    return normalized.includes(term);
  });
  if (/\d+\s*%/.test(text)) {
    blocked.push("numeric percentage");
  }
  return blocked;
}
