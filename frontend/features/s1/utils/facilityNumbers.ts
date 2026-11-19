import type { FacilityOption } from "../types";

/**
 * Account and meter numbers on a Setup facility. PROVISIONAL (approved by the product owner, 18 Nov 2026):
 * the ops lead may change the format of the client's facility list, so the labels, the input parsing, the
 * limits and the one matching function all live in this file, and the backend's twin is
 * backend/app/services/facility_identifiers.py. Keep the two in step: the cases in
 * backend/tests/fixtures/facility_placement_cases.json are run against both.
 *
 * The comparison (NFKC, case-folded, invisible characters such as a BOM dropped):
 * - spaces, dashes and dots separate groups; two numbers are the same when their groups are the same
 *   ("4417 2290 31" = "4417-2290-31"), or when one is written without separators and the characters are the
 *   same ("442290" = "44-2290"). "12-345" is not "1234-5";
 * - only a whole number counts, never a partial one ("4417-2290" is not "4417-2290-31");
 * - a number needs at least MIN_DIGITS digits, on the bill and in Setup, before it can match.
 * Not done yet, because the format is provisional: a supplier per number.
 */
export type NumberKind = "account" | "meter";

export const MAX_NUMBERS_PER_FACILITY = 50;
export const MAX_NUMBER_LENGTH = 64;
export const MIN_DIGITS = 4;

/** How a bill placed by its number is described, here and on the backend. */
export const IDENTIFIER_REASON = "Account or meter number in Setup";

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

const SEPARATORS = /[\s.\-‐-―−]+/;
const INVISIBLE = /[﻿​-‍⁠]/g;

/** NFKC, invisible characters dropped, case-folded (the folds JavaScript's toLowerCase lacks are added by hand). */
export function foldNumber(value: string | null | undefined): string {
  return (value ?? "")
    .replace(INVISIBLE, "")
    .normalize("NFKC")
    .toLowerCase()
    .replace(/ß/g, "ss")
    .replace(/ς/g, "σ");
}

/** A number's groups of characters between spaces, dashes and dots. */
export function numberGroups(value: string | null | undefined): string[] {
  return foldNumber(value).split(SEPARATORS).filter(Boolean);
}

/** The groups run together: case, spaces, dashes and dots dropped. */
export function normaliseNumber(value: string | null | undefined): string {
  return numberGroups(value).join("");
}

export function digitCount(value: string | null | undefined): number {
  return [...foldNumber(value)].filter((ch) => /\p{Nd}/u.test(ch)).length;
}

/** Whether two numbers are the same: the same groups, or one without separators and the same characters. */
export function sameNumber(a: string | null | undefined, b: string | null | undefined): boolean {
  const ga = numberGroups(a);
  const gb = numberGroups(b);
  if (!ga.length || !gb.length) return false;
  if (ga.length === gb.length && ga.every((g, i) => g === gb[i])) return true;
  return (ga.length === 1 || gb.length === 1) && ga.join("") === gb.join("");
}

/** A pasted list split on newlines, commas and semicolons outside double quotes; quotes are removed. */
export function splitPasted(text: string): string[] {
  const parts: string[] = [];
  let current = "";
  let quoted = false;
  for (const ch of text) {
    if (ch === '"') quoted = !quoted;
    else if (!quoted && /[\r\n,;]/.test(ch)) {
      parts.push(current);
      current = "";
    } else current += ch;
  }
  parts.push(current);
  return parts.map((part) => part.trim()).filter(Boolean);
}

/** The reason one number is refused, or null when it is fine. */
export function checkNumber(value: string): string | null {
  const text = value.trim();
  if (!text) return NUMBER_PROBLEMS.empty;
  if ([...text].length > MAX_NUMBER_LENGTH) return NUMBER_PROBLEMS.tooLong;
  if (digitCount(text) === 0) return NUMBER_PROBLEMS.noDigit;
  return null;
}

export interface AddResult {
  values: string[];
  /** The parts that were refused, as typed; the input keeps only these. */
  rejected: string[];
  /** The first thing that went wrong, as a sentence naming the value; null when everything was added. */
  problem: string | null;
}

/** Add typed or pasted text to a list: each part is checked, the good ones are added, the first refusal is reported. */
export function addNumbers(current: string[], text: string): AddResult {
  const values = [...current];
  const rejected: string[] = [];
  let problem: string | null = null;
  const parts = splitPasted(text);
  if (!parts.length && text !== "") problem = NUMBER_PROBLEMS.empty;
  for (const part of parts) {
    const wrong = checkNumber(part);
    const duplicate = values.some((v) => sameNumber(v, part));
    const full = values.length >= MAX_NUMBERS_PER_FACILITY;
    const why = wrong ?? (full ? NUMBER_PROBLEMS.tooMany : duplicate ? NUMBER_PROBLEMS.duplicate : null);
    if (why) {
      rejected.push(part);
      problem ??= `${part.length > 24 ? `${[...part].slice(0, 24).join("")}…` : part}: ${why}`;
      continue;
    }
    values.push(part);
  }
  return { values, rejected, problem };
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
    const seen: { value: string; ids: Set<string> }[] = [];
    for (const facility of facilities) {
      for (const value of numbersOf(facility, kind)) {
        const entry = seen.find((e) => sameNumber(e.value, value));
        if (entry) entry.ids.add(facility.facilityId);
        else seen.push({ value, ids: new Set([facility.facilityId]) });
      }
    }
    for (const { value, ids } of seen) if (ids.size > 1) out.push({ kind, value, facilityIds: [...ids] });
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
  /** Set when the numbers point at two or more facilities, so nothing is placed. */
  ambiguous: string | null;
  /** The number that matched, for a note: "Account 4417-2290-31". */
  what: string | null;
}

function listing(kind: NumberKind, value: string | null | undefined, facilities: FacilityOption[]): FacilityOption[] {
  if (digitCount(value) < MIN_DIGITS) return [];
  return facilities.filter((f) => numbersOf(f, kind).some((v) => digitCount(v) >= MIN_DIGITS && sameNumber(v, value)));
}

/**
 * The facility whose listed numbers contain the bill's account number and/or meter number. Callers use it
 * only when nothing else placed the bill. One facility places the bill; a number on two or more facilities,
 * or an account and a meter number on different facilities, place nothing and say why; no match changes nothing.
 */
export function matchByIdentifier(
  account: string | null | undefined,
  meter: string | null | undefined,
  facilities: FacilityOption[]
): IdentifierMatch {
  const none: IdentifierMatch = { facility: null, reason: null, ambiguous: null, what: null };
  const found: Partial<Record<NumberKind, { value: string; hits: FacilityOption[] }>> = {};
  for (const [kind, value] of [["account", account], ["meter", meter]] as const) {
    const hits = listing(kind, value, facilities);
    if (hits.length) found[kind] = { value: String(value).trim(), hits };
  }
  for (const kind of ["account", "meter"] as const) {
    const entry = found[kind];
    if (entry && entry.hits.length > 1) {
      return { ...none, ambiguous: `${NUMBER_FIELDS[kind].singular} ${entry.value} is listed on ${entry.hits.length === 2 ? "two" : entry.hits.length} facilities` };
    }
  }
  if (found.account && found.meter && found.account.hits[0] !== found.meter.hits[0]) {
    return { ...none, ambiguous: `Account ${found.account.value} and meter ${found.meter.value} are listed on different facilities` };
  }
  const kind: NumberKind | null = found.account ? "account" : found.meter ? "meter" : null;
  const entry = kind ? found[kind] : undefined;
  if (!kind || !entry) return none;
  return { facility: entry.hits[0], reason: IDENTIFIER_REASON, ambiguous: null, what: `${NUMBER_FIELDS[kind].singular} ${entry.value}` };
}
