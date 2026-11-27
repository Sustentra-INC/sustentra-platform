/**
 * Demo backend: the grid region the company used for an electricity line, as a reviewer entered or accepted it
 * (the backend's `input|grid_region|company` decision). Kept apart from decisions.ts so the demo's calculation
 * (recalcDataCalc.ts) can read it without importing the decision routes. Like the backend, it moves only the
 * company's side: its factors are those of its own region.
 */
const regions = new Map<string, string>();
const keyOf = (engagement: string, line: string) => `${engagement}|${line}`;

export function setDemoCompanyRegion(engagement: string, line: string, text: string | null): void {
  if (text === null) regions.delete(keyOf(engagement, line));
  else regions.set(keyOf(engagement, line), text);
}

export function demoCompanyRegion(engagement: string, line: string): string | null {
  return regions.get(keyOf(engagement, line)) ?? null;
}

export function resetDemoCompanyRegions(): void {
  regions.clear();
}

/** The two subregions the demo has factors for (the same names as recalcDataCalc's EGRID table). */
export const DEMO_REGION_NAMES: Record<string, string> = { NWPP: "WECC Northwest", CAMX: "WECC California" };

/** The demo subregion a reviewer's text names ("NWPP", "nwpp - WECC Northwest", "WECC Northwest"); null when none. */
export function companyRegionCode(text: string | null | undefined): string | null {
  const t = (text ?? "").normalize("NFKC").trim();
  if (!t || t.length > 200 || /[\u0000-\u001f\u007f-\u009f\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]/.test(t)) return null;
  for (const [code, name] of Object.entries(DEMO_REGION_NAMES)) {
    const found = new RegExp(`^${code}(?:\\s*[-\u2013\u2014\u00b7:(]?\\s*(.*?)\\)?)?$`, "i").exec(t);
    const rest = found ? (found[1] ?? "") : undefined; // an empty optional group does not take part: no name given
    if (rest !== undefined && (rest === "" || rest.toLowerCase() === name.toLowerCase())) return code;
    if (t.toLowerCase() === name.toLowerCase()) return code;
  }
  return null;
}
