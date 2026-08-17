import { BANNED } from "../constants/copy";

export function findBannedRenderedCopy(text: string): string[] {
  const lower = text.toLowerCase();
  return BANNED.filter((term) => lower.includes(term.toLowerCase()));
}

