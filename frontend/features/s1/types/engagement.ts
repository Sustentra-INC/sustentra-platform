export interface Actor {
  id: string;
  name: string;
  actorType: "preparer" | "reviewer" | "client" | "system";
}

export interface FacilityOption {
  facilityId: string;
  name: string;
  /** Street address, used to match bills to this facility. */
  address?: string;
  /** eGRID subregion for purchased electricity (Scope 2 location-based). */
  gridRegion?: string;
}

/** The client's point of contact — one recipient for all Evidence requests. */
export interface ClientContact {
  name: string;
  email: string;
  company: string;
}

/** A member of the engagement team, selectable as "raised by" on a request. */
export interface TeamMember {
  /** The chosen display name. */
  name: string;
  /** The login that saved the action; stored alongside the chosen name. */
  login: string;
}

export interface EngagementConfig {
  clientName: string;
  engagementId: string;
  /** The engagement's own name, shown in the Setup picker (S1-BE-002). */
  engagementName?: string;
  reportingPeriod: {
    start: string;
    end: string;
  };
  facilities: FacilityOption[];
  regulation: string;
  conclusionType: string;
  assuranceLevel: string;
  boundaryApproach: string;
  scopeBoundaryStatement: string;

  // --- Revised-spec (09/16) additions, optional for back-compat. ---
  /** Regulation shown by full name + jurisdiction; drives the in-scope list. */
  regulationJurisdiction?: string;
  methodology?: string;
  /** Screen-4 precondition: one recipient for the whole engagement. */
  clientContact?: ClientContact;
  /** Screen-4 precondition: the "raised by" options, typically up to four. */
  engagementTeam?: TeamMember[];
  /** The signed-in user's login, pre-selected as "raised by". */
  signedInLogin?: string;
  /** The signed-in user's display name, used when the engagement team is empty. */
  signedInName?: string;
  /** The verifier's own email — the "from" address for Request-by-email. */
  verifierEmail?: string;

  // --- Scope & assurance (Setup) additions, optional for back-compat. ---
  /** Which scopes the engagement covers, e.g. "Scope 1 & 2" or "Scope 1, 2, and 3". */
  dataScope?: string;
  /** The assurance standard applied, e.g. "ISO 14064-3". */
  assuranceStandard?: string;
  /** The materiality threshold as a percentage of total, e.g. "5%". */
  materialityThreshold?: string;

  /** Inputs the emissions recalculation needs that the evidence does not carry. */
  recalculation?: RecalculationSettings;
  /** Workbook data point keys the engagement does not cover (set in Setup's in-scope list). */
  outOfScopeDataPoints?: string[];
}

/** A renewable energy certificate applied to the market-based Scope 2 total. */
export interface RecalculationCertificate {
  label: string;
  mwh: number;
}

/** Stored by the API under settings.recalculation; the backend validates every value. */
export interface RecalculationSettings {
  /** "AR5" (default) or "AR6". */
  gwp_set?: string;
  /** Facility name (as on the bill) to eGRID subregion, e.g. { "Facility A": "NYUP" }. */
  grid_regions?: Record<string, string>;
  /** "stationary:<fuel code>" or "mobile:<fuel code>" to the EPA fuel name chosen for it. */
  fuel_choices?: Record<string, string>;
  certificates?: RecalculationCertificate[];
  /** Reported data point key to the client's reported value. */
  reported?: Record<string, number>;
  /** Refrigerant to the GWP entered from its safety data sheet, for gases the EPA Hub does not list. */
  refrigerant_gwps?: Record<string, number>;
  /** Which vehicles used each mobile fuel, for CH4 and N2O (workbook Eq 4 / Eq 5). */
  vehicle_groups?: VehicleGroupSetting[];
  /** Emission source (roll-up key) to the reviewer's reason the company has none: a true 0. */
  absent_sources?: Record<string, string>;
  /** Per-gas data point (workbook rows 23-28, 30-36) to the unit the company reported it in. */
  reported_units?: Record<string, "t" | "t CO2e">;
}

/** One vehicle group: on-road by distance (and model year where the factor needs it),
 *  non-road by the fuel it used. */
export interface VehicleGroupSetting {
  /** The EPA Table 2 fuel of the reviewed records, e.g. "Diesel Fuel". */
  fuel: string;
  vehicle_type: string;
  /** The fuel as the CH4/N2O table names it, e.g. "Diesel", "Gasoline (4 stroke)". */
  factor_fuel_type: string;
  on_road: boolean;
  model_year?: number;
  distance?: number;
  distance_unit?: "mi" | "km";
  fuel_quantity?: number;
  fuel_unit?: "gal" | "L";
  label?: string;
}
