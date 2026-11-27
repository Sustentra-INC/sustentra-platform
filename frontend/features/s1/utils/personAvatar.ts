/** Tones of the shared person avatar (.s1-team-avatar--0 … --3). */
const AVATAR_TONES = 4;

/** Same person, same avatar tone: a small hash of the name. */
export function avatarTone(name: string): number {
  let n = 0;
  for (const ch of name) n = (n + ch.charCodeAt(0)) % AVATAR_TONES;
  return n;
}

/** Initials from the first and last word of a name: "T. Brandt" → "TB". */
export function initials(name: string): string {
  const words = name.replace(/\./g, " ").split(/\s+/).filter(Boolean);
  return ((words[0]?.[0] ?? "") + (words.length > 1 ? words[words.length - 1][0] : "")).toUpperCase();
}
