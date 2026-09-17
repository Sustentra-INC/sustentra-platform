import type { EngagementConfig } from "../types";

/**
 * Fixture engagement: Cascade Provisions Co., a three-facility food
 * manufacturer, 2025 reporting year. Regulation and methodology are stored as
 * real values here (and are live selectors on Setup) — nothing downstream
 * assumes SB 253.
 */
export const engagementConfig: EngagementConfig = {
  clientName: "Cascade Provisions Co.",
  engagementId: "ENG-CASCADE-2025",
  reportingPeriod: {
    start: "2025-01-01",
    end: "2025-12-31",
  },
  facilities: [
    { facilityId: "facility-tualatin", name: "Tualatin Plant" },
    { facilityId: "facility-kent", name: "Kent Cannery" },
    { facilityId: "facility-modesto", name: "Modesto Bottling" },
  ],
  regulation: "California Senate Bill 253",
  regulationJurisdiction:
    "California Senate Bill 253 — Climate Corporate Data Accountability Act (California, USA)",
  methodology: "GHG Protocol Corporate Standard",
  conclusionType: "GHG assurance",
  assuranceLevel: "Limited assurance",
  boundaryApproach: "Operational control",
  scopeBoundaryStatement:
    "Electricity, stationary and mobile combustion, and supporting corporate inventory evidence for in-scope facilities.",
  clientContact: {
    name: "Dana Whitfield",
    email: "dana.whitfield@cascadeprovisions.example",
    company: "Cascade Provisions Co.",
  },
  engagementTeam: [
    { name: "M. Osei", login: "mosei" },
    { name: "R. Iqbal", login: "riqbal" },
    { name: "T. Brandt", login: "tbrandt" },
    { name: "L. Chen", login: "lchen" },
  ],
  signedInLogin: "mosei",
  verifierEmail: "m.osei@verifier.example",
};
