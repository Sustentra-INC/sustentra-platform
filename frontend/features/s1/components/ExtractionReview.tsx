"use client";

import { useEffect, useMemo, useState, type KeyboardEvent } from "react";

import { EXACT_COPY } from "../constants/copy";
import { inlineDocumentUrl } from "../adapters/evidenceAdapter";
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
  showSessionAuditIntents?: boolean;
  onBack: () => void;
}

export function ExtractionReview({
  documents,
  fields,
  initialDocumentId,
  auditIntents,
  onAuditIntent,
  onPersistReview,
  showSessionAuditIntents = true,
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

  useEffect(() => {
    const docFields = fieldItems.filter(
      (field) => field.valueOrigin === "extracted" && field.documentId === selectedDocumentId
    );
    const first = docFields.find((field) => field.reviewStatus === "unreviewed") ?? docFields[0];
    setSelectedFieldKey(first?.fieldKey);
  }, [fieldItems, selectedDocumentId]);

  const queue = useMemo(() => {
    return documents
      .map((document) => {
        const docFields = reviewableFields.filter((field) => field.documentId === document.documentId);
        if (docFields.length === 0 && document.documentId !== selectedDocumentId) return null;
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
  }, [documents, reviewableFields, selectedDocumentId]);

  const selectedField =
    selectedDocumentFields.find((field) => field.fieldKey === selectedFieldKey) ??
    selectedDocumentFields[0] ??
    reviewableFields[0];
  const selectedDocument = documents.find((document) => document.documentId === selectedDocumentId) ?? documents[0];
  const selectedDocumentHasNoFields = selectedDocumentFields.length === 0;
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
      <main className="s1-document-viewer">
        <div className="s1-pane-header">
          <h2>{selectedDocument?.filename}</h2>
          {selectedField?.location ? (
            <div className="s1-muted">
              {selectedField.location.kind === "page"
                ? `Selected field source: page ${selectedField.location.page}`
                : `Selected field source: ${selectedField.location.sheet} ${selectedField.location.range}`}
            </div>
          ) : (
            <div className="s1-muted">{EXACT_COPY.sourceLocationMissing}</div>
          )}
        </div>
        {selectedDocumentHasNoFields ? (
          <NoFieldsExtracted document={selectedDocument} />
        ) : null}
        <DocumentPreview document={selectedDocument} field={selectedField} />
      </main>
      <CorrectionRail
        document={selectedDocument}
        fields={selectedDocumentFields}
        selectedField={selectedField}
        editingFieldKey={editingFieldKey}
        draftValue={draftValue}
        onDraftValue={setDraftValue}
        onSelectField={selectField}
        onFieldKeys={handleFieldKeys}
        onAcceptValue={acceptValue}
        onSaveDraft={saveDraft}
        onEditField={(field) => {
          setEditingFieldKey(field.fieldKey);
          setDraftValue(field.correctedValue ?? field.value ?? "");
        }}
        onCancelEdit={() => setEditingFieldKey(null)}
        auditIntents={showSessionAuditIntents ? auditIntents : []}
      />
    </section>
  );
}

function NoFieldsExtracted({ document }: { document?: EvidenceItem }) {
  return (
    <section className="s1-panel">
      <h3>No extracted fields</h3>
      <p>
        {document?.haltReason ??
          "No reviewable extracted fields are available for this document yet."}
      </p>
      <p className="s1-muted">
        The original document remains available. Processing can be retried from the Evidence Workspace.
      </p>
    </section>
  );
}

function DocumentPreview({ document, field }: { document?: EvidenceItem; field?: ExtractedField }) {
  if (!document?.downloadUrl) {
    return (
      <section className="s1-document-empty">
        <h3>Original document unavailable</h3>
        <p>The uploaded file is not available from storage.</p>
      </section>
    );
  }

  if (document.format === "csv") {
    return <CsvDocumentPreview document={document} />;
  }

  if (document.format === "pdf" || document.format === "image" || document.format === "other") {
    const pageSuffix =
      document.format === "pdf" && field?.location?.kind === "page"
        ? `#page=${field.location.page}`
        : "";
    const previewUrl = `${inlineDocumentUrl(document.documentId)}${pageSuffix}`;
    return (
      <iframe
        className="s1-document-frame"
        title={`Original document: ${document.filename}`}
        src={previewUrl}
      />
    );
  }

  return (
    <section className="s1-document-empty">
      <h3>Original workbook</h3>
      <p>Preview is not available for this workbook format in the browser.</p>
      <button
        className="s1-button"
        type="button"
        onClick={() => window.open(document.downloadUrl, "_blank", "noopener,noreferrer")}
      >
        Download original
      </button>
    </section>
  );
}

function CsvDocumentPreview({ document }: { document: EvidenceItem }) {
  const [state, setState] = useState<{
    status: "loading" | "ready" | "failed";
    text: string;
    error: string | null;
  }>({ status: "loading", text: "", error: null });

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: "loading", text: "", error: null });
    fetch(inlineDocumentUrl(document.documentId), {
      cache: "no-store",
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) throw new Error(`Preview request failed: ${response.status}`);
        return response.text();
      })
      .then((text) => setState({ status: "ready", text, error: null }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setState({
          status: "failed",
          text: "",
          error: error instanceof Error ? error.message : "CSV preview could not be loaded.",
        });
      });
    return () => controller.abort();
  }, [document.documentId]);

  if (state.status === "loading") {
    return (
      <section className="s1-document-empty">
        <h3>Loading original file</h3>
      </section>
    );
  }

  if (state.status === "failed") {
    return (
      <section className="s1-document-empty">
        <h3>CSV preview unavailable</h3>
        <p>{state.error}</p>
        <button
          className="s1-button"
          type="button"
          onClick={() => window.open(document.downloadUrl, "_blank", "noopener,noreferrer")}
        >
          Download original
        </button>
      </section>
    );
  }

  const rows = parseCsvPreview(state.text);
  const [header, ...body] = rows;
  return (
    <section className="s1-csv-preview" aria-label={`Original CSV: ${document.filename}`}>
      {header ? (
        <table className="s1-csv-table">
          <thead>
            <tr>
              {header.map((cell, index) => (
                <th key={`${cell}-${index}`}>{cell}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {body.map((row, rowIndex) => (
              <tr key={`row-${rowIndex}`}>
                {header.map((_, cellIndex) => (
                  <td key={`cell-${rowIndex}-${cellIndex}`}>{row[cellIndex] ?? ""}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <pre className="s1-csv-raw">{state.text}</pre>
      )}
    </section>
  );
}

function parseCsvPreview(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let inQuotes = false;

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    const next = text[index + 1];
    if (char === "\"" && inQuotes && next === "\"") {
      cell += "\"";
      index += 1;
      continue;
    }
    if (char === "\"") {
      inQuotes = !inQuotes;
      continue;
    }
    if (char === "," && !inQuotes) {
      row.push(cell);
      cell = "";
      continue;
    }
    if ((char === "\n" || char === "\r") && !inQuotes) {
      if (char === "\r" && next === "\n") index += 1;
      row.push(cell);
      if (row.some((value) => value.trim())) rows.push(row.map((value) => value.trim()));
      row = [];
      cell = "";
      continue;
    }
    cell += char;
  }

  row.push(cell);
  if (row.some((value) => value.trim())) rows.push(row.map((value) => value.trim()));
  return rows.slice(0, 200);
}

function CorrectionRail({
  document,
  fields,
  selectedField,
  editingFieldKey,
  draftValue,
  onDraftValue,
  onSelectField,
  onFieldKeys,
  onAcceptValue,
  onSaveDraft,
  onEditField,
  onCancelEdit,
  auditIntents,
}: {
  document?: EvidenceItem;
  fields: ExtractedField[];
  selectedField?: ExtractedField;
  editingFieldKey: string | null;
  draftValue: string;
  onDraftValue: (value: string) => void;
  onSelectField: (fieldKey: string) => void;
  onFieldKeys: (event: KeyboardEvent) => void;
  onAcceptValue: (field: ExtractedField) => Promise<void>;
  onSaveDraft: (field: ExtractedField) => Promise<void>;
  onEditField: (field: ExtractedField) => void;
  onCancelEdit: () => void;
  auditIntents: AuditIntent[];
}) {
  const fieldIntents = auditIntents.filter((intent) => intent.fieldKey && intent.fieldKey === selectedField?.fieldKey);
  return (
    <aside className="s1-correction-rail">
      <div className="s1-pane-header">
        <h2>Fields</h2>
        <div className="s1-muted">{document?.filename}</div>
      </div>
      {fields.map((field) => (
        <article
          className="s1-field-row"
          key={field.fieldKey}
          aria-current={selectedField?.fieldKey === field.fieldKey}
          tabIndex={0}
          onClick={() => onSelectField(field.fieldKey)}
          onKeyDown={onFieldKeys}
        >
          <h3>{field.fieldLabel}</h3>
          <div className="s1-mono s1-muted">{field.fieldKey}</div>
          <div className="s1-chip-stack">
            <StateIndicator
              dimension="field"
              value={field.fieldState}
              label={field.fieldState === "populated" ? "populated" : "missing — requestable"}
            />
            {field.valueProperties.map((property) => (
              <StateIndicator key={property} dimension="valueProperty" value={property} label={valuePropertyLabel(property)} />
            ))}
            <StateIndicator dimension="review" value={field.reviewStatus} label={reviewLabel(field.reviewStatus)} />
          </div>
          <div className="s1-field-value">
            <strong>{field.correctedValue ?? field.value ?? EXACT_COPY.valueAbsent}</strong>
            {field.unit ? <span className="s1-muted"> {field.unit}</span> : null}
          </div>
          {field.location ? (
            <div className="s1-muted">
              {field.location.kind === "page"
                ? `Page ${field.location.page}`
                : `${field.location.sheet} ${field.location.range}`}
            </div>
          ) : (
            <StateIndicator dimension="check" value="not_applicable" label={EXACT_COPY.sourceLocationMissing} />
          )}
          {field.snippet ? <div className="s1-snippet">{field.snippet}</div> : <div className="s1-muted">No snippet</div>}
          {editingFieldKey === field.fieldKey ? (
            <div className="s1-actions">
              <input
                className="s1-inline-input"
                value={draftValue}
                onChange={(event) => onDraftValue(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Escape") onCancelEdit();
                }}
              />
              <button className="s1-button" type="button" onClick={() => void onSaveDraft(field)}>
                Save
              </button>
              <button className="s1-button" type="button" onClick={onCancelEdit}>
                Cancel
              </button>
            </div>
          ) : null}
          <div className="s1-actions">
            {field.value !== null ? (
              <>
                <button className="s1-button" type="button" onClick={() => void onAcceptValue(field)}>
                  Accept
                </button>
                <button className="s1-button" type="button" onClick={() => onEditField(field)}>
                  Correct
                </button>
              </>
            ) : (
              <button className="s1-button" type="button" onClick={() => onEditField(field)}>
                Enter value
              </button>
            )}
          </div>
        </article>
      ))}
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
