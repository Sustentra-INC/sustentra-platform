/**
 * The demo's Methodology review content for Cascade Provisions Co. (2025 GHG assurance, SB 253):
 * what the company's report states (shown as already stated by the company), and what Claude
 * proposes when the reviewer asks it to read the client's reports. Substance follows the older
 * fixture (fixtures/methodology/methodologyReview.ts): operational control, three entities, the
 * Stockton JV outside the boundary, AR5, EPA GHG EF Hub 2025 and eGRID.
 *
 * Quotes are written as the report lines print them; a choice value appears in its quote.
 */
import { engagementConfig } from "../fixtures/engagementConfig";
import { manufacturerEvidence } from "../fixtures/evidence/manufacturerEvidence";

export type SeedValue = string | number | string[] | { [key: string]: string | number | string[] };

/** Document ids come from the Evidence fixtures, so "open document" lands on a real document. */
function doc(filename: string): { document_id: string; file_name: string } {
  const found = manufacturerEvidence.find((d) => d.filename === filename);
  if (!found) throw new Error(`Demo methodology cites ${filename}, which is not in the Evidence fixtures.`);
  return { document_id: found.documentId, file_name: found.filename };
}

export const BOUNDARY_DOC = doc("cascade_org_boundary_statement.pdf");
export const FACILITIES_DOC = doc("cascade_facility_list.pdf");
export const FACTORS_DOC = doc("cascade_emission_factors_2025.pdf");
export const WORKBOOK_DOC = doc("cascade_inventory_workbook_2025.xlsx");
export const PPA_DOC = doc("cascade_ppa_greenpower.pdf");

/** The demo's signed-in verifier: the same person the app shows as the actor elsewhere. */
const member = engagementConfig.engagementTeam?.find((m) => m.login === engagementConfig.signedInLogin);
export const DEMO_ACTOR = { name: member?.name ?? "M. Osei", login: member?.login ?? "mosei" };

/** Who the company's own statements are attributed to. */
export const COMPANY = { name: "Cascade Provisions Co. (stated in report)", login: "company" };

export const AI_MODEL = "claude-sonnet-4-5";

/** Stated by the company in its report: present before Claude reads anything. */
export const COMPANY_STATED: { fieldId: string; value: SeedValue; group?: string }[] = [
  { fieldId: "reporting_period", value: "January 1, 2025 to December 31, 2025" },
  { fieldId: "category:scope1:stationary", value: "Yes" },
  { fieldId: "category:scope1:mobile", value: "Yes" },
  { fieldId: "category:scope1:process", value: "No" },
  { fieldId: "category:scope1:fugitive", value: "Yes" },
  { fieldId: "gwp", value: { set: "AR5", horizon: "100-year" } },
  { fieldId: "exclusion:boundary", value: "Stockton Cold Storage JV (50% equity), which Cascade Provisions does not operate." },
  { fieldId: "factor:scope1:co0001", group: "factor:scope1", value: { database: "U.S. EPA GHG Emission Factors Hub", edition: "2025" } },
  { fieldId: "factor:scope2:co0001", group: "factor:scope2", value: { database: "U.S. EPA eGRID", edition: "eGRID2023" } },
];

export interface ClaudeItem {
  /** A fixed field, or a new row in `rowGroup`. */
  fieldId?: string;
  rowGroup?: "entities" | "factor:scope1" | "factor:scope2";
  rowKey?: string;
  value: SeedValue;
  quote: string;
  source: { document_id: string; file_name: string };
  page: string;
}

const B = BOUNDARY_DOC;
const W = WORKBOOK_DOC;

/** What Claude proposes from the client's documents. Nothing here is pre-accepted. */
export const CLAUDE_ITEMS: ClaudeItem[] = [
  { fieldId: "consolidation_approach", value: "Operational Control", quote: "Cascade Provisions Co. consolidates its 2025 GHG inventory using the operational control approach.", source: B, page: "page 1" },
  { fieldId: "category:location:electricity", value: "Yes", quote: "Purchased electricity is reported on a location-based basis for all three facilities.", source: W, page: "Scope 2 sheet, cell B4" },
  { fieldId: "category:location:heating", value: "Yes", quote: "Purchased heat at Tualatin Plant is reported on a location-based basis.", source: W, page: "Scope 2 sheet, cell B5" },
  { fieldId: "category:location:steam", value: "Yes", quote: "Purchased steam at Kent Cannery is reported on a location-based basis.", source: W, page: "Scope 2 sheet, cell B6" },
  { fieldId: "category:location:cooling", value: "No", quote: "No purchased cooling is used at any facility in 2025.", source: W, page: "Scope 2 sheet, cell B7" },
  { fieldId: "category:market:electricity", value: "Yes", quote: "Market-based electricity applies the Tualatin Plant PPA; other sites use the eGRID subregion rate.", source: W, page: "Scope 2 sheet, cell C4" },
  { fieldId: "category:market:heating", value: "Yes", quote: "Purchased heat at Tualatin Plant is reported on a market-based basis using the supplier factor.", source: W, page: "Scope 2 sheet, cell C5" },
  { fieldId: "category:market:steam", value: "Yes", quote: "Purchased steam at Kent Cannery is reported on a market-based basis.", source: W, page: "Scope 2 sheet, cell C6" },
  { fieldId: "category:market:cooling", value: "No", quote: "No purchased cooling is used at any facility in 2025.", source: W, page: "Scope 2 sheet, cell C7" },
  { fieldId: "category:biogenic:direct", value: "No", quote: "Direct biogenic CO2 emissions are not applicable to the 2025 inventory.", source: B, page: "page 3" },
  { fieldId: "exclusion:inventory", value: "Backup diesel generators at Tualatin Plant; no fuel records for 2025.", quote: "Backup diesel generators at Tualatin Plant are excluded because no fuel records exist for 2025.", source: B, page: "page 5" },
  { fieldId: "exclusion:materiality", value: "Sources below 1% of combined Scope 1 and Scope 2 emissions are treated as de minimis.", quote: "Sources below 1% of combined Scope 1 and Scope 2 emissions are treated as de minimis.", source: B, page: "page 5" },
  { fieldId: "calculation:approach", value: "Activity data multiplied by emission factor. Stationary and mobile fuel from utility bills and fleet fuel cards; refrigerant from service records; electricity, heat and steam from utility and supplier bills.", quote: "Emissions are calculated as activity data multiplied by an emission factor, using utility bills, fleet fuel cards and refrigerant service records.", source: B, page: "page 6" },
  {
    rowGroup: "entities",
    rowKey: "cp",
    value: { name: "Cascade Provisions Co.", facilities: ["Kent Cannery", "Modesto Bottling"], equity_share_pct: 100, financial_control: 100, operational_control: "Yes" },
    quote: "Cascade Provisions Co. (Kent Cannery, Modesto Bottling): 100% equity share, 100% financial control, operational control Yes.",
    source: FACILITIES_DOC,
    page: "page 1",
  },
  {
    rowGroup: "entities",
    rowKey: "td",
    value: { name: "Cascade Provisions Oregon LLC", facilities: ["Tualatin Plant"], equity_share_pct: 100, financial_control: 100, operational_control: "Yes" },
    quote: "Cascade Provisions Oregon LLC (Tualatin Plant): 100% equity share, 100% financial control, operational control Yes.",
    source: FACILITIES_DOC,
    page: "page 1",
  },
  {
    rowGroup: "entities",
    rowKey: "sc",
    value: { name: "Stockton Cold Storage JV", facilities: ["Stockton cold storage"], equity_share_pct: 50, financial_control: 50, operational_control: "No" },
    quote: "Stockton Cold Storage JV (Stockton cold storage): 50% equity share, 50% financial control, operational control No.",
    source: FACILITIES_DOC,
    page: "page 2",
  },
  // Disagrees with the company: the report states eGRID2023, the factor list prints eGRID2021.
  {
    rowGroup: "factor:scope2",
    rowKey: "egrid21",
    value: { database: "U.S. EPA eGRID", edition: "eGRID2021" },
    quote: "Location-based grid factors are taken from the U.S. EPA eGRID eGRID2021 subregion tables.",
    source: FACTORS_DOC,
    page: "page 2",
  },
  {
    rowGroup: "factor:scope2",
    rowKey: "ppa",
    value: { database: "Tualatin Plant Green Power PPA supplier-specific emission rate", edition: "" },
    quote: "Market-based electricity at Tualatin Plant uses the supplier-specific emission rate in the Green Power PPA.",
    source: PPA_DOC,
    page: "page 1",
  },
];
