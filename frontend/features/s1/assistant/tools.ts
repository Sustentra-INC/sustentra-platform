import type { EngagementConfig, EvidenceItem, ReviewValue } from "../types";
import type { Ask } from "../types/requests";
import type { CoverageRule, Examination, Finding } from "../types/verification";
import type { ResultLine } from "../types/verificationResults";
import type { ActivityEntry, DashboardFigures } from "../utils/engagementActivity";
import { buildResultBoxes, examinationKey } from "../utils/verificationTable";

/**
 * The assistant's tools, run in the browser over the engagement data the signed-in user
 * already sees: the same records, the same organization. Read-only. Each returns compact
 * JSON with refs ([doc:…], [val:…], [req:…], [chk:…]) the model cites and the panel
 * turns into links.
 */

export interface AssistantData {
  engagement: EngagementConfig;
  evidence: EvidenceItem[];
  values: ReviewValue[];
  asks: Ask[];
  coverage: CoverageRule[] | null;
  /** Verification results lines, when the screen has them. */
  resultLines: ResultLine[] | null;
  examinations: Record<string, Examination>;
  findings: Finding[];
  activity: ActivityEntry[];
  figures: DashboardFigures;
}

const MAX_DOCUMENTS = 30;
const MAX_VALUES = 40;
/** A tool result never exceeds this many characters. */
const MAX_RESULT_CHARS = 18_000;

export function runAssistantTool(name: string, input: Record<string, unknown>, data: AssistantData): string {
  const out = (() => {
    switch (name) {
      case "get_engagement":
        return engagement(data);
      case "search_documents":
        return searchDocuments(data, input);
      case "get_values":
        return getValues(data, input);
      case "get_coverage":
        return data.coverage
          ? { checks: data.coverage.map((r) => ({ ref: `chk:${r.ruleId}`, check: r.assertion, data_points: r.appliesTo, status: r.status, reason: r.reason })) }
          : { note: "Coverage has not been worked out for this engagement yet." };
      case "get_requests":
        return getRequests(data, input);
      case "get_results":
        return getResults(data);
      case "get_activity": {
        const limit = Math.min(Math.max(Number(input.limit) || 25, 1), 60);
        return { entries: data.activity.slice(0, limit).map((a) => ({ at: a.at, who: a.who, what: a.what, ...(a.documentId ? { ref: `doc:${a.documentId}` } : {}) })) };
      }
      case "lookup_reference":
        return lookupReference(String(input.topic ?? ""));
      default:
        return { error: `Unknown tool ${name}.` };
    }
  })();
  const json = JSON.stringify(out);
  return json.length > MAX_RESULT_CHARS ? `${json.slice(0, MAX_RESULT_CHARS)}… (cut: narrow the search)` : json;
}

/* ================================ engagement ================================ */

function engagement(data: AssistantData) {
  const e = data.engagement;
  return {
    client: e.clientName,
    engagement: e.engagementName ?? e.engagementId,
    reporting_period: e.reportingPeriod,
    regulation: e.regulation,
    methodology: e.methodology ?? null,
    data_scope: e.dataScope ?? null,
    assurance_level: e.assuranceLevel,
    assurance_standard: e.assuranceStandard ?? null,
    materiality_threshold: e.materialityThreshold ?? null,
    facilities: e.facilities.map((f) => ({ name: f.name, address: f.address ?? null })),
    team: (e.engagementTeam ?? []).map((m) => m.name),
    client_contact: e.clientContact ? { name: e.clientContact.name, company: e.clientContact.company } : null,
    progress: data.figures,
  };
}

/* ================================= documents ================================= */

function statusOf(item: EvidenceItem): string {
  if (item.disposition === "withdrawn") return "withdrawn";
  if (item.processingState === "blocked") return "blocked";
  if (item.detectedType == null || item.facilityState === "unresolved") return "needs_you";
  if (item.processingState === "extracted") return "extracted";
  return "extracting";
}

const has = (hay: string | null | undefined, needle: unknown) =>
  !needle || (hay ?? "").toLowerCase().includes(String(needle).toLowerCase());

function searchDocuments(data: AssistantData, input: Record<string, unknown>) {
  const matches = data.evidence.filter((item) => {
    const hay = [item.filename, item.detectedType, item.facilityName, item.periodStart].join(" ");
    return (
      words(input.query).every((w) => has(hay, w)) &&
      has(item.facilityName, input.facility) &&
      has(item.detectedType, input.type) &&
      (!input.status || statusOf(item) === String(input.status))
    );
  });
  const valueCount = new Map<string, number>();
  for (const v of data.values) valueCount.set(v.documentId, (valueCount.get(v.documentId) ?? 0) + 1);
  return {
    total: matches.length,
    shown: Math.min(matches.length, MAX_DOCUMENTS),
    documents: matches.slice(0, MAX_DOCUMENTS).map((item) => ({
      ref: `doc:${item.documentId}`,
      file: item.filename,
      type: item.detectedType ?? "type not set",
      facility: item.facilityName ?? (item.facilityState === "multiple" ? "multiple facilities" : item.facilityState === "not_facility_scoped" ? "entity-level" : "not yet known"),
      period: item.periodStart && item.periodEnd ? `${item.periodStart} to ${item.periodEnd}` : null,
      status: statusOf(item),
      ...(item.haltReason ? { why_blocked: item.haltReason } : {}),
      ...(item.missingFields?.length ? { not_found: item.missingFields } : {}),
      values_read: valueCount.get(item.documentId) ?? 0,
      uploaded: { by: item.uploadedBy.name, at: item.uploadedAt },
      ...(item.notes?.length ? { notes: item.notes.map((n) => `${n.author}: ${n.text}`) } : {}),
      ...(item.relationships.length ? { related: item.relationships.map((r) => `${r.kind} ${r.otherDocumentId}`) } : {}),
    })),
  };
}

function words(query: unknown): string[] {
  return String(query ?? "")
    .toLowerCase()
    .split(/\s+/)
    .filter((w) => w.length > 1);
}

/* =================================== values =================================== */

function getValues(data: AssistantData, input: Record<string, unknown>) {
  const facilityName = (id: string | null) => data.engagement.facilities.find((f) => f.facilityId === id)?.name ?? null;
  const docId = input.document_id ? String(input.document_id).replace(/^doc:/, "") : null;
  const matches = data.values.filter((v) => {
    const hay = [v.whatItIs, v.filename, v.documentType, v.period, v.value].join(" ");
    return (
      (!docId || v.documentId === docId) &&
      has(facilityName(v.facilityId), input.facility) &&
      words(input.query).every((w) => has(hay, w)) &&
      (!input.review_state || v.reviewState === String(input.review_state))
    );
  });
  const states = { to_review: 0, accepted: 0, corrected: 0, requested: 0 };
  matches.forEach((v) => (states[v.reviewState] += 1));
  return {
    total: matches.length,
    by_review_state: states,
    shown: Math.min(matches.length, MAX_VALUES),
    values: matches.slice(0, MAX_VALUES).map((v) => ({
      ref: `val:${v.id}`,
      what: v.whatItIs,
      value: v.missing || v.value === "not found" ? "not found on the document" : `${v.value}${v.unit ? ` ${v.unit}` : ""}`,
      scope: v.scope,
      period: v.period,
      facility: facilityName(v.facilityId) ?? (v.entityLevel ? "entity-level" : "not yet known"),
      document: { ref: `doc:${v.documentId}`, file: v.filename, page: v.page },
      review_state: v.reviewState,
      ...(v.originalValue ? { read_as: v.originalValue } : {}),
      record: v.record.map((r) => `${r.actor} ${r.action}${r.reason ? ` (${r.reason})` : ""}`),
    })),
  };
}

/* ================================== requests ================================== */

function getRequests(data: AssistantData, input: Record<string, unknown>) {
  const asks = data.asks.filter((a) => !input.state || a.state === String(input.state));
  return {
    total: asks.length,
    requests: asks.map((a) => ({
      ref: `req:${a.id}`,
      item: a.source.itemLabel,
      type: a.type,
      facility: a.source.facilityName,
      period: a.source.period,
      what_is_needed: a.whatIsNeeded,
      state: a.state,
      ...(a.requestNumber ? { request_number: a.requestNumber } : {}),
      ...(a.source.documentId ? { document: `doc:${a.source.documentId}` } : {}),
      raised_by: a.raisedByName,
      history: a.history.map((h) => `${h.at.slice(0, 10)} ${h.actorName} ${h.kind}`),
    })),
  };
}

/* =================================== results =================================== */

function getResults(data: AssistantData) {
  if (!data.resultLines) return { note: "Verification results are not loaded on this screen yet." };
  const lines = data.resultLines;
  const boxes = buildResultBoxes(lines, (lineId, facilityId) => {
    const exam = data.examinations[examinationKey(lineId, facilityId)];
    return Boolean(exam && exam.examinationState !== "not_examined");
  });
  const round = (n: number | null) => (n === null ? null : Math.round(n));
  const pct = (n: number | null) => (n === null ? null : `${(n * 100).toFixed(1)}%`);
  return {
    materiality_threshold: data.engagement.materialityThreshold ?? null,
    boxes: boxes.map((box) => ({
      box: box.title,
      total: {
        reported: round(box.totals.reported),
        recomputed: round(box.totals.recomputed),
        difference: round(box.totals.difference),
        pct_material: pct(box.totals.pctMaterial),
        coverage: pct(box.totals.share),
        examined: `${box.totals.examined} of ${box.totals.facilities} facility rows`,
      },
      lines: box.rows
        .filter((r) => r.line)
        .map((r) => ({
          activity: r.activity,
          reported: round(r.reported),
          recomputed: round(r.recomputed),
          difference: round(r.difference),
          pct_material: pct(r.pctMaterial),
          facilities: (r.line?.facilities ?? []).map((f) => ({
            facility: f.facility,
            reported: round(f.reported),
            recomputed: round(f.recomputed),
            cause: f.cause,
            examined: Boolean(data.examinations[examinationKey(r.key, f.facilityId)] && data.examinations[examinationKey(r.key, f.facilityId)].examinationState !== "not_examined"),
          })),
        })),
    })),
    findings: data.findings.map((f) => ({ data_point: f.dataPointLabel, sentence: f.sentence, status: f.status })),
  };
}

/* ================================== reference ================================== */

const REFERENCE: Record<string, string> = {
  sb253:
    "California SB 253 (Climate Corporate Data Accountability Act). Applies to US entities doing business in California " +
    "with total annual revenue above $1 billion. Scope 1 and Scope 2 are reported from 2026 on 2025 data; Scope 3 from 2027. " +
    "Assurance: limited assurance on Scope 1 and 2 from the start, reasonable assurance from 2030; Scope 3 limited " +
    "assurance from 2030. Administered by the California Air Resources Board (CARB); emissions are measured to the GHG Protocol.",
  ghg_protocol_scopes:
    "GHG Protocol Corporate Standard. Scope 1: direct emissions from sources the company owns or controls (fuel burned on " +
    "site, company vehicles, refrigerant leaks, process emissions). Scope 2: indirect emissions from purchased electricity, " +
    "steam, heating and cooling. Scope 3: other indirect emissions in the value chain. Biogenic CO2 is reported separately, " +
    "outside the scopes. The boundary follows a consolidation approach: operational control, financial control or equity share.",
  scope2_methods:
    "Scope 2 is reported two ways. Location-based: grid-average factors for where the electricity is used (in the US, the " +
    "eGRID subregion). Market-based: factors from the contracts and instruments the company chose (renewable energy " +
    "certificates, supplier-specific rates, PPAs), with a residual mix where it has none. Instruments must meet quality " +
    "criteria (vintage, market boundary, one claim per MWh).",
  materiality:
    "Materiality in Sustentra: set in Setup as a share of the total (for example 5%). For each line, the difference is " +
    "recomputed minus reported, % difference is the difference over reported, share is the line's reported over the box " +
    "total, and % material is % difference times share. A box's % material adds up its lines; differences beyond the " +
    "threshold, alone or together, are material.",
  limited_assurance:
    "Limited assurance (ISO 14064-3, ISAE 3410): the verifier performs fewer procedures than for reasonable assurance and " +
    "gives a negative-form conclusion: nothing has come to the verifier's attention that the statement is materially " +
    "misstated. Evidence is still traced to source for the lines the verification plan selects.",
  emission_factors:
    "Factors used: EPA GHG Emission Factors Hub (2025) for fuels, for example natural gas 53.06 kg CO2, 1 g CH4 and 0.1 g N2O " +
    "per MMBtu; diesel 10.21 kg CO2 per gallon. Electricity, location-based: eGRID2023 subregion factors (for example NWPP " +
    "for Oregon and Washington, CAMX for California). GWPs: IPCC AR5 (CH4 28, N2O 265).",
  refrigerants:
    "Refrigerant emissions use the GHG Protocol material balance: (P_N − C_N) + P_S + (C_D − R_D), the refrigerant in new " +
    "equipment minus its capacity, plus refrigerant added in service, plus the capacity of retired equipment minus what was " +
    "recovered from it, times the refrigerant's GWP (R-404A: 3,943 under AR5). CFCs and HCFCs are reported separately.",
  coverage:
    "Coverage shows what can and cannot be checked with the evidence held. Inputs present: the evidence and reviewed values " +
    "a check needs are in. Inputs missing: something is missing, and a request to the client can be raised. Not applicable " +
    "or out of scope: the check does not apply. It states input readiness, not a pass or fail.",
  review_states:
    "Each value read from a document is to review until the auditor acts: accepted (as read), corrected (changed, with the " +
    "value as read kept beside it), or requested (asked of the client). A value the reviewer keys by hand counts as " +
    "reviewed. Only reviewed values count toward coverage and the recomputation.",
  requests:
    "Requests are asks to the client: missing document, replace document, missing data, clarify, or confirm or restate. " +
    "They are raised from a document, a value or a check missing its inputs, sent together in one message, and resolved by " +
    "hand when the answer arrives. Sustentra does not email the client yet: the auditor copies the message or opens it in mail.",
  sustentra_workflow:
    "The Sustentra workflow: Setup (engagement, facilities, scope, materiality) → Evidence (upload, documents read and " +
    "typed) → Extraction review (accept or correct each value against its document) → Coverage & requests (what can be " +
    "checked, what to ask for) → Verification results (reported vs recomputed, each difference explained, rows examined) " +
    "→ Output (workbook, statement).",
};

function lookupReference(topic: string) {
  const key = topic.toLowerCase().replace(/[^a-z0-9_]/g, "");
  const text = REFERENCE[key];
  return text ? { ref: `ref:${key}`, text } : { error: `No reference on "${topic}". Topics: ${Object.keys(REFERENCE).join(", ")}.` };
}
