// Deliberately the same shape the API checks: one @, no spaces, a dot in the domain.
const EMAIL = /^[^@\s,;<>"'\\\x00-\x1f\x7f]+@[^@\s,;<>"'\\\x00-\x1f\x7f]+\.[^@\s,;<>"'\\\x00-\x1f\x7f]+$/;

export function isEmail(value: string): boolean {
  return value.length <= 320 && EMAIL.test(value);
}

/** Split pasted text (commas, semicolons, spaces, new lines, "Name <a@b.c>") into addresses.
 *  Lower-cased and de-duplicated, in the order given. `invalid` keeps what is not an address. */
export function parseEmails(text: string): { valid: string[]; invalid: string[] } {
  const valid: string[] = [];
  const invalid: string[] = [];
  const seen = new Set<string>();
  for (const raw of text.split(/[\s,;]+/)) {
    const token = raw.replace(/^[<"'(]+|[>"'),.]+$/g, "").trim().toLowerCase();
    if (!token || seen.has(token)) continue;
    seen.add(token);
    (isEmail(token) ? valid : invalid).push(token);
  }
  return { valid, invalid };
}
