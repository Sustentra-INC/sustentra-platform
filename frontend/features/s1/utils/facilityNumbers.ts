import type { FacilityOption } from "../types";

/**
 * Account and meter numbers on a Setup facility. PROVISIONAL (approved by the product owner, 18 Nov 2026):
 * the ops lead may change the format of the client's facility list, so the labels, the input parsing, the
 * limits and the one matching function all live in this file, and the backend's twin is
 * backend/app/services/facility_identifiers.py. Keep the two in step.
 *
 * Numbers are compared with case, spaces, dashes and dots ignored, and only as a whole: "4417-2290" never
 * matches "4417-2290-31". The stored value stays as typed.
 */
export type NumberKind = "account" | "meter";

export const MAX_NUMBERS_PER_FACILITY = 50;
export const MAX_NUMBER_LENGTH = 64;

/** The facility field each kind is stored in, and the words the screen uses for it. */
export const NUMBER_FIELDS: Record<NumberKind, { key: "accountNumbers" | "meterNumbers"; label: string; singular: string; placeholder: string }> = {
  account: { key: "accountNumbers", label: "Account numbers", singular: "Account", placeholder: "Type a number, or paste a list" },
  meter: { key: "meterNumbers", label: "Meter numbers", singular: "Meter", placeholder: "Type a number, or paste a list" },
};

/** Why a value is refused, in a plain sentence. */
export const NUMBER_PROBLEMS = {
  empty: "A number can't be empty.",
  noDigit: "A number needs at least one digit.",
  tooLong: `A number can be at most ${MAX_NUMBER_LENGTH} characters.`,
  tooMany: `A facility can have at most ${MAX_NUMBERS_PER_FACILITY} numbers of one kind.`,
  duplicate: "That number is already listed on this facility.",
} as const;

/** The form two numbers are compared in: case, spaces, dashes and dots dropped. */
export function normaliseNumber(value: string | null | undefined): string {
  return (value ?? "")
    .normalize("NFKC")
    .replace(/[\s.\-‐-―−]+/g, "")
    .replace(/ß/g, "ss")
    .toLowerCase();
}

/** A pasted list split on newlines, commas and semicolons; blanks dropped. */
export function splitPasted(text: string): string[] {
  return text
    .split(/[\r\n,;]+/)
    .map((part) => part.trim())
    .filter(Boolean);
}

/** The reason one number is refused, or null when it is fine. */
export function checkNumber(value: string): string | null {
  const text = value.trim();
  if (!text) return NUMBER_PROBLEMS.empty;
  if ([...text].length > MAX_NUMBER_LENGTH) return NUMBER_PROBLEMS.tooLong;
  if (!/\p{Nd}/u.test(text.normalize("NFKC"))) return NUMBER_PROBLEMS.noDigit;
  return null;
}

export interface AddResult {
  values: string[];
  /** The first thing that went wrong, as a sentence naming the value; null when everything was added. */
  problem: string | null;
}

/** Add typed or pasted text to a list: each part is checked, the good ones are added, the first refusal is reported. */
export function addNumbers(current: string[], text: string): AddResult {
  const values = [...current];
  let problem: string | null = null;
  const parts = splitPasted(text);
  if (!parts.length && text.trim() === "" && text !== "") problem = NUMBER_PROBLEMS.empty;
  for (const part of parts) {
    const wrong = checkNumber(part);
    const duplicate = values.some((v) => normaliseNumber(v) === normaliseNumber(part));
    const full = values.length >= MAX_NUMBERS_PER_FACILITY;
    const why = wrong ?? (full ? NUMBER_PROBLEMS.tooMany : duplicate ? NUMBER_PROBLEMS.duplicate : null);
    if (why) {
      problem ??= `${part.length > 24 ? `${[...part].slice(0, 24).join("")}…` : part}: ${why}`;
      continue;
    }
    values.push(part);
  }
  return { values, problem };
}

/** A number listed on more than one facility, with the facilities that list it. */
export interface SharedNumber {
  kind: NumberKind;
  value: string;
  facilityIds: string[];
}

export function numbersOf(facility: FacilityOption, kind: NumberKind): string[] {
  const raw = (facility as unknown as Record<string, unknown>)[NUMBER_FIELDS[kind].key];
  return Array.isArray(raw) ? raw.filter((v): v is string => typeof v === "string" && v.trim() !== "") : [];
}

export function sharedNumbers(facilities: FacilityOption[]): SharedNumber[] {
  const out: SharedNumber[] = [];
  for (const kind of ["account", "meter"] as const) {
    const seen = new Map<string, { value: string; ids: Set<string> }>();
    for (const facility of facilities) {
      for (const value of numbersOf(facility, kind)) {
        const entry = seen.get(normaliseNumber(value)) ?? { value, ids: new Set<string>() };
        entry.ids.add(facility.facilityId);
        seen.set(normaliseNumber(value), entry);
      }
    }
    for (const { value, ids } of seen.values()) if (ids.size > 1) out.push({ kind, value, facilityIds: [...ids] });
  }
  return out;
}

/** The Setup note for a number on more than one facility. */
export function sharedNumberNote(shared: SharedNumber): string {
  const count = shared.facilityIds.length;
  return `${NUMBER_FIELDS[shared.kind].singular} ${shared.value} is on ${count === 2 ? "two" : count} facilities. Bills with it won't be placed automatically.`;
}

export interface IdentifierMatch {
  facility: FacilityOption | null;
  reason: string | null;
  /** Set when the number is listed on two or more facilities, so nothing is placed. */
  ambiguous: string | null;
}

/**
 * The facility whose listed numbers contain the bill's account number, else its meter number. Used only when
 * the name and address steps found no facility. One facility places the bill; two or more place nothing and
 * say why; no match changes nothing.
 */
export function matchByIdentifier(
  account: string | null | undefined,
  meter: string | null | undefined,
  facilities: FacilityOption[]
): IdentifierMatch {
  const none: IdentifierMatch = { facility: null, reason: null, ambiguous: null };
  for (const [kind, value] of [["account", account], ["meter", meter]] as const) {
    const wanted = normaliseNumber(value);
    if (!wanted || !/\p{Nd}/u.test(wanted)) continue;
    const found = facilities.filter((f) => numbersOf(f, kind).some((v) => normaliseNumber(v) === wanted));
    const label = NUMBER_FIELDS[kind].singular;
    if (found.length === 1) return { facility: found[0], reason: `${label} number in Setup`, ambiguous: null };
    if (found.length > 1) {
      return { facility: null, reason: null, ambiguous: `${label} ${String(value).trim()} is listed on ${found.length === 2 ? "two" : found.length} facilities` };
    }
  }
  return none;
}
