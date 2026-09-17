"use client";

import { useEffect, useState } from "react";

import {
  listWorkspaceEvidence,
  processDocument,
  uploadDocument,
  userFacingApiError,
} from "../api/s1Backend";
import { ExtractionReview } from "../components/ExtractionReview";
import { EvidenceWorkspace } from "../components/EvidenceWorkspace";
import { S1Chrome, type NavKey } from "../components/S1Chrome";
import { UploadScreen } from "../components/UploadScreen";
import { SetupScreen } from "../components/SetupScreen";
import { EvidenceRequests } from "../components/EvidenceRequests";
import { CheckCoverage } from "../components/CheckCoverage";
import { VerificationResults } from "../components/VerificationResults";
import { OutputScreen } from "../components/OutputScreen";
import { coverageRules } from "../fixtures/verification/coverageRules";
import { verificationRows } from "../fixtures/verification/verificationResults";
import { useVerificationStore } from "../verification/verificationStore";
import { StateIndicator } from "../components/StateIndicator";
import { EXACT_COPY } from "../constants/copy";
import { engagementConfig } from "../fixtures/engagementConfig";
import { inScopeFieldPlaceholders } from "../fixtures/scope/inScopeFields";
import type { EngagementConfig, InScopeField } from "../types";
import { manufacturerEvidence } from "../fixtures/evidence/manufacturerEvidence";
import { manufacturerValues } from "../fixtures/extraction/manufacturerValues";
import { seedAsks } from "../fixtures/requests/seedAsks";
import { makeUploadItem, classifyGuess } from "../fixtures/upload/simulateUpload";
import { useRequestsStore } from "../requests/requestsStore";
import type { ContainerState, EvidenceItem, ReviewValue, StateDimension } from "../types";
import type { SessionAuditEntry } from "../utils/auditIntent";

type ActiveView =
  | { name: "evidence" }
  | { name: "setup" }
  | { name: "upload" }
  | { name: "requests" }
  | { name: "coverage" }
  | { name: "results" }
  | { name: "output" }
  | { name: "extraction"; documentId: string; mode?: "snippet" | "manual"; nodeKey?: string }
  | { name: "glossary"; previous: Exclude<ActiveView, { name: "glossary" }> };

/** Facility->type (or entity/not-yet-known) node a Workspace row maps into. */
function nodeKeyForEvidence(item: EvidenceItem): string {
  const type = item.detectedType ?? "Type unresolved";
  if (item.facilityState === "resolved" && item.facilityId) return `F:${item.facilityId}|T:${type}`;
  if (item.facilityState === "unresolved") return "N";
  return "E"; // multiple / not_facility_scoped -> entity-level
}

export function S1WorkpaperApp() {
  const dataMode = process.env.NEXT_PUBLIC_S1_DATA_MODE === "fixture" ? "fixture" : "backend";
  const [activeView, setActiveView] = useState<ActiveView>({ name: "evidence" });
  const [auditIntents, setAuditIntents] = useState<SessionAuditEntry[]>([]);
  const [demoState, setDemoState] = useState<ContainerState>(dataMode === "backend" ? "loading" : "populated");
  const [evidenceItems, setEvidenceItems] = useState<EvidenceItem[]>(
    dataMode === "backend" ? [] : manufacturerEvidence
  );
  // Extraction review data lifted to app state so accepts/corrections survive
  // navigation (fixture mode; backend mode fetches its own).
  const [reviewValues, setReviewValues] = useState<ReviewValue[]>(dataMode === "backend" ? [] : manufacturerValues);
  const [isUploading, setIsUploading] = useState(false);
  const [processingDocumentIds, setProcessingDocumentIds] = useState<string[]>([]);
  const [backendError, setBackendError] = useState<string | null>(null);
  const requests = useRequestsStore(dataMode === "backend" ? [] : seedAsks);
  const verification = useVerificationStore();
  const [sessionUploads, setSessionUploads] = useState<string[]>([]);
  // Engagement config is editable on Setup; facilities here feed the Workspace.
  const [engagement, setEngagement] = useState<EngagementConfig>(engagementConfig);
  const [inScopeFields, setInScopeFields] = useState<InScopeField[]>(inScopeFieldPlaceholders);

  useEffect(() => {
    if (dataMode !== "backend") return;
    void refreshBackendWorkspace();
  }, [dataMode]);

  async function refreshBackendWorkspace(nextContainerState?: ContainerState) {
    setBackendError(null);
    try {
      const workspace = await listWorkspaceEvidence(engagement.engagementId);
      setEvidenceItems(workspace.evidence);
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
    const item = evidenceItems.find((i) => i.documentId === documentId);
    setActiveView({
      name: "extraction",
      documentId,
      mode: "snippet",
      nodeKey: item ? nodeKeyForEvidence(item) : undefined,
    });
  }

  function uploadFiles(files: FileList) {
    if (dataMode === "backend") {
      void handleUploadFiles(files);
      return;
    }
    handleFixtureUpload(files);
  }

  // Fixture-mode upload: rows appear immediately, then progress as they process.
  function handleFixtureUpload(files: FileList) {
    const created = Array.from(files).map((file) => makeUploadItem(file));
    if (created.length === 0) return;
    setEvidenceItems((cur) => [...created, ...cur]);
    setSessionUploads((cur) => [...created.map((c) => c.documentId), ...cur]);
    const patch = (id: string, next: Partial<EvidenceItem>) =>
      setEvidenceItems((cur) => cur.map((x) => (x.documentId === id ? { ...x, ...next } : x)));
    created.forEach((item, i) => {
      window.setTimeout(() => patch(item.documentId, { processingState: "ingested" }), 700 + i * 140);
      window.setTimeout(() => patch(item.documentId, classifyGuess(item.filename, engagement)), 1600 + i * 180);
    });
  }

  const NAV_FOR_VIEW: Partial<Record<ActiveView["name"], NavKey>> = {
    setup: "setup",
    upload: "upload",
    requests: "requests",
    coverage: "coverage",
    results: "results",
    output: "output",
  };
  const navCurrent: NavKey = NAV_FOR_VIEW[activeView.name] ?? "evidence";
  function onNavigate(key: NavKey) {
    if (key === "setup") setActiveView({ name: "setup" });
    else if (key === "upload") setActiveView({ name: "upload" });
    else if (key === "requests") setActiveView({ name: "requests" });
    else if (key === "coverage") setActiveView({ name: "coverage" });
    else if (key === "results") setActiveView({ name: "results" });
    else if (key === "output") setActiveView({ name: "output" });
    else if (key === "evidence") setActiveView({ name: "evidence" });
  }

  // Follow-up: a problem that came back becomes a new ask linked to the old one.
  function raiseFollowUp(fromAsk: (typeof requests.asks)[number]) {
    requests.saveAsk({
      origin: fromAsk.source.origin,
      documentId: fromAsk.source.documentId ?? null,
      fieldKey: fromAsk.source.fieldKey ?? null,
      itemLabel: fromAsk.source.itemLabel,
      facilityName: fromAsk.source.facilityName,
      period: fromAsk.source.period,
      arrival: fromAsk.source.arrival ?? null,
      sourcePage: fromAsk.source.sourcePage ?? null,
      type: fromAsk.type,
      whatIsNeeded: fromAsk.whatIsNeeded,
      raisedByName: fromAsk.raisedByName,
      raisedByLogin: fromAsk.raisedByLogin,
      linkedFromAskId: fromAsk.id,
    });
  }
  const sessionUploadItems = sessionUploads
    .map((id) => evidenceItems.find((i) => i.documentId === id))
    .filter((i): i is EvidenceItem => Boolean(i));

  async function handleUploadFiles(files: FileList) {
    if (dataMode !== "backend") return;
    setIsUploading(true);
    setBackendError(null);
    const failures: string[] = [];
    for (const file of Array.from(files)) {
      try {
        const document = await uploadDocument(engagement.engagementId, file);
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
        engagement={engagement}
        current={navCurrent}
        onNavigate={onNavigate}
        onOpenGlossary={() =>
          setActiveView((current) =>
            current.name === "glossary" ? current : { name: "glossary", previous: current }
          )
        }
      >
        {activeView.name === "setup" ? (
          <SetupScreen
            engagement={engagement}
            onChange={setEngagement}
            inScopeFields={inScopeFields}
            onInScopeChange={setInScopeFields}
          />
        ) : activeView.name === "upload" ? (
          <UploadScreen
            onUploadFiles={uploadFiles}
            batch={sessionUploadItems}
            onOpenWorkspace={() => setActiveView({ name: "evidence" })}
          />
        ) : activeView.name === "requests" ? (
          <EvidenceRequests
            engagement={engagement}
            asks={requests.asks}
            onSend={(ids, lineNumbers) => requests.sendAsks(ids, lineNumbers).requestNumber}
            onResolve={requests.resolveAsk}
            onWithdraw={requests.withdrawAsk}
            onEdit={requests.editAsk}
            onRaiseFollowUp={raiseFollowUp}
            onOpenSource={(ask) => ask.source.documentId && openExtraction(ask.source.documentId)}
            onOpenSetup={() => setActiveView({ name: "setup" })}
          />
        ) : activeView.name === "coverage" ? (
          <CheckCoverage rules={coverageRules} />
        ) : activeView.name === "results" ? (
          <VerificationResults rows={verificationRows} store={verification} />
        ) : activeView.name === "output" ? (
          <OutputScreen />
        ) : activeView.name === "evidence" ? (
          <EvidenceWorkspace
            engagement={engagement}
            evidence={evidenceItems}
            asks={requests.asks}
            onSaveAsk={requests.saveAsk}
            onResolveAsk={requests.resolveAsk}
            onEvidenceChange={setEvidenceItems}
            onOpenRequests={() => setActiveView({ name: "requests" })}
            auditIntents={auditIntents}
            onAuditIntent={addAuditIntent}
            demoState={demoState}
            onOpenExtraction={openExtraction}
            onUploadFiles={uploadFiles}
            isUploading={isUploading}
            backendError={backendError}
            writesEnabled={dataMode !== "backend"}
          />
        ) : activeView.name === "extraction" ? (
          <ExtractionReview
            engagement={engagement}
            values={reviewValues}
            onValuesChange={setReviewValues}
            initialDocumentId={activeView.documentId}
            initialNodeKey={activeView.nodeKey}
            onSaveAsk={requests.saveAsk}
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
