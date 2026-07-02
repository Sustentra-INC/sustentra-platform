export function formatLabel(value: string): string {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

export function formatConfidence(value: number): string {
  const bounded = Math.min(1, Math.max(0, value));
  return `${Math.round(bounded * 100)}%`;
}
