import type { FacilityOption } from "../types";

/**
 * Which Setup facility a bill belongs to. Same rules as the backend
 * (engagement_recalculation_service.match_facility), so the screens and the
 * recalculation always agree: the same name, or the same street address (one
 * containing the other). Nothing is matched on a guess.
 */
function norm(value: string | null | undefined): string {
  return (value ?? "")
    .toLowerCase()
    .replace(/[^a-z0-9 ]+/g, " ")
    .split(/\s+/)
    .filter(Boolean)
    .join(" ");
}

export function matchFacility(
  name: string | null | undefined,
  address: string | null | undefined,
  facilities: FacilityOption[]
): FacilityOption | null {
  const billName = norm(name);
  const billAddress = norm(address);
  if (billName) {
    const byName = facilities.find((f) => norm(f.name) === billName);
    if (byName) return byName;
  }
  if (billAddress.length >= 8) {
    const byAddress = facilities.find((f) => {
      const setup = norm(f.address);
      return setup.length >= 8 && (billAddress.includes(setup) || setup.includes(billAddress));
    });
    if (byAddress) return byAddress;
  }
  return null;
}
