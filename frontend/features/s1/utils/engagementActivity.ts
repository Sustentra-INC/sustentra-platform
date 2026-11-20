import { METHOD_CHECK_RULE_IDS } from "../api/recalculation";
import type { EvidenceItem, ReviewValue } from "../types";
import type { Ask } from "../types/requests";
import type { CoverageRule, Examination, Finding } from "../types/verification";
import type { EvidenceActivityItem } from "../api/evidenceTree";
import type { SessionAuditEntry } from "./auditIntent";

/** One line of the engagement's activity log: who did what, when, to which document. */
export interface ActivityEntry {
  at: string;
  who: string;
  what: string;
  /** The document it concerns, when there is one. */
  documentId?: string;
  kind: "upload" | "review" | "request" | "finding" | "document" | "methodology";
}

/** The engagement's history, newest first: uploads, reviews, requests, findings and document edits. */
export function engagementActivity(input: {
  evidence: EvidenceItem[];
  values: ReviewValue[];
  asks: Ask[];
  findings: Finding[];
  intents?: SessionAuditEntry[];
  /** Line and placement changes on the Evidence page, as the server recorded them. */
  evidenceEvents?: EvidenceActivityItem[];
  /** Methodology review changes, oldest first. */
  methodology?: { at: string; who: string; what: string }[];
}): ActivityEntry[] {
  const log: ActivityEntry[] = [];
  const filename = new Map(input.evidence.map((e) => [e.documentId, e.filename]));
  for (const item of input.evidence) {
    log.push({
      at: item.uploadedAt,
      who: item.uploadedBy.name,
      what:
        item.answeredRequestNumber != null
          ? `uploaded ${item.filename}, answering request ${item.answeredRequestNumber}`
          : `uploaded ${item.filename}`,
      documentId: item.documentId,
      kind: "upload",
    });
  }
  for (const value of input.values) {
    for (const entry of value.record) {
      // A request's outcome on a card ("Request 3 resolved") is the request's own event, which
      // its history logs once below: it is not a review, and not one entry per value.
      if (entry.kind === "human" && entry.at && !entry.outcomeOf) {
        log.push({
          at: entry.at,
          who: entry.actor,
          what: `${entry.action}: ${value.whatItIs} (${value.filename})`,
          documentId: value.documentId,
          kind: "review",
        });
      }
    }
  }
  for (const ask of input.asks) {
    for (const event of ask.history) {
      log.push({
        at: event.at,
        who: event.actorName,
        what: `${event.kind} a request: ${ask.source.itemLabel}`,
        documentId: ask.source.documentId ?? undefined,
        kind: "request",
      });
    }
  }
  for (const finding of input.findings) {
    if (finding.registeredAt) {
      log.push({
        at: finding.registeredAt,
        who: finding.registeredBy ?? "Reviewer",
        what: `registered a finding on ${finding.dataPointLabel}`,
        kind: "finding",
      });
    }
  }
  for (const intent of input.intents ?? []) {
    const name = filename.get(intent.documentId) ?? intent.documentId;
    const change = intent.newValue ? `: ${intent.newValue}` : "";
    log.push({
      at: intent.timestamp,
      who: intent.actor.name,
      what: `${intent.action.replaceAll("_", " ")} on ${name}${change}`,
      documentId: intent.documentId || undefined,
      kind: "document",
    });
  }
  for (const event of input.evidenceEvents ?? []) {
    log.push({
      at: event.at,
      who: event.actor_name ?? "A team member",
      what: evidenceEventText(event, filename),
      documentId: event.document_id,
      kind: "document",
    });
  }
  for (const change of input.methodology ?? []) {
    log.push({ at: change.at, who: change.who, what: change.what, kind: "methodology" });
  }
  return log.sort((a, b) => b.at.localeCompare(a.at));
}

/** One Evidence change as a sentence: "moved a.pdf from Natural gas · Kent to Unassigned supporting evidence". */
function evidenceEventText(event: EvidenceActivityItem, filename: Map<string, string>): string {
  const line = (label: string | undefined, level2?: string) => (level2 && label ? `${level2} · ${label}` : label ?? "a line");
  switch (event.event_type) {
    case "evidence_line_created":
      return `added the line ${line(event.label, event.level2_label)}`;
    case "evidence_line_renamed":
      return `renamed the line ${event.old_label ?? ""} to ${event.new_label ?? ""}`.replace("  ", " ");
    case "evidence_line_deleted": {
      const n = event.documents_moved ?? 0;
      const moved = n === 0 ? "" : n === 1 ? ", moving 1 document to Unassigned supporting evidence" : `, moving ${n} documents to Unassigned supporting evidence`;
      return `deleted the line ${event.label ?? ""}${moved}`;
    }
    case "evidence_document_moved":
      return `moved ${(event.document_id && filename.get(event.document_id)) || "a document"} from ${event.from_label ?? "its place"} to ${event.to_label ?? "another place"}`;
    case "evidence_document_facility_set":
      return `placed ${(event.document_id && filename.get(event.document_id)) || "a document"} on ${event.facility_name ?? "a facility"}${event.suggested ? ", as Claude suggested" : ""}`;
  }
}

/** The figures the dashboard shows, from the engagement's state (either data mode). */
export interface DashboardFigures {
  documents: number;
  documentsReadable: number;
  blockedDocuments: number;
  documentsNeedingYou: number;
  valuesReviewed: number;
  valuesToReview: number;
  requestsNotSent: number;
  requestsAwaitingClient: number;
  requestsResolved: number;
  requestsRaised: number;
  /**
   * The evidence checks, by status; null until coverage has been checked. Method checks
   * (reporting period, GWP basis, reported totals, reviewer decisions) are not evidence
   * and are not counted here.
   */
  coverage: {
    /** Data points with their reviewed inputs in. */
    present: number;
    /** Data points whose documents are in but whose values wait for review. */
    awaitingReview: number;
    /** Data points that need a choice first (grid region, fuel, vehicle groups, a GWP). */
    needsChoice: number;
    /** Data points with no evidence at all. */
    missing: number;
    /** Data points whose documents are in: present, awaiting review or needing a choice. */
    obtained: number;
    /** Every in-scope data point: obtained plus missing. */
    inScope: number;
    notApplicable: number;
    outOfScope: number;
  } | null;
  /**
   * The engagement's reporting period is missing a date. Set by the live dashboard from the
   * engagement itself, so fixing the period in Setup clears it at once (absent: it is not).
   */
  reportingPeriodIncomplete?: boolean;
  /**
   * How many headline totals have a recalculated value but no reported total to compare it
   * with. Set by the live dashboard from the recalculation (absent: none).
   */
  reportedTotalsMissing?: number;
  dataPointsCalculated: number;
  dataPointsExamined: number;
  findings: number;
}

export function dashboardFigures(input: {
  evidence: EvidenceItem[];
  values: ReviewValue[];
  asks: Ask[];
  findings: Finding[];
  coverage: CoverageRule[] | null;
  examinations?: Record<string, Examination>;
  /** Data points that have a recalculated value (verification results). */
  calculatedIds?: string[];
}): DashboardFigures {
  const documents = input.evidence.filter((e) => e.disposition !== "withdrawn");
  const values = input.values.filter((v) => !v.withdrawn);
  const rules = input.coverage?.filter((r) => !METHOD_CHECK_RULE_IDS.includes(r.ruleId)) ?? null;
  const calculated = input.calculatedIds ?? [];
  const notReady = rules?.filter((r) => r.status === "inputs_missing") ?? [];
  const waiting = notReady.filter((r) => r.missingBecause === "awaiting_review").length;
  const choice = notReady.filter((r) => r.missingBecause === "needs_input").length;
  const absent = notReady.length - waiting - choice;
  const present = rules?.filter((r) => r.status === "inputs_present").length ?? 0;
  return {
    documents: documents.length,
    documentsReadable: documents.filter((e) => e.processingState === "extracted").length,
    blockedDocuments: documents.filter((e) => e.processingState === "blocked").length,
    documentsNeedingYou: documents.filter(
      (e) => e.detectedType == null || (!e.typeConfirmed && e.typeReviewBand === "cannot_determine") || e.facilityState === "unresolved"
    ).length,
    valuesReviewed: values.filter((v) => v.reviewState === "accepted" || v.reviewState === "corrected").length,
    valuesToReview: values.filter((v) => v.reviewState === "to_review").length,
    requestsNotSent: input.asks.filter((a) => a.state === "not_yet_sent").length,
    requestsAwaitingClient: input.asks.filter((a) => a.state === "requested").length,
    requestsResolved: input.asks.filter((a) => a.state === "resolved").length,
    requestsRaised: input.asks.filter((a) => a.state !== "withdrawn").length,
    coverage: rules
      ? {
          present,
          awaitingReview: waiting,
          needsChoice: choice,
          missing: absent,
          obtained: present + waiting + choice,
          inScope: present + notReady.length,
          notApplicable: rules.filter((r) => r.status === "not_applicable").length,
          outOfScope: rules.filter((r) => r.status === "out_of_scope").length,
        }
      : null,
    dataPointsCalculated: calculated.length,
    dataPointsExamined: calculated.filter(
      (id) => input.examinations?.[id] && input.examinations[id].examinationState !== "not_examined"
    ).length,
    findings: input.findings.length,
  };
}
