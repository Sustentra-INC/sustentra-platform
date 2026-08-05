"use client";

import { useEffect, useMemo, useState } from "react";

import { EXACT_COPY } from "../constants/copy";
import { useKeyboardNavigation } from "../hooks/useKeyboardNavigation";
import type { AuditIntent } from "../utils/auditIntent";
import { createAuditIntent, createCorrectionAuditIntents } from "../utils/auditIntent";
import type { EvidenceItem, ExtractedField } from "../types";
import { StateIndicator } from "./StateIndicator";

interface ExtractionReviewProps {
  documents: EvidenceItem[];
  fields: ExtractedField[];
  initialDocumentId: string;
  auditIntents: AuditIntent[];
  onAuditIntent: (intent: AuditIntent) => void;
  onPersistReview?: (payload: {
    field: ExtractedField;
    decision: "accepted" | "edited";
    reviewedValue?: string | null;
    reviewerNote?: string | null;
  }) => Promise<void>;
  onBack: () => void;
}

export function ExtractionReview({
  documents,
  fields,
  initialDocumentId,
  auditIntents,
  onAuditIntent,
  onPersistReview,
  onBack,
}: ExtractionReviewProps) {
  const [fieldItems, setFieldItems] = useState(fields);
  const reviewableFields = fieldItems.filter((field) => field.valueOrigin === "extracted");
  const [selectedDocumentId, setSelectedDocumentId] = useState(initialDocumentId);
  const selectedDocumentFields = reviewableFields.filter((field) => field.documentId === selectedDocumentId);
  const firstUnreviewed = selectedDocumentFields.find((field) => field.reviewStatus === "unreviewed");
  const [selectedFieldKey, setSelectedFieldKey] = useState(firstUnreviewed?.fieldKey ?? selectedDocumentFields[0]?.fieldKey);
  const [editingFieldKey, setEditingFieldKey] = useState<string | null>(null);
  const [draftValue, setDraftValue] = useState("");

  useEffect(() => {
    setFieldItems(fields);
  }, [fields]);

  const queue = useMemo(() => {
    return documents
      .map((document) => {
        const docFields = reviewableFields.filter((field) => field.documentId === document.documentId);
        if (docFields.length === 0) return null;
        return {
          documentId: document.documentId,
          filename: document.filename,
          facility: document.facilityName ?? document.facilityState.replaceAll("_", " "),
          period:
            document.periodState === "resolved"
              ? `${document.periodStart} to ${document.periodEnd}`
              : document.periodState.replaceAll("_", " "),
          reviewedCount: docFields.filter((field) => field.reviewStatus !== "unreviewed").length,
          fieldCount: docFields.length,
        };
      })
      .filter((item): item is NonNullable<typeof item> => item !== null);
  }, [documents, reviewableFields]);

  const selectedField =
    selectedDocumentFields.find((field) => field.fieldKey === selectedFieldKey) ??
    selectedDocumentFields[0] ??
    reviewableFields[0];
  const selectedDocument = documents.find((document) => document.documentId === selectedDocumentId) ?? documents[0];
  const selectedFieldIndex = Math.max(
    selectedDocumentFields.findIndex((field) => field.fieldKey === selectedField?.fieldKey),
    0
  );
  const handleFieldKeys = useKeyboardNavigation({
    currentIndex: selectedFieldIndex,
    itemCount: selectedDocumentFields.length,
    onMove: (nextIndex) => {
      const next = selectedDocumentFields[nextIndex];
      if (next) selectField(next.fieldKey);
    },
    onEnter: () => {
      if (selectedField) void acceptValue(selectedField);
    },
    onEscape: () => setEditingFieldKey(null),
  });

  function selectDocument(documentId: string) {
    const docFields = reviewableFields.filter((field) => field.documentId === documentId);
    const first = docFields.find((field) => field.reviewStatus === "unreviewed") ?? docFields[0];
    setSelectedDocumentId(documentId);
    setSelectedFieldKey(first?.fieldKey);
    setEditingFieldKey(null);
  }

  function selectField(fieldKey: string) {
    setSelectedFieldKey(fieldKey);
    setEditingFieldKey(null);
  }

  function advanceFrom(fieldKey: string, updatedFields: ExtractedField[]) {
    const currentIndex = selectedDocumentFields.findIndex((field) => field.fieldKey === fieldKey);
    const next =
      selectedDocumentFields
        .slice(currentIndex + 1)
        .find((field) => updatedFields.find((updated) => updated.fieldKey === field.fieldKey)?.reviewStatus === "unreviewed") ??
      selectedDocumentFields.find((field) => updatedFields.find((updated) => updated.fieldKey === field.fieldKey)?.reviewStatus === "unreviewed");
    if (next) {
      setSelectedFieldKey(next.fieldKey);
    }
  }

  async function acceptValue(field: ExtractedField) {
    const updated = fieldItems.map((candidate) =>
      candidate.fieldKey === field.fieldKey ? { ...candidate, reviewStatus: "accepted" as const } : candidate
    );
    await onPersistReview?.({ field, decision: "accepted" });
    setFieldItems(updated);
    onAuditIntent(
      createAuditIntent({
        action: "accept_value",
        documentId: field.documentId,
        fieldKey: field.fieldKey,
        oldValue: field.value,
        newValue: field.value,
      })
    );
    advanceFrom(field.fieldKey, updated);
  }

  async function saveDraft(field: ExtractedField) {
    if (!draftValue.trim()) return;
    if (field.value === null) {
      const updated = fieldItems.map((candidate) =>
        candidate.fieldKey === field.fieldKey
          ? {
              ...candidate,
              value: draftValue,
              correctedValue: draftValue,
              reviewStatus: "keyed_by_reviewer" as const,
            }
          : candidate
      );
      await onPersistReview?.({ field, decision: "edited", reviewedValue: draftValue, reviewerNote: "Entered by reviewer." });
      setFieldItems(updated);
      onAuditIntent(
        createAuditIntent({
          action: "enter_value",
          documentId: field.documentId,
          fieldKey: field.fieldKey,
          oldValue: null,
          newValue: draftValue,
        })
      );
      setEditingFieldKey(null);
      advanceFrom(field.fieldKey, updated);
      return;
    }

    const updated = fieldItems.map((candidate) =>
      candidate.fieldKey === field.fieldKey
        ? {
            ...candidate,
            correctedValue: draftValue,
            reviewStatus: "corrected" as const,
          }
        : candidate
    );
    await onPersistReview?.({ field, decision: "edited", reviewedValue: draftValue, reviewerNote: "Corrected by reviewer." });
    setFieldItems(updated);
    const intents = createCorrectionAuditIntents(
      {
        documentId: field.documentId,
        fieldKey: field.fieldKey,
        oldValue: field.value,
      },
      draftValue
    );
    intents.forEach(onAuditIntent);
    setEditingFieldKey(null);
    advanceFrom(field.fieldKey, updated);
  }

  return (
    <section className="s1-extraction">
      <aside className="s1-queue">
        <div className="s1-pane-header">
          <button className="s1-linklike" type="button" onClick={onBack}>
            Back to evidence
          </button>
          <h2>Queue</h2>
        </div>
        {queue.map((item) => (
          <button
            className="s1-queue-item"
            type="button"
            key={item.documentId}
            aria-current={item.documentId === selectedDocumentId}
            onClick={() => selectDocument(item.documentId)}
          >
            <strong>{item.filename}</strong>
            <div className="s1-muted">{item.facility}</div>
            <div className="s1-muted">{item.period}</div>
            <div className="s1-mono">
              {item.reviewedCount} of {item.fieldCount} reviewed
            </div>
          </button>
        ))}
      </aside>
      <main className="s1-fields">
        <div className="s1-pane-header">
          <h2>{selectedDocument?.filename}</h2>
        </div>
        {selectedDocumentFields.map((field) => (
          <article
            className="s1-field-row"
            key={field.fieldKey}
            aria-current={selectedField?.fieldKey === field.fieldKey}
            tabIndex={0}
            onClick={() => selectField(field.fieldKey)}
            onKeyDown={handleFieldKeys}
          >
            <div>
              <h3>{field.fieldLabel}</h3>
              <div className="s1-mono s1-muted">{field.fieldKey} · placeholder</div>
              <div className="s1-chip-stack">
                <StateIndicator
                  dimension="field"
                  value={field.fieldState}
                  label={field.fieldState === "populated" ? "populated" : "missing — requestable"}
                />
                {field.valueProperties.map((property) => (
                  <StateIndicator
                    key={property}
                    dimension="valueProperty"
                    value={property}
                    label={valuePropertyLabel(property)}
                  />
                ))}
                <StateIndicator dimension="review" value={field.reviewStatus} label={reviewLabel(field.reviewStatus)} />
              </div>
            </div>
            <div>
              <div>
                <strong>{field.correctedValue ?? field.value ?? EXACT_COPY.valueAbsent}</strong>
                {field.unit ? <span className="s1-muted"> {field.unit}</span> : null}
              </div>
              {field.snippet ? <div className="s1-snippet">{field.snippet}</div> : <div className="s1-muted">No snippet</div>}
              {editingFieldKey === field.fieldKey ? (
                <div className="s1-actions">
                  <input
                    className="s1-inline-input"
                    value={draftValue}
                    onChange={(event) => setDraftValue(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Escape") setEditingFieldKey(null);
                    }}
                  />
                  <button className="s1-button" type="button" onClick={() => void saveDraft(field)}>
                    Save
                  </button>
                  <button className="s1-button" type="button" onClick={() => setEditingFieldKey(null)}>
                    Cancel
                  </button>
                </div>
              ) : null}
            </div>
            <div className="s1-actions">
              {field.value !== null ? (
                <>
                  <button className="s1-button" type="button" onClick={() => void acceptValue(field)}>
                    Accept
                  </button>
                  <button
                    className="s1-button"
                    type="button"
                    onClick={() => {
                      setEditingFieldKey(field.fieldKey);
                      setDraftValue(field.correctedValue ?? field.value ?? "");
                    }}
                  >
                    Correct
                  </button>
                </>
              ) : (
                <button
                  className="s1-button"
                  type="button"
                  onClick={() => {
                    setEditingFieldKey(field.fieldKey);
                    setDraftValue("");
                  }}
                >
                  Enter value
                </button>
              )}
            </div>
          </article>
        ))}
      </main>
      <SourcePane document={selectedDocument} field={selectedField} auditIntents={auditIntents} />
    </section>
  );
}

function SourcePane({
  document,
  field,
  auditIntents,
}: {
  document?: EvidenceItem;
  field?: ExtractedField;
  auditIntents: AuditIntent[];
}) {
  const fieldIntents = auditIntents.filter((intent) => intent.fieldKey && intent.fieldKey === field?.fieldKey);
  return (
    <aside className="s1-source">
      <div className="s1-pane-header">
        <h2>Source</h2>
        <div className="s1-muted">{document?.filename}</div>
      </div>
      <div className="s1-source-body">
        {field?.location ? (
          <p>
            {field.location.kind === "page"
              ? `Page ${field.location.page}`
              : `${field.location.sheet} ${field.location.range}`}
          </p>
        ) : (
          <StateIndicator dimension="check" value="not_applicable" label={EXACT_COPY.sourceLocationMissing} />
        )}
        <h3>Snippet context</h3>
        <div className="s1-source-context">
          {field?.snippetContext ?? "No snippet context"}
        </div>
        <p>
          <button
            className="s1-button"
            type="button"
            onClick={() => {
              if (document?.downloadUrl) window.open(document.downloadUrl, "_blank", "noopener,noreferrer");
            }}
            disabled={!document?.downloadUrl}
          >
            Download original
          </button>
        </p>
      </div>
      {fieldIntents.length > 0 ? (
        <div className="s1-source-body">
          <h3>Field history</h3>
          {fieldIntents.map((intent, index) => (
            <div className="s1-mono" key={`${intent.action}-${index}`}>
              {intent.action}
            </div>
          ))}
        </div>
      ) : null}
    </aside>
  );
}

function reviewLabel(status: ExtractedField["reviewStatus"]) {
  const labels = {
    unreviewed: "unreviewed",
    accepted: "accepted",
    corrected: "corrected",
    keyed_by_reviewer: "human-keyed",
  };
  return labels[status];
}

function valuePropertyLabel(property: ExtractedField["valueProperties"][number]) {
  const labels = {
    estimated_read: "estimated meter read",
    unit_missing: "unit missing",
    unit_ambiguous: "unit ambiguous",
    format_mismatch: "value outside expected format",
  };
  return labels[property];
}
