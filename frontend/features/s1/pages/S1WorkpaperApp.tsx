"use client";

import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";

import {
  getSignedInUser,
  isSessionEnded,
  listWorkspaceEvidence,
  signInAgainPath,
  submitFieldReview,
  uploadDocumentWithProgress,
  userFacingApiError,
} from "../api/s1Backend";
import { ApiError } from "../../../lib/api";
import { isActiveRun, readFailureMessage, requestRead, type ProcessingRunView } from "../api/processingRuns";
import { useProcessingRuns } from "../hooks/useProcessingRuns";
import { readAfterUpload, withReadingState } from "../utils/readingState";
import { reviewValuesFromFields, withRequestsFromAsks } from "../adapters/reviewValueAdapter";
import {
  getRecalculation,
  getRecalculationReference,
  inScopeFieldsFrom,
  lookupEgridZip,
  type DataPointOption,
  type QualityCheck,
} from "../api/recalculation";
import {
  applyDocumentView,
  BACKEND_TYPE_IDS,
  decisionFromEdit,
  documentFacts,
  unmatchedFacilities,
} from "../utils/documentView";
import { ExtractionReview } from "../components/ExtractionReview";
import { EvidenceWorkspace, type WorkspaceProblem } from "../components/EvidenceWorkspace";
import { S1Chrome, type NavKey, type WorkpaperUser } from "../components/S1Chrome";
import { logout } from "../../auth/api";
import { DashboardScreen } from "../components/DashboardScreen";
import { UploadDialog, uploadTasksFor, type SampleScript, type UploadTask } from "../components/UploadDialog";
import { SetupScreen } from "../components/SetupScreen";
import { DemoDocument } from "../components/demo/DemoDocument";
import {
  preparedInvoiceEvidence,
  preparedInvoiceValues,
  preparedInvoiceClassified,
  preparedInvoiceFoundOrder,
  DEMO_INVOICE_ID,
  DEMO_INVOICE_FILENAME,
} from "../fixtures/demo/preparedInvoice";
import { EvidenceRequests } from "../components/EvidenceRequests";
import { VerificationResults } from "../components/VerificationResults";
import { BackendVerificationResults } from "../components/BackendVerificationResults";
import { BackendPageView } from "../components/BackendPageView";
import { DocumentContentView } from "../components/DocumentContentView";
import { BackendOutputScreen } from "../components/BackendOutputScreen";
import { BackendDashboard } from "../components/BackendDashboard";
import { OutputScreen } from "../components/OutputScreen";
import { coverageRules } from "../fixtures/verification/coverageRules";
import { verificationRows } from "../fixtures/verification/verificationResults";
import { seedExaminations, verificationLines } from "../fixtures/verification/resultsDataset";
import { useVerificationStore } from "../verification/verificationStore";
import { useWorkpaperSync } from "../verification/useWorkpaperSync";
import { StateIndicator } from "../components/StateIndicator";
import { EXACT_COPY } from "../constants/copy";
import { uploadProblemTitle } from "../constants/uploads";
import { engagementConfig } from "../fixtures/engagementConfig";
import { inScopeFieldPlaceholders } from "../fixtures/scope/inScopeFields";
import type { EngagementConfig, InScopeField, RecalculationSettings } from "../types";
import { manufacturerEvidence } from "../fixtures/evidence/manufacturerEvidence";
import { manufacturerValues } from "../fixtures/extraction/manufacturerValues";
import { seedAsks } from "../fixtures/requests/seedAsks";
import { makeUploadItem, classifyGuess } from "../fixtures/upload/simulateUpload";
import { loadDemoState, saveDemoState, clearDemoState, loadSignedIn, saveSignedIn, type DemoSnapshot } from "../utils/demoPersistence";
import { DemoSignIn } from "../components/DemoSignIn";
import { SessionEndedPanel } from "../components/SessionEndedPanel";
import { EngagementPicker, type SaveState } from "../components/EngagementPicker";
import {
  createEngagement,
  engagementFromBackend,
  engagementSaveProblem,
  listEngagements,
  pickEngagement,
  rememberEngagement,
  saveEngagement,
  type BackendEngagement,
} from "../api/engagements";
import { useRequestsStore } from "../requests/requestsStore";
import type {
  ContainerState,
  DocumentDecision,
  EvidenceItem,
  ExtractedField,
  ReviewValue,
  StateDimension,
} from "../types";
import type { SessionAuditEntry } from "../utils/auditIntent";
import { dashboardFigures, engagementActivity } from "../utils/engagementActivity";
import { ActivityDrawer } from "../components/ActivityDrawer";
import { useBackendCoverage } from "../components/useBackendCoverage";
import { testedExaminationKeys } from "../utils/verificationTable";
import { MethodologyReview } from "../components/MethodologyReview";
import { emptyMethodologyReview, methodologyStated } from "../fixtures/methodology/methodologyReview";
import type { MethodologyState } from "../types/methodology";

type ActiveView =
  | { name: "dashboard" }
  | { name: "evidence" }
  | { name: "setup" }
  | { name: "requests" }
  | { name: "coverage" }
  | { name: "methodology" }
  | { name: "results" }
  | { name: "output" }
  | { name: "extraction"; documentId: string; mode?: "snippet" | "manual"; nodeKey?: string; valueId?: string }
  | { name: "glossary"; previous: Exclude<ActiveView, { name: "glossary" }> };

/** The files of the upload in progress (or just finished): the lines the Evidence banner lists,
 *  and the documents whose reads may still fail after the upload dialog has moved on. */
interface UploadBatch {
  notUploaded: string[];
  notRead: string[];
  /** File name by document id, for the files that were stored. */
  names: Map<string, string>;
}

/** Facility->type (or entity/not-yet-known) node a Workspace row maps into. */
function nodeKeyForEvidence(item: EvidenceItem): string {
  const type = item.detectedType ?? "Type unresolved";
  if (item.facilityState === "resolved" && item.facilityId) return `F:${item.facilityId}|T:${type}`;
  if (item.facilityState === "unresolved") return "N";
  return "E"; // multiple / not_facility_scoped -> entity-level
}

/** Why loading failed, in the API's words when it gave any. */
function loadFailure(error: unknown): string {
  return error instanceof Error ? error.message : "Check your connection and reload the page.";
}

/** A blank engagement — the starting point in backend mode. No templated data;
 *  the user configures it in Setup (or it is created/loaded from the backend). */
const EMPTY_ENGAGEMENT: EngagementConfig = {
  clientName: "",
  engagementId: "",
  reportingPeriod: { start: "", end: "" },
  facilities: [],
  regulation: "",
  conclusionType: "",
  assuranceLevel: "",
  boundaryApproach: "",
  scopeBoundaryStatement: "",
};

/** The demo's signed-in verifier, who writes the notes saved in fixture mode. */
const DEMO_ACTOR = engagementConfig.engagementTeam?.find((m) => m.login === engagementConfig.signedInLogin)?.name;

export function S1WorkpaperApp({ user }: { user?: WorkpaperUser } = {}) {
  const dataMode = process.env.NEXT_PUBLIC_S1_DATA_MODE === "fixture" ? "fixture" : "backend";
  // Demo-only: rehydrate the fixture state from localStorage once, so a refresh
  // does not wipe the walkthrough. Read a single time on mount.
  const [persisted] = useState<DemoSnapshot | null>(() => (dataMode === "fixture" ? loadDemoState() : null));
  const [signedIn, setSignedIn] = useState<boolean>(() => (dataMode === "fixture" ? loadSignedIn() : true));
  // localStorage is read in initializers above; render nothing until mounted so
  // the server and first client render match (no hydration mismatch).
  // useSyncExternalStore returns false on the server / hydration pass and true
  // on the client, without a setState-in-effect.
  const mounted = useSyncExternalStore(
    () => () => {},
    () => true,
    () => false
  );
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
  const [uploadTasks, setUploadTasks] = useState<UploadTask[]>([]);
  // Backend mode: every extracted field (facts about each document) and the reviewer's
  // saved decisions per document, laid over the machine's view of the evidence.
  const [workspaceFields, setWorkspaceFields] = useState<ExtractedField[]>([]);
  const [documentDecisions, setDocumentDecisions] = useState<Record<string, DocumentDecision>>({});
  const [gridRegions, setGridRegions] = useState<{ code: string; name: string }[] | undefined>(undefined);
  const [dataPoints, setDataPoints] = useState<DataPointOption[]>([]);
  const [backendError, setBackendError] = useState<WorkspaceProblem | null>(null);
  // Backend mode: a 401 from the API means the session ended (FE-007).
  const [sessionEnded, setSessionEnded] = useState(false);
  const requests = useRequestsStore(dataMode === "backend" ? [] : persisted?.asks ?? seedAsks);
  const verification = useVerificationStore(
    persisted?.examinations ?? (dataMode === "fixture" ? seedExaminations : {}),
    persisted?.findings ?? [],
    dataMode === "backend" ? user?.firstName ?? user?.email : DEMO_ACTOR
  );
  const [sessionUploads, setSessionUploads] = useState<string[]>(persisted?.sessionUploads ?? []);
  // Engagement config is editable on Setup; facilities here feed the Workspace.
  // Backend mode starts blank (no templated data); fixture mode seeds the demo.
  // A demo saved before the engagement had a name gets the fixture's, so the context bar
  // shows the name rather than the ID.
  const [engagement, setEngagement] = useState<EngagementConfig>(
    persisted?.engagement
      ? { ...persisted.engagement, engagementName: persisted.engagement.engagementName || engagementConfig.engagementName }
      : dataMode === "fixture"
        ? engagementConfig
        : EMPTY_ENGAGEMENT
  );
  // Backend mode: the org's engagements (S1-BE-002); null until loaded.
  const [engagements, setEngagements] = useState<BackendEngagement[] | null>(dataMode === "backend" ? null : []);

  // Reference lists for Setup (backend mode): eGRID subregions for the facility picker and
  // the workbook's reported data points for the in-scope list.
  useEffect(() => {
    if (dataMode !== "backend") return;
    let live = true;
    getRecalculationReference()
      .then((ref) => {
        if (!live) return;
        setGridRegions(ref.egrid_subregions.map((r) => ({ code: r.egrid_subregion, name: r.name })));
        setDataPoints(ref.data_points ?? []);
      })
      .catch(() => undefined); // the picker simply stays hidden
    return () => {
      live = false;
    };
  }, [dataMode]);

  // Requests, findings and examination states are saved per engagement (backend mode).
  useWorkpaperSync({
    enabled: dataMode === "backend",
    engagementId: engagement.engagementId,
    asks: requests.asks,
    findings: verification.findings,
    examinations: verification.examinations,
    documents: documentDecisions,
    replaceAsks: requests.replaceAsks,
    replaceVerification: verification.replaceAll,
    replaceDocuments: setDocumentDecisions,
    onError: (error) => {
      if (handleSessionEnded(error)) return;
      setBackendError({ title: "Your last change wasn't saved", message: userFacingApiError(error) });
    },
  });
  const [engagementSave, setEngagementSave] = useState<SaveState>("idle");
  const [engagementSaveMessage, setEngagementSaveMessage] = useState<string | null>(null);
  const saveTimer = useRef<number | null>(null);
  const [inScopeFields, setInScopeFields] = useState<InScopeField[]>(
    persisted?.inScopeFields ?? (dataMode === "fixture" ? inScopeFieldPlaceholders : [])
  );
  // Methodology review (demo): the verifier's acceptances and changes to the stated methodology.
  const [methodology, setMethodology] = useState<MethodologyState>(() => persisted?.methodology ?? emptyMethodologyReview());

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
      methodology,
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
    methodology,
  ]);


  function resetDemo() {
    clearDemoState();
    if (typeof window !== "undefined") window.location.reload();
  }

  // The scripted "upload one invoice" beat: add the prepared doc + values, play
  // the analysis progress, then open Extraction Review with the highlight.
  const [sampleScript, setSampleScript] = useState<SampleScript | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [activityOpen, setActivityOpen] = useState(false);
  const DEMO_NODE = "F:facility-kent|T:Electricity bill";

  function runSampleUpload() {
    if (evidenceItems.some((i) => i.documentId === DEMO_INVOICE_ID)) {
      setUploadOpen(false);
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
      setUploadOpen(false);
      setActiveView({ name: "extraction", documentId: DEMO_INVOICE_ID, nodeKey: DEMO_NODE });
    });
  }

  /** On a 401, send the user to log in again (back to this page afterwards).
   *  Returns true when the error was handled that way. */
  function handleSessionEnded(error: unknown): boolean {
    if (!isSessionEnded(error)) return false;
    setSessionEnded(true);
    const path = signInAgainPath(window.location.pathname + window.location.search);
    if (path) window.location.assign(path);
    return true;
  }

  useEffect(() => {
    if (dataMode !== "backend") return;
    // Confirm the session first, so a signed-out visitor is sent to log in even
    // before an engagement is configured; then load the workspace.
    void getSignedInUser()
      .then(() => listEngagements())
      .then((items) => {
        setEngagements(items);
        const picked = pickEngagement(items);
        if (picked) {
          setEngagement(engagementFromBackend(picked));
          rememberEngagement(picked.id);
        }
        return refreshBackendWorkspace(undefined, picked?.id ?? "");
      })
      .catch((error: unknown) => {
        if (handleSessionEnded(error)) return;
        setBackendError({ title: "Couldn't load the engagement", message: loadFailure(error) });
        setDemoState("error_degraded");
      });
  }, [dataMode]);

  async function refreshBackendWorkspace(
    nextContainerState?: ContainerState,
    engagementId: string = engagement.engagementId
  ) {
    // No engagement configured yet → nothing to fetch; show the empty state.
    if (!engagementId) {
      setEvidenceItems([]);
      setWorkspaceFields([]);
      setReviewValues([]);
      setDemoState("empty_nothing_yet");
      return;
    }
    setBackendError(null);
    try {
      const workspace = await listWorkspaceEvidence(engagementId);
      setEvidenceItems(workspace.evidence);
      setWorkspaceFields(workspace.fields);
      setReviewValues(reviewValuesFromFields(workspace.fields, workspace.evidence));
      setDemoState(nextContainerState ?? (workspace.evidence.length === 0 ? "empty_nothing_yet" : "populated"));
    } catch (error) {
      if (handleSessionEnded(error)) return;
      setBackendError({ title: "Couldn't load the evidence", message: loadFailure(error) });
      setDemoState("error_degraded");
    }
  }

  // Backend mode: reads run in the background. The runs say which documents are still being
  // read, and the page hears when a read finishes. Fixture mode never fetches or schedules.
  const uploadBatch = useRef<UploadBatch>({ notUploaded: [], notRead: [], names: new Map() });
  // Reads a reviewer asked for (setting a document's type), by run id, with the banner title to
  // use if one fails after the request has answered.
  const rereadRuns = useRef(new Map<string, string>());

  /** The Evidence banner for an upload batch: the files that weren't uploaded or weren't read.
   *  `refreshBackendWorkspace` clears the banner as it starts, so this is set after a refresh. */
  function showUploadProblems(batch: UploadBatch) {
    if (batch.notUploaded.length === 0 && batch.notRead.length === 0) return;
    setBackendError({
      title: uploadProblemTitle(batch.notUploaded.length, batch.notRead.length),
      message: [...batch.notUploaded, ...batch.notRead].join(" "),
    });
  }

  /** Reads that were queued have finished: settle the upload dialog's rows, load what the reads
   *  produced once, then tell what failed. */
  function handleReadsFinished(runs: ProcessingRunView[]) {
    const batch = uploadBatch.current;
    let problem: WorkspaceProblem | null = null;
    for (const run of runs) {
      const rereadTitle = rereadRuns.current.get(run.run_id);
      if (rereadTitle !== undefined) {
        rereadRuns.current.delete(run.run_id);
        if (run.status === "failed") problem = { title: rereadTitle, message: readFailureMessage(run) };
        continue;
      }
      const name = batch.names.get(run.document_id);
      if (name === undefined) continue;
      const patch: Partial<UploadTask> =
        run.status === "completed"
          ? { stage: "done" }
          : { stage: "failed", error: `Uploaded, but could not be read: ${readFailureMessage(run)}` };
      setUploadTasks((current) =>
        current.map((task) => (task.documentId === run.document_id ? { ...task, ...patch } : task))
      );
      if (patch.stage === "failed") batch.notRead.push(`${name}: ${patch.error}`);
    }
    void refreshBackendWorkspace("populated").then(() => {
      if (problem) setBackendError(problem);
      else showUploadProblems(batch);
    });
  }

  const reads = useProcessingRuns({
    enabled: dataMode === "backend",
    engagementId: engagement.engagementId,
    onFinished: handleReadsFinished,
    onError: handleSessionEnded,
  });

  function selectEngagement(id: string) {
    const row = engagements?.find((item) => item.id === id);
    if (!row) return;
    flushEngagementSave();
    setEngagement(engagementFromBackend(row));
    rememberEngagement(row.id);
    setEngagementSave("idle");
    setDemoState("loading");
    void refreshBackendWorkspace(undefined, row.id);
  }

  async function createAndSelectEngagement(name: string) {
    try {
      const row = await createEngagement(name);
      setEngagements((current) => [row, ...(current ?? [])]);
      flushEngagementSave();
      setEngagement(engagementFromBackend(row));
      rememberEngagement(row.id);
      setEngagementSave("idle");
      await refreshBackendWorkspace(undefined, row.id);
    } catch (error) {
      if (handleSessionEnded(error)) return;
      throw new Error(
        error instanceof ApiError && error.status === 403
          ? "Your role can view engagements but not create them."
          : userFacingApiError(error)
      );
    }
  }

  // Setup edits save to the picked engagement shortly after typing stops.
  const pendingSave = useRef<EngagementConfig | null>(null);

  function flushEngagementSave() {
    if (saveTimer.current !== null) window.clearTimeout(saveTimer.current);
    saveTimer.current = null;
    const config = pendingSave.current;
    pendingSave.current = null;
    if (config) void persistEngagement(config);
  }

  async function persistEngagement(config: EngagementConfig) {
    const problem = engagementSaveProblem(config);
    if (problem) {
      setEngagementSave("error");
      setEngagementSaveMessage(problem);
      return;
    }
    setEngagementSave("saving");
    try {
      const row = await saveEngagement(config);
      setEngagements((current) => (current ?? []).map((item) => (item.id === row.id ? row : item)));
      setEngagementSave("saved");
      setEngagementSaveMessage(null);
    } catch (error) {
      if (handleSessionEnded(error)) return;
      setEngagementSave("error");
      setEngagementSaveMessage(
        error instanceof ApiError && error.status === 403
          ? "Your role can view this engagement but not change it."
          : `Changes not saved. ${userFacingApiError(error)}`
      );
    }
  }

  /** Saves the recalculation inputs now, folding in any Setup edit still waiting to save. */
  async function saveRecalculationInputs(recalculation: RecalculationSettings) {
    if (saveTimer.current !== null) window.clearTimeout(saveTimer.current);
    saveTimer.current = null;
    const base = pendingSave.current ?? engagement;
    pendingSave.current = null;
    const next = { ...base, recalculation };
    const row = await saveEngagement(next);
    setEngagements((current) => (current ?? []).map((item) => (item.id === row.id ? row : item)));
    setEngagement(next);
  }

  function changeEngagement(next: EngagementConfig) {
    setEngagement(next);
    if (dataMode !== "backend" || !next.engagementId) return;
    pendingSave.current = next;
    if (saveTimer.current !== null) window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(flushEngagementSave, 700);
  }

  async function signOut() {
    flushEngagementSave();
    try {
      await logout();
    } catch {
      // The cookie may already be gone; continue to the login page either way.
    }
    // The realm cookie stays, so this browser goes back to the same login page.
    window.location.assign(signInAgainPath("/") ?? "/sign-in");
  }

  function addAuditIntent(intent: SessionAuditEntry) {
    setAuditIntents((current) => [...current, intent]);
  }

  function openExtraction(documentId: string, valueId?: string) {
    const item = evidenceItems.find((i) => i.documentId === documentId);
    setActiveView({
      name: "extraction",
      documentId,
      mode: "snippet",
      nodeKey: item ? nodeKeyForEvidence(item) : undefined,
      valueId,
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
    requests: "requests",
    coverage: "requests",
    methodology: "methodology",
    results: "results",
    output: "output",
  };
  const navCurrent: NavKey = NAV_FOR_VIEW[activeView.name] ?? "evidence";
  function onNavigate(key: NavKey) {
    if (key === "dashboard") setActiveView({ name: "dashboard" });
    else if (key === "setup") setActiveView({ name: "setup" });
    else if (key === "upload") setUploadOpen(true);
    else if (key === "requests") setActiveView({ name: "requests" });
    else if (key === "coverage") setActiveView({ name: "requests" });
    else if (key === "methodology") setActiveView({ name: "methodology" });
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

  /** Evidence edits in backend mode become saved decisions; a new type re-reads the document. */
  function changeEvidence(updater: (cur: EvidenceItem[]) => EvidenceItem[]) {
    if (dataMode !== "backend") {
      setEvidenceItems(updater);
      return;
    }
    const before = new Map(evidenceView.map((item) => [item.documentId, item]));
    const after = updater(evidenceView);
    const changes: Record<string, DocumentDecision> = {};
    const retype: { documentId: string; typeId: string }[] = [];
    for (const item of after) {
      const prior = before.get(item.documentId);
      if (!prior) continue;
      const decision = decisionFromEdit(prior, item, documentDecisions[item.documentId]);
      if (!decision) continue;
      changes[item.documentId] = decision;
      const typeId = item.detectedType ? BACKEND_TYPE_IDS[item.detectedType] : undefined;
      if (item.detectedType !== prior.detectedType && typeId) retype.push({ documentId: item.documentId, typeId });
    }
    if (Object.keys(changes).length) setDocumentDecisions((cur) => ({ ...cur, ...changes }));
    for (const { documentId, typeId } of retype) void rereadAs(documentId, typeId);
  }

  /** Ask for a document to be read as a type the reviewer set. A read that is only queued is
   *  followed by the runs hook; its failure is told when it finishes (handleReadsFinished). */
  async function rereadAs(documentId: string, typeId: string) {
    const title = "Couldn't read the document as that type";
    try {
      const run = await requestRead(documentId, typeId);
      if (isActiveRun(run)) {
        rereadRuns.current.set(run.run_id, title);
        reads.track(run);
        return;
      }
      await refreshBackendWorkspace("populated");
      if (run.status === "failed") setBackendError({ title, message: readFailureMessage(run) });
    } catch (error) {
      if (handleSessionEnded(error)) return;
      setBackendError({ title, message: userFacingApiError(error) });
    }
  }

  async function handleUploadFiles(files: FileList) {
    if (dataMode !== "backend") return;
    if (!engagement.engagementId) {
      setBackendError({ title: "Couldn't upload", message: "Create or pick an engagement in Setup before uploading." });
      return;
    }
    const picked = Array.from(files);
    // A file no parser can read is set aside as not uploaded and never sent.
    const tasks = uploadTasksFor(picked, Date.now().toString(36));
    const patchTask = (id: string, next: Partial<UploadTask>) =>
      setUploadTasks((current) => current.map((task) => (task.id === id ? { ...task, ...next } : task)));
    setUploadTasks(tasks);
    setIsUploading(true);
    setBackendError(null);
    // One line per file for the Evidence banner: not uploaded, then uploaded but not read. Reads
    // that fail after the upload has moved on (queued reads) are added by handleReadsFinished.
    const batch: UploadBatch = {
      notUploaded: tasks.flatMap((task) => (task.stage === "not_uploaded" && task.error ? [task.error] : [])),
      notRead: [],
      names: new Map(),
    };
    uploadBatch.current = batch;
    const sending = tasks.some((task) => task.stage === "waiting");
    for (const [index, file] of picked.entries()) {
      const taskId = tasks[index].id;
      if (tasks[index].stage === "not_uploaded") continue;
      let uploadedId: string | null = null;
      try {
        patchTask(taskId, { stage: "uploading" });
        const document = await uploadDocumentWithProgress(engagement.engagementId, file, (fraction) =>
          patchTask(taskId, { progress: fraction })
        );
        uploadedId = document.document_id;
        batch.names.set(document.document_id, file.name);
        patchTask(taskId, { stage: "reading", progress: 1, documentId: document.document_id });
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
        // Queued, the read is only started: the runs hook follows it and the next file goes up.
        // Inline, this waits for the read itself. The task already says Reading… until it ends.
        const start = await readAfterUpload(document);
        if (start.kind === "reading") {
          reads.track(start.run);
        } else if (start.kind === "done") {
          patchTask(taskId, { stage: "done" });
        } else {
          patchTask(taskId, { stage: "failed", error: start.reason });
          batch.notRead.push(`${file.name}: ${start.reason}`);
        }
      } catch (error) {
        if (handleSessionEnded(error)) {
          setIsUploading(false);
          return;
        }
        if (uploadedId) {
          // Uploaded, but asking for the read failed: the row and the banner say why.
          const reason = `Uploaded, but could not be read: ${userFacingApiError(error)}`;
          patchTask(taskId, { stage: "failed", error: reason });
          batch.notRead.push(`${file.name}: ${reason}`);
        } else {
          // Not stored: the API's own words say why (its 415 names the file).
          const reason = userFacingApiError(error);
          patchTask(taskId, { stage: "not_uploaded", progress: 0, error: reason });
          batch.notUploaded.push(reason.includes(file.name) ? reason : `${file.name}: ${reason}`);
        }
      }
    }
    if (sending) await refreshBackendWorkspace("populated");
    showUploadProblems(batch);
    setIsUploading(false);
  }

  async function handleProcessDocument(documentId: string) {
    if (dataMode !== "backend") return;
    setBackendError(null);
    const title = "Couldn't read the document";
    try {
      const run = await requestRead(documentId);
      if (isActiveRun(run)) {
        rereadRuns.current.set(run.run_id, title);
        reads.track(run);
        return;
      }
      await refreshBackendWorkspace("populated");
      if (run.status === "failed") setBackendError({ title, message: readFailureMessage(run) });
    } catch (error) {
      if (handleSessionEnded(error)) return;
      await refreshBackendWorkspace();
      setBackendError({ title, message: userFacingApiError(error) });
    }
  }

  // Backend mode: the evidence as the screens show it (Setup facility, period, decisions).
  const facts = useMemo(() => documentFacts(workspaceFields), [workspaceFields]);
  const evidenceView = useMemo(
    () =>
      dataMode === "backend"
        ? withReadingState(applyDocumentView(evidenceItems, facts, documentDecisions, engagement.facilities), reads.runs)
        : evidenceItems,
    [dataMode, evidenceItems, facts, documentDecisions, engagement.facilities, reads.runs]
  );
  // The data quality checks behind the Evidence screen's Issue column (backend mode), fetched
  // again when the documents or the reviewer's decisions change.
  const [qualityChecks, setQualityChecks] = useState<QualityCheck[] | undefined>(undefined);
  const evidenceSignature = useMemo(
    () => evidenceView.map((e) => `${e.documentId}:${e.processingState}:${e.disposition}:${e.relationships.length}`).join("|"),
    [evidenceView]
  );
  useEffect(() => {
    if (dataMode !== "backend" || activeView.name !== "evidence" || !engagement.engagementId) return;
    let live = true;
    getRecalculation(engagement.engagementId)
      .then((result) => {
        if (live) setQualityChecks(result.quality_checks);
      })
      .catch(() => {
        // The Issue column then shows the document's own issues only.
      });
    return () => {
      live = false;
    };
  }, [dataMode, activeView.name, engagement.engagementId, evidenceSignature]);
  const reviewValuesView = useMemo(() => {
    // A card's latest request decides whether it is requested, in the session and after a reload.
    const settled = withRequestsFromAsks(reviewValues, requests.asks);
    if (dataMode !== "backend") return settled;
    const byId = new Map(evidenceView.map((item) => [item.documentId, item]));
    return settled.map((value) => {
      const item = byId.get(value.documentId);
      if (!item) return value;
      return {
        ...value,
        facilityId: item.facilityId,
        notYetKnown: !item.facilityId,
        documentType: item.detectedType ?? value.documentType,
        withdrawn: item.disposition === "withdrawn",
        withdrawnReason: item.disposition === "withdrawn" ? "Document withdrawn; it is left out of the results." : undefined,
      };
    });
  }, [dataMode, reviewValues, evidenceView, requests.asks]);
  const backendCoverage = useBackendCoverage(
    engagement.engagementId,
    dataMode === "backend" && (activeView.name === "requests" || activeView.name === "coverage"),
    handleSessionEnded
  );
  // What the demo's assistant may look things up in: the engagement as the screens show it.
  const assistantData = useMemo(
    () =>
      dataMode === "fixture"
        ? {
                  engagement,
                  evidence: evidenceView,
                  values: reviewValuesView,
                  asks: requests.asks,
                  coverage: coverageRules,
                  resultLines: verificationLines,
                  examinations: verification.examinations,
                  findings: verification.findings,
                  activity: engagementActivity({
                    evidence: evidenceView,
                    values: reviewValuesView,
                    asks: requests.asks,
                    findings: verification.findings,
                    intents: auditIntents,
                    methodology: methodology.log,
                  }),
                  figures: dashboardFigures({
                    evidence: evidenceView,
                    values: reviewValuesView,
                    asks: requests.asks,
                    findings: verification.findings,
                    examinations: verification.examinations,
                    coverage: coverageRules,
                    calculatedIds: testedExaminationKeys(verificationLines),
                  }),
                }
        : null,
    [dataMode, engagement, evidenceView, reviewValuesView, requests.asks, verification.examinations, verification.findings, auditIntents, methodology.log]
  );
  const foundFacilities = useMemo(
    () => (dataMode === "backend" ? unmatchedFacilities(facts, engagement.facilities) : []),
    [dataMode, facts, engagement.facilities]
  );

  if (!mounted) {
    return <div className="s1-signin" aria-hidden />;
  }

  if (sessionEnded) {
    return <SessionEndedPanel next={window.location.pathname + window.location.search} />;
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

  // Screens that record who did something get the signed-in person (backend mode).
  const engagementForUser: EngagementConfig =
    dataMode === "backend" && user
      ? {
          ...engagement,
          signedInLogin: engagement.signedInLogin ?? user.email,
          signedInName: engagement.signedInName ?? user.firstName ?? user.email,
        }
      : engagement;

  return (
    <main className="s1-app">
      <S1Chrome
        engagement={engagement}
        user={dataMode === "backend" ? user : undefined}
        onSignOut={dataMode === "backend" && user ? () => void signOut() : undefined}
        current={navCurrent}
        onNavigate={onNavigate}
        onReset={dataMode === "fixture" ? resetDemo : undefined}
        hiddenNav={dataMode === "backend" ? ["methodology"] : undefined}
        onOpenActivity={() => setActivityOpen(true)}
        assistant={assistantData ? { data: assistantData, onOpenDocument: openExtraction, onNavigate } : undefined}
        onOpenGlossary={() =>
          setActiveView((current) =>
            current.name === "glossary" ? current : { name: "glossary", previous: current }
          )
        }
      >
        {activeView.name === "dashboard" ? (
          dataMode === "backend" ? (
            <BackendDashboard
              engagement={engagement}
              evidence={evidenceView}
              values={reviewValuesView}
              asks={requests.asks}
              findings={verification.findings}
              examinations={verification.examinations}
              onNavigate={onNavigate}
              onError={handleSessionEnded}
            />
          ) : (
            <DashboardScreen
              engagement={engagement}
              figures={dashboardFigures({
                evidence: evidenceView,
                values: reviewValuesView,
                asks: requests.asks,
                findings: verification.findings,
                examinations: verification.examinations,
                coverage: coverageRules,
                calculatedIds: testedExaminationKeys(verificationLines),
              })}
              onNavigate={onNavigate}
            />
          )
        ) : activeView.name === "setup" ? (
          <SetupScreen
            engagement={engagement}
            onChange={changeEngagement}
            picker={
              dataMode === "backend" && engagements !== null ? (
                <EngagementPicker
                  engagements={engagements.map((e) => ({ id: e.id, name: e.name, clientName: e.client_name }))}
                  selectedId={engagement.engagementId}
                  onSelect={selectEngagement}
                  onCreate={createAndSelectEngagement}
                  saveState={engagementSave}
                  message={engagementSaveMessage}
                />
              ) : undefined
            }
            inScopeFields={
              dataMode === "backend" ? inScopeFieldsFrom(dataPoints, engagement.outOfScopeDataPoints) : inScopeFields
            }
            onInScopeChange={
              dataMode === "backend"
                ? (fields) =>
                    changeEngagement({
                      ...engagement,
                      outOfScopeDataPoints: fields.filter((f) => !f.inScope).map((f) => f.methodologyFieldId),
                    })
                : setInScopeFields
            }
            gridRegions={dataMode === "backend" ? gridRegions : undefined}
            lookupZip={dataMode === "backend" ? lookupEgridZip : undefined}
            foundFacilities={foundFacilities}
          />
        ) : activeView.name === "requests" || activeView.name === "coverage" ? (
          <EvidenceRequests
            engagement={engagementForUser}
            asks={requests.asks}
            coverage={dataMode === "backend" ? backendCoverage : { rules: coverageRules }}
            valuesToReview={reviewValuesView.filter((v) => !v.withdrawn && v.reviewState === "to_review").length}
            onReview={() => {
              const next = reviewValuesView.find((v) => !v.withdrawn && v.reviewState === "to_review");
              if (next) openExtraction(next.documentId);
            }}
            onSaveAsk={requests.saveAsk}
            onSend={(ids, lineNumbers) => requests.sendAsks(ids, lineNumbers).requestNumber}
            onResolve={requests.resolveAsk}
            onWithdraw={requests.withdrawAsk}
            onEdit={requests.editAsk}
            onRaiseFollowUp={raiseFollowUp}
            onOpenSource={(ask) => ask.source.documentId && openExtraction(ask.source.documentId)}
          />
        ) : activeView.name === "methodology" ? (
          // Demo only for now: the backend does not read the methodology from the report yet.
          dataMode === "fixture" ? (
            <MethodologyReview
              stated={methodologyStated}
              review={methodology}
              onChange={setMethodology}
              verifier={engagement.engagementTeam?.find((m) => m.login === engagement.signedInLogin)?.name ?? DEMO_ACTOR ?? "Verifier"}
            />
          ) : null
        ) : activeView.name === "results" ? (
          dataMode === "backend" ? (
            <BackendVerificationResults
              engagement={engagementForUser}
              store={verification}
              onSaveInputs={saveRecalculationInputs}
              onError={handleSessionEnded}
              onOpenDocument={openExtraction}
            />
          ) : (
            <VerificationResults
              rows={verificationRows}
              lines={verificationLines}
              store={verification}
              team={engagement.engagementTeam ?? []}
              signedInLogin={engagement.signedInLogin}
            />
          )
        ) : activeView.name === "output" ? (
          dataMode === "backend" ? (
            <BackendOutputScreen
              engagement={engagement}
              evidence={evidenceView}
              values={reviewValuesView}
              asks={requests.asks}
              findings={verification.findings}
              onError={handleSessionEnded}
            />
          ) : (
            <OutputScreen
              engagement={engagement}
              lines={verificationLines}
              figures={dashboardFigures({
                evidence: evidenceView,
                values: reviewValuesView,
                asks: requests.asks,
                findings: verification.findings,
                examinations: verification.examinations,
                coverage: coverageRules,
                calculatedIds: testedExaminationKeys(verificationLines),
              })}
            />
          )
        ) : activeView.name === "evidence" ? (
          <EvidenceWorkspace
            engagement={engagementForUser}
            evidence={evidenceView}
            asks={requests.asks}
            onSaveAsk={requests.saveAsk}
            onResolveAsk={requests.resolveAsk}
            onEvidenceChange={changeEvidence}
            onOpenRequests={() => setActiveView({ name: "requests" })}
            auditIntents={auditIntents}
            onAuditIntent={addAuditIntent}
            demoState={demoState}
            onOpenExtraction={openExtraction}
            onUploadFiles={(files) => {
              setUploadOpen(true);
              uploadFiles(files);
            }}
            onOpenUpload={() => setUploadOpen(true)}
            isUploading={isUploading}
            backendError={backendError}
            writesEnabled
            typeOptions={dataMode === "backend" ? Object.keys(BACKEND_TYPE_IDS) : undefined}
            qualityChecks={qualityChecks}
          />
        ) : activeView.name === "extraction" ? (
          <ExtractionReview
            engagement={engagementForUser}
            values={reviewValuesView}
            onValuesChange={setReviewValues}
            key={`${activeView.documentId}:${activeView.valueId ?? ""}`}
            initialDocumentId={activeView.documentId}
            initialDocumentName={evidenceView.find((e) => e.documentId === activeView.documentId)?.filename}
            initialValueId={activeView.valueId}
            initialNodeKey={activeView.nodeKey}
            onSaveAsk={requests.saveAsk}
            asks={requests.asks}
            onBack={() => setActiveView({ name: "evidence" })}
            reviewerName={dataMode === "backend" ? user?.firstName ?? user?.email : undefined}
            allowAddValue={dataMode === "fixture"}
            onValueAdded={(value, filled) => {
              // The document follows its new value: a field it was missing is found, and the
              // Evidence row's status and issue update with it.
              setEvidenceItems((cur) =>
                cur.map((item) =>
                  item.documentId !== value.documentId
                    ? item
                    : {
                        ...item,
                        fieldsExtracted: filled ? Math.min(item.fieldsExtracted + 1, item.fieldsExpectedDisplay ?? item.fieldsExpected) : item.fieldsExtracted,
                        missingFields: (item.missingFields ?? []).filter((f) => f.toLowerCase() !== value.whatItIs.toLowerCase()),
                      }
                )
              );
            }}
            onPersistAccept={
              dataMode === "backend"
                ? async (value) => {
                    try {
                      await submitFieldReview({ field: { reviewToken: value.reviewToken }, decision: "accepted" });
                    } catch (error) {
                      if (handleSessionEnded(error)) return;
                      throw error instanceof ApiError ? new Error(userFacingApiError(error)) : error;
                    }
                  }
                : undefined
            }
            onPersistCorrect={
              dataMode === "backend"
                ? async (value, next) => {
                    try {
                      await submitFieldReview({
                        field: { reviewToken: value.reviewToken },
                        decision: "edited",
                        reviewedValue: next.value,
                        reviewedUnit: next.unit && next.unit !== value.unit ? next.unit : null,
                      });
                    } catch (error) {
                      if (handleSessionEnded(error)) return;
                      throw error instanceof ApiError ? new Error(userFacingApiError(error)) : error;
                    }
                  }
                : undefined
            }
            drawnWhole={(id) =>
              dataMode === "fixture" && reviewValuesView.some((v) => v.documentId === id)
            }
            renderPage={(documentId, span, onPickBox, marks, pick) => {
              const item = evidenceItems.find((e) => e.documentId === documentId);
              const format = item?.format ?? "";
              // Drawn as content: workbooks, CSVs, Word and plain-text files, emails (not TIFFs and other images).
              const asContent =
                ["xlsx", "csv", "docx"].includes(format) ||
                (format === "other" && /\.(txt|md|markdown|eml)$/i.test(item?.filename ?? ""));
              const demoValues =
                dataMode === "fixture" ? reviewValuesView.filter((v) => v.documentId === documentId) : [];
              return demoValues.length ? (
                // The demo's documents, drawn whole with every value highlighted in place.
                <DemoDocument
                  values={demoValues}
                  engagement={engagement}
                  selectedId={pick?.selectedId ?? null}
                  onPick={(ids) => pick?.onPickAmong(ids)}
                  onAddValue={pick?.onAddValue}
                  highlighting={pick?.highlighting}
                  onHighlightingChange={pick?.onHighlightingChange}
                />
              ) : dataMode === "backend" && ["pdf", "image"].includes(format) ? (
                // The uploaded page as an image, the value outlined where it was read.
                <BackendPageView
                  key={`${documentId}:${span?.page ?? 0}`}
                  documentId={documentId}
                  span={span}
                  marks={marks}
                  onPickMark={onPickBox ? (m) => m.span && onPickBox(m.span, m.id) : undefined}
                />
              ) : dataMode === "backend" && asContent ? (
                // A workbook, CSV or Word file drawn as its cells or lines, the value marked.
                <DocumentContentView
                  key={documentId}
                  documentId={documentId}
                  marks={marks ?? []}
                  selectedId={pick?.selectedId ?? null}
                  onPickAmong={pick?.onPickAmong}
                />
              ) : null;
            }}
          />
        ) : (
          <GlossaryPage onBack={() => setActiveView(activeView.previous)} />
        )}
        {uploadOpen ? (
          <UploadDialog
            onClose={() => setUploadOpen(false)}
            onUploadFiles={uploadFiles}
            onUploadSample={dataMode === "fixture" ? runSampleUpload : undefined}
            sampleFilename={
              dataMode === "fixture" && !evidenceItems.some((i) => i.documentId === DEMO_INVOICE_ID)
                ? DEMO_INVOICE_FILENAME
                : undefined
            }
            script={sampleScript}
            batch={dataMode === "backend" ? [] : sessionUploadItems}
            tasks={dataMode === "backend" ? uploadTasks : undefined}
            items={dataMode === "backend" ? evidenceItems : undefined}
            onOpenWorkspace={() => setActiveView({ name: "evidence" })}
          />
        ) : null}
        {activityOpen ? (
          <ActivityDrawer
            entries={engagementActivity({
              evidence: evidenceView,
              values: reviewValuesView,
              asks: requests.asks,
              findings: verification.findings,
              intents: auditIntents,
              methodology: dataMode === "fixture" ? methodology.log : undefined,
            })}
            onClose={() => setActivityOpen(false)}
          />
        ) : null}
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
