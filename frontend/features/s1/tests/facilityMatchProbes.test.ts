import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import type { FacilityOption } from "../types";
import { matchFacilityState } from "../utils/facilityMatch";

/**
 * The name and address step: match, ambiguous or none, over the probes the backend tests read too
 * (backend/tests/fixtures/facility_match_probes.json; backend side: test_facility_match_probes.py).
 */
interface Probe {
  name: string | null;
  address: string | null;
  company: string | null;
  facilities?: FacilityOption[];
  expect: string | null;
}
const shared = JSON.parse(
  readFileSync(resolve(process.cwd(), "../backend/tests/fixtures/facility_match_probes.json"), "utf-8")
) as { facilities: FacilityOption[]; probes: Probe[] };

describe("the screen's facility match equals the backend's (shared probes)", () => {
  for (const p of shared.probes) {
    it(`${p.name ?? ""} | ${p.address ?? ""} | ${p.company ?? ""} -> ${p.expect}`, () => {
      const state = matchFacilityState(p.name, p.address, p.facilities ?? shared.facilities, p.company);
      if (p.expect === "ambiguous") expect([state.facility, state.ambiguous]).toEqual([null, true]);
      else if (p.expect === null) expect([state.facility, state.ambiguous]).toEqual([null, false]);
      else expect([state.facility?.facilityId, state.ambiguous]).toEqual([p.expect, false]);
    });
  }
});
