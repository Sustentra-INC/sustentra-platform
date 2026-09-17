"use client";

import { useEffect, useState } from "react";

import {
  listWorkspaceEvidence,
  processDocument,
  submitFieldReview,
  uploadDocument,
  userFacingApiError,
} from "../api/s1Backend";
import { ExtractionReview } from "../components/ExtractionReview";
import { EvidenceWorkspace } from "../components/EvidenceWorkspace";
import { S1Chrome } from "../components/S1Chrome";
import { StateIndicator } from "../components/StateIndicator";
import { EXACT_COPY } from "../constants/copy";
import { engagementConfig } from "../fixtures/engagementConfig";
import { manufacturerEvidence } from "../fixtures/evidence/manufacturerEvidence";
import { seedAsks } from "../fixtures/requests/seedAsks";
import { extractedFields } from "../fixtures/extraction/fields";
import { useRequestsStore } from "../requests/requestsStore";
import type { ContainerState, EvidenceItem, ExtractedField, StateDimension } from "../types";
import type { SessionAuditEntry } from "../utils/auditIntent";

type ActiveView =
  | { name: "evidence" }
  | { name: "extraction"; documentId: string; mode?: "snippet" | "manual" }
  | { name: "glossary"; previous: Exclude<ActiveView, { name: "glossary" }> };

export function S1WorkpaperApp() {
  const dataMode = process.env.NEXT_PUBLIC_S1_DATA_MODE === "fixture" ? "fixture" : "backend";
  const [activeView, setActiveView] = useState<ActiveView>({ name: "evidence" });
  const [auditIntents, setAuditIntents] = useState<SessionAuditEntry[]>([]);
  const [demoState, setDemoState] = useState<ContainerState>(dataMode === "backend" ? "loading" : "populated");
  const [evidenceItems, setEvidenceItems] = useState<EvidenceItem[]>(
    dataMode === "backend" ? [] : manufacturerEvidence
  );
  const [fieldItems, setFieldItems] = useState<ExtractedField[]>(extractedFields);
  const [isUploading, setIsUploading] = useState(false);
  const [processingDocumentIds, setProcessingDocumentIds] = useState<string[]>([]);
  const [backendError, setBackendError] = useState<string | null>(null);
  const requests = useRequestsStore(dataMode === "backend" ? [] : seedAsks);

  useEffect(() => {
    if (dataMode !== "backend") return;
    void refreshBackendWorkspace();
  }, [dataMode]);

  async function refreshBackendWorkspace(nextContainerState?: ContainerState) {
    setBackendError(null);
    try {
      const workspace = await listWorkspaceEvidence(engagementConfig.engagementId);
      setEvidenceItems(workspace.evidence);
      setFieldItems(workspace.fields);
      setDemoState(nextContainerState ?? (workspace.evidence.length === 0 ? "empty_nothing_yet" : "populated"));
    } catch (error) {
      setBackendError(error instanceof Error ? error.message : "Could not reach the backend API.");
      setDemoState("error_degraded");
    }
  }

  function addAuditIntent(intent: SessionAuditEntry) {
    setAuditIntents((current) => [...current, intent]);
  }

  function openExtraction(documentId: string) {
    setActiveView({ name: "extraction", documentId, mode: "snippet" });
  }

  async function handleUploadFiles(files: FileList) {
    if (dataMode !== "backend") return;
    setIsUploading(true);
    setBackendError(null);
    const failures: string[] = [];
    for (const file of Array.from(files)) {
      try {
        const document = await uploadDocument(engagementConfig.engagementId, file);
        setEvidenceItems((current) => [
          {
            documentId: document.document_id,
            filename: document.file_name,
            downloadUrl: undefined,
            format: file.name.toLowerCase().endsWith(".pdf") ? "pdf" : "other",
            uploadedBy: { id: document.uploaded_by, name: document.uploaded_by, actorType: "preparer" },
            uploadedAt: document.uploaded_at,
            evidenceClass: "main",
            disposition: "active",
            processingState: "not_ingested",
            haltReason: null,
            detectedType: null,
            typeReviewBand: null,
            typeReviewReason: null,
            facilityState: "unresolved",
            facilityId: null,
            facilityName: null,
            facilityCount: null,
            periodState: "unresolved",
            periodStart: null,
            periodEnd: null,
            fieldsExpected: 0,
            fieldsExpectedDisplay: null,
            fieldsExtracted: 0,
            documentProperties: [],
            relationships: [],
            reviewArea: null,
            note: null,
          },
          ...current.filter((item) => item.documentId !== document.document_id),
        ]);
        setDemoState("populated");
        setProcessingDocumentIds((current) => [...current, document.document_id]);
        await processDocument(document.document_id);
        setProcessingDocumentIds((current) => current.filter((id) => id !== document.document_id));
      } catch (error) {
        failures.push(`${file.name}: ${userFacingApiError(error)}`);
      }
    }
    await refreshBackendWorkspace("populated");
    if (failures.length > 0) {
      setBackendError(`Some files were not uploaded. ${failures.join(" ")}`);
    }
    setIsUploading(false);
  }

  async function handleProcessDocument(documentId: string) {
    if (dataMode !== "backend") return;
    setBackendError(null);
    setProcessingDocumentIds((current) => [...new Set([...current, documentId])]);
    try {
      await processDocument(documentId);
      await refreshBackendWorkspace("populated");
    } catch (error) {
      setBackendError(userFacingApiError(error));
      await refreshBackendWorkspace();
    } finally {
      setProcessingDocumentIds((current) => current.filter((id) => id !== documentId));
    }
  }

  return (
    <main className="s1-app">
      <S1Chrome
        engagement={engagementConfig}
        currentTab={activeView.name === "evidence" || activeView.name === "glossary" ? "evidence" : "extraction"}
        onOpenGlossary={() =>
          setActiveView((current) =>
            current.name === "glossary" ? current : { name: "glossary", previous: current }
          )
        }
      >
        {activeView.name === "evidence" ? (
          <EvidenceWorkspace
            engagement={engagementConfig}
            evidence={evidenceItems}
            asks={requests.asks}
            onSaveAsk={requests.saveAsk}
            onResolveAsk={requests.resolveAsk}
            auditIntents={auditIntents}
            onAuditIntent={addAuditIntent}
            demoState={demoState}
            onOpenExtraction={openExtraction}
            onUploadFiles={handleUploadFiles}
            isUploading={isUploading}
            backendError={backendError}
            writesEnabled={dataMode !== "backend"}
          />
        ) : activeView.name === "extraction" ? (
          <ExtractionReview
            documents={evidenceItems}
            fields={fieldItems}
            initialDocumentId={activeView.documentId}
            mode={activeView.mode ?? "snippet"}
            auditIntents={auditIntents}
            onAuditIntent={addAuditIntent}
            onPersistReview={dataMode === "backend" ? submitFieldReview : undefined}
            showSessionAuditIntents={dataMode !== "backend"}
            onBack={() => setActiveView({ name: "evidence" })}
          />
        ) : (
          <GlossaryPage onBack={() => setActiveView(activeView.previous)} />
        )}
      </S1Chrome>
    </main>
  );
}

function GlossaryPage({ onBack }: { onBack: () => void }) {
  return (
    <section className="s1-content s1-glossary-page">
      <button className="s1-linklike" type="button" onClick={onBack}>
        Back
      </button>
      <div className="s1-glossary">
        <h2>Glossary</h2>
        <p>{EXACT_COPY.glossaryIntro}</p>
        <section>
          <h3>Vocabulary</h3>
          <table className="s1-printable-table s1-glossary-table">
            <thead>
              <tr>
                <th>Term</th>
                <th>Means</th>
              </tr>
            </thead>
            <tbody>
              {VOCABULARY_ROWS.map((row) => (
                <tr key={row.term}>
                  <th>{row.term}</th>
                  <td>{row.means}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
        <section>
          <h3>State enumerations</h3>
          <table className="s1-printable-table s1-glossary-table">
            <thead>
              <tr>
                <th>Enumeration</th>
                <th>Attaches to</th>
                <th>Values</th>
              </tr>
            </thead>
            <tbody>
              {STATE_ENUMERATION_ROWS.map((row) => (
                <tr key={row.dimension}>
                  <th>{row.enumeration}</th>
                  <td>{row.attachesTo}</td>
                  <td>
                    <div className="s1-chip-stack">
                      {row.values.map((value) => (
                        <StateIndicator
                          key={`${row.dimension}-${value.value}`}
                          dimension={row.dimension}
                          value={value.value}
                          label={value.label}
                        />
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>
    </section>
  );
}

const VOCABULARY_ROWS = [
  {
    term: "Document typing",
    means: "Detecting what a file is — utility bill, contractual instrument, workbook",
  },
  {
    term: "Classification",
    means: "Reserved for scope classification: Scope 1/2/3, and within Scope 2, location- vs market-based",
  },
  { term: "Gap", means: "User-facing label for an open finding. Not a separate object" },
  { term: "Finding", means: "The object carrying review state, failure cause, impact, disposition" },
  {
    term: "Request",
    means: "Engagement-level client ask. Many-to-many with findings — one request bundles gaps across several review items",
  },
  { term: "Main evidence", means: "Extractable, system-verifiable, links to specific Field_IDs" },
  {
    term: "Supportive evidence",
    means: "Enters the workpaper, no extraction expected, links to a coarse review area",
  },
  { term: "Type review", means: "The classifier's confidence against the vocabulary threshold" },
  { term: "Fields extracted", means: "How many required fields were found inside a typed document" },
] as const;

const STATE_ENUMERATION_ROWS: Array<{
  dimension: StateDimension;
  enumeration: string;
  attachesTo: string;
  values: Array<{ value: string; label: string }>;
}> = [
  {
    dimension: "processing",
    enumeration: "processing",
    attachesTo: "Evidence item / extraction",
    values: [
      { value: "not_ingested", label: "Not ingested" },
      { value: "ingested", label: "Ingested" },
      { value: "typed", label: "Typed" },
      { value: "extracted", label: "Extracted" },
      { value: "blocked", label: "Blocked" },
    ],
  },
  {
    dimension: "review",
    enumeration: "review",
    attachesTo: "Field / finding",
    values: [
      { value: "unreviewed", label: "Unreviewed" },
      { value: "accepted", label: "Accepted" },
      { value: "corrected", label: "Corrected" },
      { value: "keyed_by_reviewer", label: "human-keyed" },
    ],
  },
  {
    dimension: "check",
    enumeration: "check",
    attachesTo: "Verification check",
    values: [
      { value: "not_system_verified", label: "Not system-verified" },
      { value: "not_applicable", label: "Not applicable" },
      { value: "passed", label: "Passed" },
      { value: "failed", label: "Failed" },
      { value: "not_evaluable", label: "Not evaluable" },
    ],
  },
  {
    dimension: "field",
    enumeration: "field",
    attachesTo: "Schema field",
    values: [
      { value: "populated", label: "Populated" },
      { value: "missing_requestable", label: "Missing — requestable" },
      { value: "missing_not_requestable", label: "Missing — not requestable" },
      { value: "system_key", label: "System key" },
      { value: "not_applicable", label: "Not applicable" },
    ],
  },
  {
    dimension: "facilityResolution",
    enumeration: "facilityResolution",
    attachesTo: "Evidence item",
    values: [
      { value: "resolved", label: "Resolved" },
      { value: "unresolved", label: "Unresolved" },
      { value: "multiple", label: "Multiple" },
      { value: "not_facility_scoped", label: "Not facility-scoped" },
    ],
  },
  {
    dimension: "periodResolution",
    enumeration: "periodResolution",
    attachesTo: "Evidence item",
    values: [
      { value: "resolved", label: "Resolved" },
      { value: "unresolved", label: "Unresolved" },
      { value: "spans_multiple", label: "Spans multiple" },
    ],
  },
  {
    dimension: "valueProperty",
    enumeration: "valueProperty",
    attachesTo: "Extracted value",
    values: [
      { value: "estimated_read", label: "Estimated read" },
      { value: "unit_missing", label: "Unit missing" },
      { value: "unit_ambiguous", label: "Unit ambiguous" },
      { value: "format_mismatch", label: "Format mismatch" },
    ],
  },
  {
    dimension: "readiness",
    enumeration: "readiness",
    attachesTo: "Finding / conclusion readiness",
    values: [
      { value: "non-blocking", label: "Non-blocking" },
      { value: "blocking", label: "Blocking" },
    ],
  },
  {
    dimension: "disposition",
    enumeration: "disposition",
    attachesTo: "Evidence item / finding",
    values: [
      { value: "active", label: "Active" },
      { value: "withdrawn", label: "Withdrawn" },
    ],
  },
  {
    dimension: "request",
    enumeration: "request",
    attachesTo: "Client request",
    values: [
      { value: "requested", label: "Requested" },
      { value: "fulfilled", label: "Fulfilled" },
      { value: "cancelled", label: "Cancelled" },
      { value: "waived_below_threshold", label: "Waived below threshold" },
    ],
  },
];
