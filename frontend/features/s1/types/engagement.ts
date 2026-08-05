export interface Actor {
  id: string;
  name: string;
  actorType: "preparer" | "reviewer" | "client" | "system";
}

export interface FacilityOption {
  facilityId: string;
  name: string;
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
}
