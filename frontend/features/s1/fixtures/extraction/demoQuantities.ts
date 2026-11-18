/**
 * Demo quantities for the fleet statements and propane invoices (the old demo's annual numbers,
 * spread over the quarters). The fixture values for those documents and the demo backend's
 * schedule both read them from here, so a quantity is one figure on every screen.
 */
export const FLEET_ANNUAL: Record<string, { gal: number; mi: number }> = {
  tualatin: { gal: 180_000, mi: 1_170_000 },
  kent: { gal: 180_000, mi: 1_170_000 },
  modesto: { gal: 108_900, mi: 707_850 },
};

/** A quarter's gallons and miles: an even share, the last quarter takes the rounding. */
export function fleetQuarter(code: string, quarter: number): { gal: number; mi: number } {
  const annual = FLEET_ANNUAL[code];
  const last = quarter === 4;
  return {
    gal: last ? annual.gal - 3 * Math.round(annual.gal / 4) : Math.round(annual.gal / 4),
    mi: last ? annual.mi - 3 * Math.round(annual.mi / 4) : Math.round(annual.mi / 4),
  };
}

export const PROPANE_BY_DOC: Record<string, number> = {
  "modesto_propane_feb.pdf": 4_000,
  "modesto_propane_aug.pdf": 4_000,
  "kent_propane_may.pdf": 3_000,
  "kent_propane_nov.pdf": 3_000,
};
