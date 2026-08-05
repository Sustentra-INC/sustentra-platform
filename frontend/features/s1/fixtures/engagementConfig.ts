import type { EngagementConfig } from "../types";

export const engagementConfig: EngagementConfig = {
  clientName: "SCE Manufacturing",
  engagementId: "ENG-S1-2025",
  reportingPeriod: {
    start: "2025-01-01",
    end: "2025-12-31",
  },
  facilities: [
    { facilityId: "facility-riverside", name: "Riverside Plant" },
    { facilityId: "facility-ontario", name: "Ontario Plant" },
    { facilityId: "facility-fresno", name: "Fresno Plant" },
  ],
  regulation: "NY Part 253",
  conclusionType: "GHG assurance",
  assuranceLevel: "Limited assurance",
  boundaryApproach: "Operational control",
  scopeBoundaryStatement:
    "Electricity, stationary combustion, and supporting corporate inventory evidence for in-scope facilities.",
};
