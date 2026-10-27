import type { EvidenceItem, ExtractedField } from "../types";
import type { ReviewValue, ScopePlacement, SourceKind, ValueRecordEntry } from "../types/review";
import type { Ask } from "../types/requests";
import { resolveCanonicalTypeDisplayName } from "./evidenceAdapter";
import { anchorOf } from "../utils/sourceAnchor";
import { decodeReviewCandidateToken } from "./fieldAdapter";

/**
 * Extracted fields from the backend (one per candidate) as Extraction Review cards.
 * Only values the extractor found are cards: an empty field has nothing to accept
 * and stays visible as "n of m fields" in the Evidence Workspace.
 */
/** Fields the numbers depend on: when one is not found, the reviewer gets a card to enter it. */
const KEY_FIELDS = new Set([
  "fuel_type",
  "activity_quantity",
  "activity_unit",
  "service_period_start",
  "service_period_end",
  "transaction_date",
  "facility_name",
  "service_address",
  // refrigerant service records (simplified material balance)
  "refrigerant_type",
  "refrigerant_added",
  "refrigerant_recovered",
  "equipment_capacity",
  "service_date",
]);

export function reviewValuesFromFields(fields: ExtractedField[], evidence: EvidenceItem[]): ReviewValue[] {
  const documents = new Map(evidence.map((item) => [item.documentId, item]));
  const periods = periodsByDocument(fields);
  const seen = new Map<string, number>();

  return fields
    .filter(
      (field) =>
        field.value !== null || field.correctedValue !== null || KEY_FIELDS.has(fieldNameOf(field) ?? "")
    )
    .map((field) => {
      const document = documents.get(field.documentId);
      const location = field.location;
      const candidate = field.reviewToken ? decodeReviewCandidateToken(field.reviewToken) : null;
      const rawValue = candidate?.raw_value ?? candidate?.normalized_value;
      const page = location?.kind === "page" ? location.page : 1;
      const accepted = field.reviewStatus === "accepted";
      const corrected = field.reviewStatus === "corrected" || field.reviewStatus === "keyed_by_reviewer";
      // A card id must be unique even if an extraction repeats a candidate id.
      const repeat = seen.get(field.fieldKey) ?? 0;
      seen.set(field.fieldKey, repeat + 1);
      return {
        id: repeat ? `${field.fieldKey}#${repeat + 1}` : field.fieldKey,
        documentId: field.documentId,
        filename: document?.filename ?? field.documentId,
        documentType:
          document?.detectedType ??
          resolveCanonicalTypeDisplayName({ canonical_type_id: field.canonicalTypeId }) ??
          "Unclassified document",
        facilityId: null,
        notYetKnown: true,
        period: periods.get(field.documentId) ?? "Period not extracted",
        whatItIs: field.fieldLabel,
        scope: scopeOf(field.canonicalTypeId),
        value: (corrected ? field.correctedValue : field.value) ?? "",
        unit: (corrected ? field.correctedUnit ?? field.unit : field.unit) ?? "",
        methodologyFieldId: fieldNameOf(field) ?? undefined,
        reviewState: accepted ? "accepted" : corrected ? "corrected" : "to_review",
        originalValue: corrected ? field.value : undefined,
        record: [
          {
            kind: "machine",
            actor: "Extraction",
            at: document?.uploadedAt ?? "",
            action: field.value === null ? "did not find this on the document" : field.snippet ? `read "${field.snippet}"` : "extracted",
          },
          ...(accepted || corrected
            ? [{
                kind: "human" as const,
                actor: field.reviewedBy ?? "Reviewer",
                at: field.reviewedAt ?? "",
                action: accepted
                  ? "accepted as read"
                  : field.value === null
                    ? "entered a value the extractor did not find"
                    : `corrected from ${field.value}${field.unit ? ` ${field.unit}` : ""}`,
              }]
            : []),
        ],
        sourceKind: sourceKindOf(document?.format),
        page,
        pageCount: page,
        span:
          location?.kind === "page" && location.region
            ? { page: location.page, ...location.region }
            : null,
        snippet: field.snippet,
        sheet: location?.kind === "cells" ? location.sheet : null,
        cell: location?.kind === "cells" ? location.range : null,
        anchor: field.value === null ? null : anchorOf(document?.format, candidate?.source_reference),
        rawText: rawValue === null || rawValue === undefined ? null : String(rawValue),
        reviewToken: field.reviewToken,
        missing: field.value === null && field.correctedValue === null,
      } satisfies ReviewValue;
    });
}

function fieldNameOf(field: ExtractedField): string | null {
  const candidate = field.reviewToken ? decodeReviewCandidateToken(field.reviewToken) : null;
  return typeof candidate?.field_name === "string" ? candidate.field_name : null;
}

/** "2025-01-01 to 2025-06-30" from a document's service period, or the span of its
 *  transaction or service dates (fuel purchases and refrigerant service have a date,
 *  not a billing period). */
function periodsByDocument(fields: ExtractedField[]): Map<string, string> {
  const found = new Map<string, { start: Set<string>; end: Set<string>; dates: string[] }>();
  for (const field of fields) {
    const name = fieldNameOf(field);
    const value = field.correctedValue ?? field.value;
    if (!value || !name || !["service_period_start", "service_period_end", "transaction_date", "service_date"].includes(name)) continue;
    const entry = found.get(field.documentId) ?? { start: new Set(), end: new Set(), dates: [] };
    if (name === "service_period_start") entry.start.add(value);
    else if (name === "service_period_end") entry.end.add(value);
    else entry.dates.push(value);
    found.set(field.documentId, entry);
  }
  const out = new Map<string, string>();
  found.forEach(({ start, end, dates }, documentId) => {
    if (start.size || end.size) {
      if (start.size > 1 || end.size > 1) {
        const first = [...start].sort()[0];
        const last = [...end].sort().at(-1);
        out.set(documentId, first && last ? `${first} to ${last}` : "Several service periods");
      } else out.set(documentId, `${[...start][0] ?? "?"} to ${[...end][0] ?? "?"}`);
    } else if (dates.length) {
      const sorted = [...dates].sort();
      out.set(documentId, sorted[0] === sorted.at(-1) ? sorted[0] : `${sorted[0]} to ${sorted.at(-1)}`);
    }
  });
  return out;
}

function scopeOf(canonicalTypeId: string | null): ScopePlacement {
  if (canonicalTypeId === "CT-S2-ELEC" || canonicalTypeId === "CT-S2-THERMAL") return "scope2_location";
  if (canonicalTypeId?.startsWith("CT-S1-")) return "scope1";
  return "not_placed";
}

function sourceKindOf(format: EvidenceItem["format"] | undefined): SourceKind {
  if (format === "pdf") return "pdf";
  if (format === "image") return "image";
  if (format === "xlsx" || format === "csv") return "spreadsheet";
  return "text";
}

/**
 * The engagement's asks laid over the review values, so a card's request decides its state the
 * same way in the session and after a reload. The review API records accepts and corrections
 * only; an ask is saved with the requests and names the card it was raised from
 * (`source.fieldKey`, the card id, which is the candidate id and the same on every load). In the
 * session, the record of every value the request was raised for also points at the ask.
 *
 * A card not accepted or corrected follows its latest request (as the card's chip does): while
 * that request is not yet sent, or sent and waiting, the card is "requested"; once it is
 * resolved or withdrawn, the card is back to review, so it can be accepted or requested again.
 * Its record keeps the line that added it to requests and a line with each request's outcome
 * ("Request 3 resolved", "Request withdrawn"). A card accepted or corrected keeps that state,
 * with the same lines. A follow-up is raised from the request, not the card: it adds no
 * "added to requests" line, but it is the card's latest request.
 */
export function withRequestsFromAsks(values: ReviewValue[], asks: Ask[]): ReviewValue[] {
  const fromCards = asks.filter((ask) => ask.source.origin === "review_value");
  if (fromCards.length === 0) return values;
  const byId = new Map(fromCards.map((ask) => [ask.id, ask]));
  // The values each ask is for: its card, every value whose record points at it, and (for a
  // follow-up) the values of the request it follows.
  const recordedFor = new Map<string, Set<string>>();
  for (const value of values) {
    for (const entry of value.record) {
      if (entry.askId) recordedFor.set(entry.askId, (recordedFor.get(entry.askId) ?? new Set()).add(value.id));
    }
  }
  const forValues = (ask: Ask, seen = new Set<string>()): Set<string> => {
    const ids = new Set(recordedFor.get(ask.id) ?? []);
    if (ask.source.fieldKey) ids.add(ask.source.fieldKey);
    const from = ask.linkedFromAskId ? byId.get(ask.linkedFromAskId) : undefined;
    if (from && !seen.has(from.id)) forValues(from, seen.add(ask.id)).forEach((id) => ids.add(id));
    return ids;
  };
  const byValue = new Map<string, Ask[]>();
  for (const ask of fromCards) {
    forValues(ask).forEach((id) => byValue.set(id, [...(byValue.get(id) ?? []), ask]));
  }
  return values.map((value) => {
    const linked = byValue.get(value.id);
    if (!linked) return value;
    const added = new Set(value.record.flatMap((entry) => (entry.askId ? [entry.askId] : [])));
    const settled = new Set(value.record.flatMap((entry) => (entry.outcomeOf ? [entry.outcomeOf] : [])));
    const lines: ValueRecordEntry[] = [
      ...linked
        .filter((ask) => !ask.linkedFromAskId && !added.has(ask.id))
        .map((ask): ValueRecordEntry => ({ kind: "human", actor: ask.raisedByName, at: ask.raisedAt, action: "added to requests", askId: ask.id })),
      ...linked.filter((ask) => !settled.has(ask.id)).flatMap(outcomeLine),
    ];
    const open = isOpen(latestOf(linked));
    const undecided = value.reviewState === "to_review" || value.reviewState === "requested";
    return {
      ...value,
      reviewState: undecided ? (open ? "requested" : "to_review") : value.reviewState,
      record: lines.length ? inTimeOrder([...value.record, ...lines]) : value.record,
    };
  });
}

/** The card's latest request: the one raised last (a follow-up comes after the request it follows). */
function latestOf(asks: Ask[]): Ask {
  return asks.reduce((latest, ask) => (ask.raisedAt >= latest.raisedAt ? ask : latest));
}

/** Not yet sent, or sent and waiting on the client. */
function isOpen(ask: Ask): boolean {
  return ask.state === "not_yet_sent" || ask.state === "requested";
}

/** A request's outcome on the card's record: "Request 3 resolved", "Request withdrawn". */
function outcomeLine(ask: Ask): ValueRecordEntry[] {
  if (ask.state !== "resolved" && ask.state !== "withdrawn") return [];
  const event = [...ask.history].reverse().find((e) => e.kind === ask.state);
  const name = ask.requestNumber != null ? `Request ${ask.requestNumber}` : "Request";
  const reason = ask.state === "withdrawn" ? ask.withdrawReason : ask.resolution?.note;
  return [
    {
      kind: "human",
      actor: event?.actorName ?? ask.resolution?.by ?? ask.raisedByName,
      at: event?.at ?? ask.resolution?.at ?? ask.raisedAt,
      action: `${name} ${ask.state}`,
      ...(reason ? { reason } : {}),
      outcomeOf: ask.id,
    },
  ];
}

/** The reading first, then what people did, oldest first (a line with no time stays last). */
function inTimeOrder(record: ValueRecordEntry[]): ValueRecordEntry[] {
  const time = (entry: ValueRecordEntry) => {
    const t = Date.parse(entry.at);
    return Number.isNaN(t) ? Number.POSITIVE_INFINITY : t;
  };
  return [
    ...record.filter((entry) => entry.kind === "machine"),
    ...record.filter((entry) => entry.kind !== "machine").sort((a, b) => time(a) - time(b)),
  ];
}
