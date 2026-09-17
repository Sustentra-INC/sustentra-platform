export interface Actor {
  id: string;
  name: string;
  actorType: "preparer" | "reviewer" | "client" | "system";
}

export interface FacilityOption {
  facilityId: string;
  name: string;
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
}
