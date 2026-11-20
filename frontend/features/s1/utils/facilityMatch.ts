import type { FacilityOption } from "../types";

/**
 * Which Setup facility a bill belongs to: a port of the backend's ``match_facility_state``
 * (backend/app/services/reviewed_evidence.py, EXT-022), so the screens and the recalculation always agree.
 * The cases in backend/tests/fixtures/facility_placement_cases.json run against both.
 *
 * Names are compared after case, punctuation and whitespace are set aside, and a leading "Company - " is
 * dropped when the company is the engagement's own. Addresses are compared word for word after the USPS
 * spellings (Road/Rd, East/E) are made the same; a unit on the bill that Setup does not have is ignored, and the
 * house number must be the same. Nothing is matched on a near miss. A name on several facilities that the
 * address does not settle, or a street two sites share, is "ambiguous": nothing is placed.
 */

/** Case folding as the backend's casefold(): JavaScript's toLowerCase plus the folds it lacks. */
function fold(text: string): string {
  return text.normalize("NFKC").toLowerCase().replace(/ß/g, "ss").replace(/ς/g, "σ");
}

function normText(value: string | null | undefined): string {
  return fold(value ?? "")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .split(/\s+/)
    .filter(Boolean)
    .join(" ");
}

// USPS street-suffix, directional and unit abbreviations (Publication 28), written out -> abbreviated.
const STREET_ABBREVIATIONS: Record<string, string> = {
  alley: "aly", avenue: "ave", av: "ave", boulevard: "blvd", circle: "cir", court: "ct",
  drive: "dr", expressway: "expy", freeway: "fwy", highway: "hwy", lane: "ln", parkway: "pkwy",
  place: "pl", plaza: "plz", road: "rd", square: "sq", street: "st", terrace: "ter", trail: "trl",
  turnpike: "tpke", way: "way", mall: "mall", loop: "loop", pike: "pike", crossing: "xing",
  center: "ctr", centre: "ctr", route: "rte", suite: "ste", apartment: "apt", floor: "fl",
  room: "rm", north: "n", south: "s", east: "e", west: "w", northeast: "ne", northwest: "nw",
  southeast: "se", southwest: "sw",
};
const NOT_SUFFIXES = new Set(["ste", "apt", "fl", "rm", "n", "s", "e", "w", "ne", "nw", "se", "sw", "hwy", "rte"]);
const STREET_SUFFIXES = new Set(Object.values(STREET_ABBREVIATIONS).filter((w) => !NOT_SUFFIXES.has(w)));
const ROUTE_WORDS = new Set(["hwy", "rte"]);
const DIRECTIONS = new Set(["n", "s", "e", "w", "ne", "nw", "se", "sw"]);
const UNIT_WORDS = new Set(["ste", "apt", "unit", "rm", "fl"]);
const CORPORATE_SUFFIXES = new Set(["inc", "incorporated", "llc", "ltd", "limited", "corp", "corporation", "co", "company", "plc", "gmbh", "ag", "sa"]);
const NAME_SEPARATOR = /\s[-‐-―−]\s/;
const PO_BOX = /\bp\.?\s?o\.?\s*box\s*[\p{L}\p{N}_]+|\bpost\s+office\s+box\s*[\p{L}\p{N}_]+/gu;
const HOUSE_NUMBER = /^\p{Nd}+[a-z]?$/u;
const ALL_DIGITS = /^\p{Nd}+$/u;
const STARTS_WITH_DIGIT = /^\p{Nd}/u;

function companyKey(value: string | null | undefined): string {
  const words = normText(value).split(" ").filter(Boolean);
  while (words.length && CORPORATE_SUFFIXES.has(words[words.length - 1])) words.pop();
  return words.join(" ");
}

/** What a bill's facility name may be called: as written, and without a leading "Company - " for the engagement's own. */
function facilityNames(name: string | null | undefined, company: string | null | undefined): Set<string> {
  const names = new Set<string>();
  if (normText(name)) names.add(normText(name));
  const key = companyKey(company);
  if (key && name) {
    const m = NAME_SEPARATOR.exec(name);
    if (m) {
      const before = name.slice(0, m.index);
      const after = name.slice(m.index + m[0].length);
      if (companyKey(before) === key && normText(after)) names.add(normText(after));
    }
  }
  return names;
}

function segments(address: string | null | undefined, dropPoBox: boolean): string[][] {
  let text = fold(address ?? "").replace(/#/g, " unit ");
  if (dropPoBox) text = text.replace(PO_BOX, " ");
  const out: string[][] = [];
  for (const part of text.split(/[,;\n]/)) {
    const words = (part.match(/[\p{L}\p{N}_]+/gu) ?? []).map((w) => STREET_ABBREVIATIONS[w] ?? w);
    if (words.length) out.push(words);
  }
  return out;
}

const isStreetLine = (words: string[]) =>
  words.length > 0 && HOUSE_NUMBER.test(words[0]) && words.slice(2).some((w) => STREET_SUFFIXES.has(w));

interface ParsedAddress {
  full: string[][];
  street: string[] | null;
  unit: string | null;
  rest: string[];
}

function parseAddress(address: string | null | undefined): ParsedAddress {
  const parsed: ParsedAddress = { full: segments(address, false), street: null, unit: null, rest: [] };
  const segs = segments(address, true);
  const starts: [number, number][] = [];
  segs.forEach((seg, si) =>
    seg.forEach((w, wi) => {
      if (HOUSE_NUMBER.test(w) && wi + 1 < seg.length && !STARTS_WITH_DIGIT.test(seg[wi + 1])) starts.push([si, wi]);
    })
  );
  if (!starts.length) return parsed;
  const found = starts.find(([a, b]) =>
    segs[a].slice(b + 1).some((w) => ROUTE_WORDS.has(w)) || segs[a].slice(b + 2).some((w) => STREET_SUFFIXES.has(w))
  );
  if (!found) return parsed;
  const [si, wi] = found;
  const words = segs[si].slice(wi);
  let end = words.length;
  const route = words.findIndex((w, i) => i >= 1 && ROUTE_WORDS.has(w));
  const suffix = words.findIndex((w, i) => i >= 2 && STREET_SUFFIXES.has(w));
  if (route !== -1 && (suffix === -1 || route < suffix)) {
    end = route + 1 < words.length && ALL_DIGITS.test(words[route + 1]) ? route + 2 : route + 1;
  } else if (suffix !== -1) {
    end = suffix + 1;
    if (end < words.length && DIRECTIONS.has(words[end])) end += 1;
  }
  parsed.street = words.slice(0, end);
  let rest = words.slice(end);
  for (const seg of segs.slice(si + 1)) if (!isStreetLine(seg)) rest = rest.concat(seg);
  if (rest.length >= 2 && UNIT_WORDS.has(rest[0]) && [...rest[1]].length <= 4 && !/^\p{Nd}{5}$/u.test(rest[1])) {
    parsed.unit = rest[1];
    rest = rest.slice(2);
  }
  parsed.rest = rest;
  return parsed;
}

const sameWords = (a: string[], b: string[]) => a.length === b.length && a.every((w, i) => w === b[i]);

function namesAPlace(segs: string[][]): boolean {
  const words = segs.flat();
  return words.length >= 3 || words.some((w) => STARTS_WITH_DIGIT.test(w));
}

/** 0 the same (unit too), 1 the same with a unit the bill has and Setup has not, null not the same place. */
function addressRank(bill: ParsedAddress, setup: ParsedAddress): number | null {
  if (bill.full.length && bill.full.length === setup.full.length && bill.full.every((s, i) => sameWords(s, setup.full[i])) && namesAPlace(setup.full)) return 0;
  if (bill.street === null || setup.street === null || !sameWords(bill.street, setup.street)) return null;
  const [short, long] = bill.rest.length <= setup.rest.length ? [bill.rest, setup.rest] : [setup.rest, bill.rest];
  if (!sameWords(long.slice(0, short.length), short)) return null;
  if (setup.unit !== null) return bill.unit === setup.unit ? 0 : null;
  return bill.unit === null ? 0 : 1;
}

export interface FacilityMatchState {
  facility: FacilityOption | null;
  /** The name or address pointed at more than one facility and nothing settled which. */
  ambiguous: boolean;
}

export function matchFacilityState(
  name: string | null | undefined,
  address: string | null | undefined,
  facilities: FacilityOption[],
  company?: string | null
): FacilityMatchState {
  let pool = facilities;
  let narrowed = false;
  const names = facilityNames(name, company);
  if (names.size) {
    const named = pool.filter((f) => names.has(normText(f.name)));
    if (named.length === 1) return { facility: named[0], ambiguous: false };
    if (named.length) {
      pool = named; // one name on several facilities: the address chooses among them
      narrowed = true;
    }
  }
  if (address) {
    const bill = parseAddress(address);
    const ranked: [number, FacilityOption][] = [];
    for (const f of pool) {
      if (!f.address) continue;
      const rank = addressRank(bill, parseAddress(f.address));
      if (rank !== null) ranked.push([rank, f]);
    }
    if (ranked.length) {
      const best = Math.min(...ranked.map(([r]) => r));
      const top = ranked.filter(([r]) => r === best).map(([, f]) => f);
      return top.length === 1 ? { facility: top[0], ambiguous: false } : { facility: null, ambiguous: true };
    }
  }
  return { facility: null, ambiguous: narrowed };
}

export function matchFacility(
  name: string | null | undefined,
  address: string | null | undefined,
  facilities: FacilityOption[],
  company?: string | null
): FacilityOption | null {
  return matchFacilityState(name, address, facilities, company).facility;
}
