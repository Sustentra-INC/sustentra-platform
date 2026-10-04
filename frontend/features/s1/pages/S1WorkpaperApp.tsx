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
import { DashboardScreen } from "../components/DashboardScreen";
import { UploadScreen, type SampleScript } from "../components/UploadScreen";
import { SetupScreen } from "../components/SetupScreen";
import { InvoicePage } from "../components/demo/InvoicePage";
import {
  preparedInvoiceEvidence,
  preparedInvoiceValues,
  preparedInvoiceClassified,
  preparedInvoiceFoundOrder,
  DEMO_INVOICE_ID,
  DEMO_INVOICE_FILENAME,
} from "../fixtures/demo/preparedInvoice";
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
import { loadDemoState, saveDemoState, clearDemoState, loadSignedIn, saveSignedIn, type DemoSnapshot } from "../utils/demoPersistence";
import { DemoSignIn } from "../components/DemoSignIn";
import { useRequestsStore } from "../requests/requestsStore";
import type { ContainerState, EvidenceItem, ReviewValue, StateDimension } from "../types";
import type { SessionAuditEntry } from "../utils/auditIntent";

type ActiveView =
  | { name: "dashboard" }
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
  // Demo-only: rehydrate the fixture state from localStorage once, so a refresh
  // does not wipe the walkthrough. Read a single time on mount.
  const [persisted] = useState<DemoSnapshot | null>(() => (dataMode === "fixture" ? loadDemoState() : null));
  const [signedIn, setSignedIn] = useState<boolean>(() => (dataMode === "fixture" ? loadSignedIn() : true));
  // localStorage is read in initializers above; render nothing until mounted so
  // the server and first client render match (no hydration mismatch).
  const [mounted, setMounted] = useState(false);
  const [activeView, setActiveView] = useState<ActiveView>({ name: "dashboard" });
  const [auditIntents, setAuditIntents] = useState<SessionAuditEntry[]>([]);
  const [demoState, setDemoState] = useState<ContainerState>(dataMode === "backend" ? "loading" : "populated");
  const [evidenceItems, setEvidenceItems] = useState<EvidenceItem[]>(
    dataMode === "backend" ? [] : persisted?.evidenceItems ?? manufacturerEvidence
  );
  // Extraction review data lifted to app state so accepts/corrections survive
  // navigation (fixture mode; backend mode fetches its own).
  const [reviewValues, setReviewValues] = useState<ReviewValue[]>(
    dataMode === "backend" ? [] : persisted?.reviewValues ?? manufacturerValues
  );
  const [isUploading, setIsUploading] = useState(false);
  const [processingDocumentIds, setProcessingDocumentIds] = useState<string[]>([]);
  const [backendError, setBackendError] = useState<string | null>(null);
  const requests = useRequestsStore(dataMode === "backend" ? [] : persisted?.asks ?? seedAsks);
  const verification = useVerificationStore(persisted?.examinations ?? {}, persisted?.findings ?? []);
  const [sessionUploads, setSessionUploads] = useState<string[]>(persisted?.sessionUploads ?? []);
  // Engagement config is editable on Setup; facilities here feed the Workspace.
  const [engagement, setEngagement] = useState<EngagementConfig>(persisted?.engagement ?? engagementConfig);
  const [inScopeFields, setInScopeFields] = useState<InScopeField[]>(persisted?.inScopeFields ?? inScopeFieldPlaceholders);

  // Demo-only: snapshot fixture state to localStorage so a refresh keeps it.
  useEffect(() => {
    if (dataMode !== "fixture") return;
    saveDemoState({
      engagement,
      evidenceItems,
      reviewValues,
      inScopeFields,
      sessionUploads,
      asks: requests.asks,
      examinations: verification.examinations,
      findings: verification.findings,
    });
  }, [
    dataMode,
    engagement,
    evidenceItems,
    reviewValues,
    inScopeFields,
    sessionUploads,
    requests.asks,
    verification.examinations,
    verification.findings,
  ]);

  useEffect(() => setMounted(true), []);

  function resetDemo() {
    clearDemoState();
    if (typeof window !== "undefined") window.location.reload();
  }

  // The scripted "upload one invoice" beat: add the prepared doc + values, play
  // the analysis progress, then open Extraction Review with the highlight.
  const [sampleScript, setSampleScript] = useState<SampleScript | null>(null);
  const DEMO_NODE = "F:facility-kent|T:Electricity bill";

  function runSampleUpload() {
    if (evidenceItems.some((i) => i.documentId === DEMO_INVOICE_ID)) {
      setActiveView({ name: "extraction", documentId: DEMO_INVOICE_ID, nodeKey: DEMO_NODE });
      return;
    }
    const now = new Date().toISOString();
    setEvidenceItems((cur) => [preparedInvoiceEvidence(now), ...cur]);
    setReviewValues((cur) => [...preparedInvoiceValues, ...cur]);
    setSessionUploads((cur) => [DEMO_INVOICE_ID, ...cur]);
    setSampleScript({ filename: DEMO_INVOICE_FILENAME, stage: "uploading", found: [], progress: 0.1 });

    const patchDoc = (patch: Partial<EvidenceItem>) =>
      setEvidenceItems((cur) => cur.map((i) => (i.documentId === DEMO_INVOICE_ID ? { ...i, ...patch } : i)));
    const step = (ms: number, fn: () => void) => window.setTimeout(fn, ms);

    step(500, () => setSampleScript((s) => (s ? { ...s, stage: "analyzing", progress: 0.35 } : s)));
    step(1300, () => {
      patchDoc({ processingState: "ingested", detectedType: "Electricity bill" });
      setSampleScript((s) => (s ? { ...s, stage: "classified", classified: "Electricity bill · Kent Cannery", progress: 0.55 } : s));
    });
    step(1800, () => setSampleScript((s) => (s ? { ...s, found: preparedInvoiceFoundOrder.slice(0, 1), progress: 0.7 } : s)));
    step(2200, () => setSampleScript((s) => (s ? { ...s, found: preparedInvoiceFoundOrder.slice(0, 2), progress: 0.82 } : s)));
    step(2600, () => setSampleScript((s) => (s ? { ...s, found: preparedInvoiceFoundOrder.slice(0, 3), progress: 0.92 } : s)));
    step(3100, () => {
      patchDoc(preparedInvoiceClassified);
      setSampleScript((s) => (s ? { ...s, stage: "done", progress: 1 } : s));
    });
    step(3600, () => {
      setSampleScript(null);
      setActiveView({ name: "extraction", documentId: DEMO_INVOICE_ID, nodeKey: DEMO_NODE });
    });
  }

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
    dashboard: "dashboard",
    setup: "setup",
    upload: "upload",
    requests: "requests",
    coverage: "coverage",
    results: "results",
    output: "output",
  };
  const navCurrent: NavKey = NAV_FOR_VIEW[activeView.name] ?? "evidence";
  function onNavigate(key: NavKey) {
    if (key === "dashboard") setActiveView({ name: "dashboard" });
    else if (key === "setup") setActiveView({ name: "setup" });
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

  if (!mounted) {
    return <div className="s1-signin" aria-hidden />;
  }

  if (!signedIn) {
    return (
      <DemoSignIn
        onSignIn={() => {
          saveSignedIn(true);
          setSignedIn(true);
        }}
      />
    );
  }

  return (
    <main className="s1-app">
      <S1Chrome
        engagement={engagement}
        current={navCurrent}
        onNavigate={onNavigate}
        onReset={dataMode === "fixture" ? resetDemo : undefined}
        onOpenGlossary={() =>
          setActiveView((current) =>
            current.name === "glossary" ? current : { name: "glossary", previous: current }
          )
        }
      >
        {activeView.name === "dashboard" ? (
          <DashboardScreen engagement={engagement} onNavigate={onNavigate} />
        ) : activeView.name === "setup" ? (
          <SetupScreen
            engagement={engagement}
            onChange={setEngagement}
            inScopeFields={inScopeFields}
            onInScopeChange={setInScopeFields}
          />
        ) : activeView.name === "upload" ? (
          <UploadScreen
            onUploadFiles={uploadFiles}
            onUploadSample={dataMode === "fixture" ? runSampleUpload : undefined}
            sampleFilename={
              dataMode === "fixture" && !evidenceItems.some((i) => i.documentId === DEMO_INVOICE_ID)
                ? DEMO_INVOICE_FILENAME
                : undefined
            }
            script={sampleScript}
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
          <OutputScreen engagement={engagement} />
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
            renderPage={(documentId, span, onPickBox) =>
              documentId === DEMO_INVOICE_ID ? (
                <InvoicePage
                  highlight={span ? { x: span.x, y: span.y, w: span.w, h: span.h } : null}
                  onMarkClick={onPickBox}
                />
              ) : null
            }
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
    means: "Detecting what a file is · utility bill, contractual instrument, workbook",
  },
  {
    term: "Classification",
    means: "Reserved for scope classification: Scope 1/2/3, and within Scope 2, location- vs market-based",
  },
  { term: "Gap", means: "User-facing label for an open finding. Not a separate object" },
  { term: "Finding", means: "The object carrying review state, failure cause, impact, disposition" },
  {
    term: "Request",
    means: "Engagement-level client ask. Many-to-many with findings · one request bundles gaps across several review items",
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
      { value: "missing_requestable", label: "Missing · requestable" },
      { value: "missing_not_requestable", label: "Missing · not requestable" },
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
