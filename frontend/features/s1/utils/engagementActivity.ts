import type { EvidenceItem, ReviewValue } from "../types";
import type { Ask } from "../types/requests";
import type { CoverageRule, Examination, Finding } from "../types/verification";
import type { SessionAuditEntry } from "./auditIntent";

/** One line of the engagement's activity log: who did what, when, to which document. */
export interface ActivityEntry {
  at: string;
  who: string;
  what: string;
  /** The document it concerns, when there is one. */
  documentId?: string;
  kind: "upload" | "review" | "request" | "finding" | "document";
}

/** The engagement's history, newest first: uploads, reviews, requests, findings and document edits. */
export function engagementActivity(input: {
  evidence: EvidenceItem[];
  values: ReviewValue[];
  asks: Ask[];
  findings: Finding[];
  intents?: SessionAuditEntry[];
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
      if (entry.kind === "human" && entry.at) {
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
      documentId: intent.documentId,
      kind: "document",
    });
  }
  return log.sort((a, b) => b.at.localeCompare(a.at));
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
  /** Null until coverage has been checked. */
  coverage: { present: number; missing: number; notApplicable: number; outOfScope: number } | null;
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
  const rules = input.coverage;
  const calculated = input.calculatedIds ?? [];
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
          present: rules.filter((r) => r.status === "inputs_present").length,
          missing: rules.filter((r) => r.status === "inputs_missing").length,
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
