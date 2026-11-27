"use client";

import type { MethodologyLogEntry } from "../utils/engagementActivity";
import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";

import {
  getSignedInUser,
  isSessionEnded,
  listWorkspaceEvidence,
  signInAgainPath,
  submitFieldReview,
  UploadInterruptedError,
  uploadDocumentWithProgress,
  userFacingApiError,
} from "../api/s1Backend";
import { ApiError } from "../../../lib/api";
import { isActiveRun, readFailureMessage, requestRead, type ProcessingRunView } from "../api/processingRuns";
import { useProcessingRuns } from "../hooks/useProcessingRuns";
import { useTeamDirectory } from "../hooks/useTeamDirectory";
import { createDocumentBatch } from "../api/documentBatches";
import { demoBatchAiTypeDocument, registerDemoBatch } from "../demo-backend/batches";
import { BATCH_NOT_CREATED, useBatchProgress } from "../hooks/useBatchProgress";
import { readAfterUpload, withAutoRead, withReadingState } from "../utils/readingState";
import { useAutoRead } from "../hooks/useAutoRead";
import { reviewValuesFromFields, withRequestsFromAsks } from "../adapters/reviewValueAdapter";
import {
  getRecalculation,
  getRecalculationReference,
  inScopeFieldsFrom,
  lookupEgridZip,
  type DataPointOption,
  type VehicleTypeOption,
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
import type { RereadState } from "../components/EvidenceTree";
import { EvidenceWorkspace, type WorkspaceProblem } from "../components/EvidenceWorkspace";
import { S1Chrome, type NavKey, type WorkpaperUser } from "../components/S1Chrome";
import { logout } from "../../auth/api";
import { navForView } from "../utils/navForView";
import { DashboardScreen } from "../components/DashboardScreen";
import { UploadDialog, uploadTasksForItems, type SampleScript, type UploadTask } from "../components/UploadDialog";
import { expandUploads, type UploadItem } from "../utils/expandUploads";
import { ZipError } from "../utils/zipReader";
import { newUploadId, runUploadQueue } from "../utils/uploadRunner";
import type { UploadPick } from "../utils/uploadSources";
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
import { SummaryDocumentReview, WithMethodologyFacts, type MethodologyFacts } from "../components/SummaryDocumentReview";
import type { SourceAt } from "../api/methodologyReview";
import { BackendOutputScreen } from "../components/BackendOutputScreen";
import { BackendDashboard } from "../components/BackendDashboard";
import { OutputScreen } from "../components/OutputScreen";
import { coverageRules } from "../fixtures/verification/coverageRules";
import { verificationRows } from "../fixtures/verification/verificationResults";
import { seedExaminations, verificationLines } from "../fixtures/verification/resultsDataset";
import { useVerificationStore } from "../verification/verificationStore";
import { useWorkpaperSync } from "../verification/useWorkpaperSync";
import { StateIndicator } from "../components/StateIndicator";
import { AI_TYPE, EXACT_COPY } from "../constants/copy";
import { uploadProblemTitle } from "../constants/uploads";
import { engagementConfig } from "../fixtures/engagementConfig";
import { inScopeFieldPlaceholders } from "../fixtures/scope/inScopeFields";
import type { EngagementConfig, InScopeField, RecalculationSettings } from "../types";
import { manufacturerEvidence } from "../fixtures/evidence/manufacturerEvidence";
import { manufacturerValues } from "../fixtures/extraction/manufacturerValues";
import { seedAsks } from "../fixtures/requests/seedAsks";
import { makeUploadItem, classifyGuess } from "../fixtures/upload/simulateUpload";
import { resetDemoDecisions } from "../demo-backend/calcTrace/decisions";
import { loadDemoState, saveDemoState, clearDemoState, loadSignedIn, saveSignedIn, type DemoSnapshot } from "../utils/demoPersistence";
import { DemoSignIn } from "../components/DemoSignIn";
import { SessionEndedPanel } from "../components/SessionEndedPanel";
import { EngagementPicker } from "../components/EngagementPicker";
import type { SetupSaveInfo } from "../components/SetupSaveStatus";
import {
  createEngagement,
  engagementFromBackend,
  setupSavePayload,
  listEngagements,
  pickEngagement,
  rememberEngagement,
  saveEngagement,
  type BackendEngagement,
} from "../api/engagements";
import { andThen } from "../requests/maybePromise";
import { useBackendRequestsStore } from "../requests/backendRequestsStore";
import { useRequestsStore } from "../requests/requestsStore";
import type {
  ContainerState,
  DocumentDecision,
  VehicleGroupSetting,
  EvidenceItem,
  ExtractedField,
  ReviewValue,
  StateDimension,
} from "../types";
import { setAuditActor, type SessionAuditEntry } from "../utils/auditIntent";
import { useOpenEngagement } from "../utils/useOpenEngagement";
import { dashboardFigures, engagementActivity, firstValueToReview } from "../utils/engagementActivity";
import { SupportingSchedule } from "../components/SupportingSchedule";
import { withDemoGroupIds } from "../demo-backend/groupIds";
import { demoEngagement, setDemoEngagement } from "../demo-backend/state";
import { adoptGroupIds } from "../utils/vehicleGroupIds";
import {
  createEvidenceFolder,
  createEvidenceLine,
  deleteEvidenceFolder,
  deleteEvidenceLine,
  getEvidenceActivity,
  getEvidenceTree,
  placementOfDocuments,
  type EvidenceTab,
  moveEvidenceDocument,
  setDocumentFacility,
  setRereadState,
  renameEvidenceFolder,
  renameEvidenceLine,
  setDocumentFolder,
  type CalculationLine,
  type EvidenceActivityItem,
  type EvidenceLineSetting,
  type FolderAnswer,
  type LineAnswer,
  type Placement,
  type RereadChoice,
  type TreeFolder,
} from "../api/evidenceTree";
import { useViewHistory, viewLabel } from "../utils/viewHistory";
import { resultsViewForLine, scheduleViewForLine } from "./lineLinks";
import { ContainerStateSurface } from "../components/ContainerStateSurface";
import { WorkspaceStateGate } from "../components/WorkspaceStateGate";
import { ActivityDrawer } from "../components/ActivityDrawer";
import { useBackendCoverage } from "../components/useBackendCoverage";
import { testedExaminationKeys } from "../utils/verificationTable";
import { BackendMethodologyReview } from "../components/BackendMethodologyReview";
import { AssignTaskProvider } from "../../tasks/AssignTaskContext";
import { MethodologyReview } from "../components/MethodologyReview";
import { emptyMethodologyReview, methodologyStated } from "../fixtures/methodology/methodologyReview";
import type { MethodologyState } from "../types/methodology";

/** The files of the upload in progress (or just finished): the lines the Evidence banner lists,
 *  and the documents whose reads may still fail after the upload dialog has moved on. */
interface UploadBatch {
  /** One banner line per file not uploaded, by task id (a retry replaces its line). */
  notUploaded: Map<string, string>;
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
  // The demo site runs the same screens as staging; in fixture mode `lib/api.ts` answers their
  // requests from the in-browser demo backend (features/s1/demo-backend).
  const STAGING_SCREENS: boolean = dataMode === "backend" || dataMode === "fixture";
  // Demo-only: rehydrate the fixture state from localStorage once, so a refresh
  // does not wipe the walkthrough. Read a single time on mount.
  const teamDirectory = useTeamDirectory(dataMode === "backend" ? user?.orgId : null, user?.role);
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
  // Which rows of the Evidence tree are open (null: the default). Kept here so it survives a visit
  // to a document or a schedule.
  const [evidenceTreeOpen, setEvidenceTreeOpen] = useState<string[] | null>(null);
  const [evidenceGrouping, setEvidenceGrouping] = useState<"lines" | "types">("lines");
  const [evidenceFacility, setEvidenceFacility] = useState<string | null>(null);
  // Which tab of the Evidence page is selected: kept here, like the open rows, so a visit to a document comes back to it.
  const [evidenceTab, setEvidenceTab] = useState<EvidenceTab>("supporting");
  // Where each document sits (Block 1, 2 or 3), from the Evidence tree; null until it has loaded.
  const [placements, setPlacements] = useState<ReturnType<typeof placementOfDocuments> | null>(null);
  const [placementsError, setPlacementsError] = useState<string | null>(null);
  const [placementsRetry, setPlacementsRetry] = useState(0);
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
  // The batch of the upload in progress (several files dropped together): its progress table.
  const [uploadBatchId, setUploadBatchId] = useState<string | null>(null);
  const [batchCreateFailed, setBatchCreateFailed] = useState(false);
  // Folders and zips (MVP-158): what was found in them, and what is being looked through now.
  const [uploadSummary, setUploadSummary] = useState<string[]>([]);
  const [unpackNote, setUnpackNote] = useState<string | null>(null);
  const uploadItems = useRef(new Map<string, UploadItem>());
  const uploadAbort = useRef<AbortController | null>(null);
  const uploadBatchRef = useRef<string | undefined>(undefined);
  const uploadRetryIds = useRef(new Set<string>());
  const uploadClientIds = useRef(new Map<string, string>());
  /** The engagement the upload in progress belongs to, fixed when it starts. */
  const uploadEngagementId = useRef<string>("");
  const activeEngagementId = useRef("");
  const unmounted = useRef(false);
  const uploadRunning = useRef(false);
  const [uploadNotice, setUploadNotice] = useState<string | null>(null);
  // Backend mode: every extracted field (facts about each document) and the reviewer's
  // saved decisions per document, laid over the machine's view of the evidence.
  const [workspaceFields, setWorkspaceFields] = useState<ExtractedField[]>([]);
  const [documentDecisions, setDocumentDecisions] = useState<Record<string, DocumentDecision>>({});
  const decisionsRef = useRef(documentDecisions);
  useEffect(() => {
    decisionsRef.current = documentDecisions;
  });
  const [gridRegions, setGridRegions] = useState<{ code: string; name: string }[] | undefined>(undefined);
  const [dataPoints, setDataPoints] = useState<DataPointOption[]>([]);
  // The fuels and vehicle types a vehicle group is chosen from (Setup, backend mode).
  const [vehicleReference, setVehicleReference] = useState<{ fuels: string[]; types: VehicleTypeOption[] } | undefined>(undefined);
  const [backendError, setBackendError] = useState<WorkspaceProblem | null>(null);
  // Backend mode: a 401 from the API means the session ended (FE-007).
  const [sessionEnded, setSessionEnded] = useState(false);
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

  // In-app screens are mirrored into browser history, scoped to the engagement (see
  // utils/viewHistory.ts), so Back and Forward step through them. `setActiveView` pushes an entry;
  // `goBack` returns to the screen the user came from, and `backLabel` names it.
  const history = useViewHistory(engagement.engagementId);
  const { view: activeView, navigate: setActiveView, previous: previousView } = history;
  const goBack = history.back;
  const backLabel = previousView ? viewLabel(previousView) : "evidence";

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
        setVehicleReference(ref.vehicle_types ? { fuels: ref.mobile_fuels, types: ref.vehicle_types } : undefined);
      })
      .catch(() => undefined); // the picker simply stays hidden
    return () => {
      live = false;
    };
  }, [dataMode]);

  // Requests: the demo keeps them in the browser; with the backend every change goes to the server's
  // request actions and the screens show what it answers. Both hooks run (hooks cannot be skipped);
  // only the one for this mode is used.
  const fixtureRequests = useRequestsStore(dataMode === "backend" ? [] : persisted?.asks ?? seedAsks);
  const backendRequests = useBackendRequestsStore({
    engagementId: engagement.engagementId,
    onSessionEnded: handleSessionEnded,
  });
  const requests = dataMode === "backend" ? backendRequests : fixtureRequests;

  // Findings and examination states are saved per engagement (backend mode). Requests are not:
  // the server's request actions keep them.
  const workpaper = useWorkpaperSync({
    enabled: dataMode === "backend",
    engagementId: engagement.engagementId,
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
  const [setupSave, setSetupSave] = useState<Omit<SetupSaveInfo, "onSaveNow">>({
    state: "idle",
    savedAt: null,
    problems: {},
    message: null,
  });
  /** The last Setup save that failed, kept so Retry sends it again. */
  const failedSave = useRef<EngagementConfig | null>(null);
  /** The engagements as last loaded or saved, for a save that holds one section back (read from a timer). */
  const engagementRows = useRef<BackendEngagement[] | null>(null);
  useEffect(() => {
    engagementRows.current = engagements;
  }, [engagements]);
  // An upload never carries on into another engagement or after the app is left: a change of
  // engagement (or leaving) stops it, and what it was showing is cleared.
  useEffect(() => {
    const previous = activeEngagementId.current;
    activeEngagementId.current = engagement.engagementId;
    if (previous !== engagement.engagementId && uploadRunning.current) {
      uploadAbort.current?.abort();
      uploadRunning.current = false;
      setIsUploading(false);
      setUnpackNote(null);
      setUploadTasks([]);
      setUploadSummary([]);
      setUploadNotice(null);
    }
  }, [engagement.engagementId]);
  useEffect(() => {
    unmounted.current = false;
    return () => {
      unmounted.current = true;
      uploadAbort.current?.abort();
    };
  }, []);
  // Closing the tab or reloading mid-upload asks first: files not yet sent would be lost.
  useEffect(() => {
    if (!isUploading) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [isUploading]);
  const saveTimer = useRef<number | null>(null);
  const [inScopeFields, setInScopeFields] = useState<InScopeField[]>(
    persisted?.inScopeFields ?? (dataMode === "fixture" ? inScopeFieldPlaceholders : [])
  );
  // Methodology review (demo): the verifier's acceptances and changes to the stated methodology.
  const [methodology, setMethodology] = useState<MethodologyState>(() => persisted?.methodology ?? emptyMethodologyReview());
  // Backend mode: the methodology decisions' history, for the activity log.
  const [methodologyActivity, setMethodologyActivity] = useState<MethodologyLogEntry[]>([]);

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
    resetDemoDecisions();
    if (typeof window !== "undefined") window.location.reload();
  }

  // The scripted "upload one invoice" beat: add the prepared doc + values, play
  // the analysis progress, then open Extraction Review with the highlight.
  const [sampleScript, setSampleScript] = useState<SampleScript | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [activityOpen, setActivityOpen] = useState(false);
  const [evidenceEvents, setEvidenceEvents] = useState<EvidenceActivityItem[]>([]);
  const [evidenceOlder, setEvidenceOlder] = useState<string | null>(null);
  // Entries kept only in this session carry the signed-in person's name, never a placeholder person.
  useEffect(() => {
    const login = engagement.signedInLogin ?? (dataMode === "backend" ? user?.email : undefined) ?? "";
    const name = engagement.signedInName ?? (dataMode === "backend" ? user?.firstName ?? user?.email : DEMO_ACTOR) ?? "";
    setAuditActor({ id: login, name });
  }, [engagement.signedInLogin, engagement.signedInName, user, dataMode]);
  // The engagement that is open now, for answers that arrive after the user switched (they are dropped).
  const stillOpen = useOpenEngagement(engagement.engagementId);
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
        const picked =
          items.find((item) => item.id === history.requestedEngagement) ?? pickEngagement(items);
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
    setAutoReadNudge((n) => n + 1);
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
  const uploadBatch = useRef<UploadBatch>({ notUploaded: new Map(), notRead: [], names: new Map() });
  // Reads a reviewer asked for (setting a document's type), by run id, with the banner title to
  // use if one fails after the request has answered.
  const rereadRuns = useRef(new Map<string, string>());
  // Re-reads a move onto a line of another type asked for, by document id (shown on the document's row).
  const [rereads, setRereads] = useState<Record<string, RereadState>>({});
  const [autoReadNudge, setAutoReadNudge] = useState(0); // bumped when documents change, so the automatic read's status is looked at
  const movedRereads = useRef(new Set<string>()); // documents whose read a move asked for, until it is reported


  /** The Evidence banner for an upload batch: the files that weren't uploaded or weren't read.
   *  `refreshBackendWorkspace` clears the banner as it starts, so this is set after a refresh. */
  function showUploadProblems(batch: UploadBatch) {
    const notUploaded = Array.from(batch.notUploaded.values());
    if (notUploaded.length === 0 && batch.notRead.length === 0) return;
    const lines = [...notUploaded, ...batch.notRead];
    const shown = lines.slice(0, 5);
    setBackendError({
      title: uploadProblemTitle(notUploaded.length, batch.notRead.length),
      message:
        shown.join(" ") + (lines.length > shown.length ? ` And ${lines.length - shown.length} more are listed in the upload pop-up.` : ""),
    });
  }

  /** Reads that were queued have finished: settle the upload dialog's rows, load what the reads
   *  produced once, then tell what failed. */
  function handleReadsFinished(runs: ProcessingRunView[]) {
    setAutoReadNudge((n) => n + 1); // a summary document that just finished reading starts the automatic read
    const batch = uploadBatch.current;
    let problem: WorkspaceProblem | null = null;
    for (const run of runs) {
      const rereadTitle = rereadRuns.current.get(run.run_id);
      if (rereadTitle !== undefined) {
        rereadRuns.current.delete(run.run_id);
        if (run.status === "failed") problem = { title: rereadTitle, message: readFailureMessage(run) };
        if (movedRereads.current.has(run.document_id) && dataMode === "backend") {
          const finished = run.status === "failed" ? "failed" : "done";
          void setRereadState(engagement.engagementId, run.document_id, finished, finished === "failed" ? readFailureMessage(run) : undefined).catch(() => undefined);
          movedRereads.current.delete(run.document_id);
        }
        setRereads((cur) => {
          const shown = cur[run.document_id];
          if (!shown) return cur;
          if (run.status === "failed") return { ...cur, [run.document_id]: { ...shown, status: "failed", message: readFailureMessage(run) } };
          const { [run.document_id]: _done, ...rest } = cur;
          void _done;
          return rest;
        });
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

  // Sustentra's AI reads a summary document by itself after its upload: its rows say "Reading…" meanwhile.
  const autoRead = useAutoRead({ enabled: dataMode === "backend", engagementId: engagement.engagementId, nudge: autoReadNudge });

  const batchProgress = useBatchProgress({
    enabled: dataMode === "backend" || dataMode === "fixture",
    engagementId: engagement.engagementId,
    batchId: uploadBatchId,
    uploading: isUploading,
    onError: handleSessionEnded,
  });

  function selectEngagement(id: string) {
    const row = engagements?.find((item) => item.id === id);
    if (!row) return;
    stillOpen.markOpen(row.id); // answers for the engagement just left are stale from this moment
    flushEngagementSave();
    setEngagement(engagementFromBackend(row));
    setEvidenceEvents([]);
    setEvidenceOlder(null);
    setEvidenceFacility(null);
    setEvidenceTab("supporting");
    setPlacements(null);
    setPlacementsError(null);
    setEvidenceTreeOpen(null);
    rememberEngagement(row.id);
    setSetupSave({ state: "idle", savedAt: null, problems: {}, message: null });
    failedSave.current = null;
    // Nothing of the engagement just left may show while the new one loads.
    setEvidenceItems([]);
    setWorkspaceFields([]);
    setReviewValues([]);
    setDemoState("loading");
    void refreshBackendWorkspace(undefined, row.id);
  }

  async function createAndSelectEngagement(name: string) {
    try {
      const row = await createEngagement(name);
      setEngagements((current) => [row, ...(current ?? [])]);
      stillOpen.markOpen(row.id);
      flushEngagementSave();
      setEngagement(engagementFromBackend(row));
      setEvidenceEvents([]);
      setEvidenceOlder(null);
      rememberEngagement(row.id);
      setSetupSave({ state: "idle", savedAt: null, problems: {}, message: null });
      failedSave.current = null;
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

  /** "Save changes" and Retry: saves what is waiting, or what last failed; with neither, everything is already saved. */
  function saveSetupNow() {
    const waiting = pendingSave.current ?? failedSave.current;
    if (waiting) {
      pendingSave.current = null;
      if (saveTimer.current !== null) window.clearTimeout(saveTimer.current);
      saveTimer.current = null;
      void persistEngagement(waiting);
    } else {
      setSetupSave((current) => ({ ...current, state: "saved", savedAt: new Date(), message: null }));
    }
  }

  async function persistEngagement(config: EngagementConfig) {
    // Each section saves on its own: one that cannot be saved yet keeps its last saved value in this save, and the
    // rest go through. (The vehicle groups hold themselves back in SetupVehicleGroups.)
    const { payload, problems } = setupSavePayload(config, savedConfigOf(config.engagementId));
    setSetupSave((current) => ({ ...current, state: "saving", problems, message: null }));
    try {
      const row = await saveEngagement(payload);
      failedSave.current = null;
      setEngagements((current) => (current ?? []).map((item) => (item.id === row.id ? row : item)));
      adoptSavedGroups(row);
      setSetupSave({ state: "saved", savedAt: new Date(), problems, message: null });
    } catch (error) {
      if (handleSessionEnded(error)) return;
      failedSave.current = config;
      setSetupSave({
        state: "error",
        savedAt: null,
        problems: {},
        message:
          error instanceof ApiError && error.status === 403
            ? "Your role can view this engagement but not change it."
            : userFacingApiError(error),
      });
    }
  }

  /** The engagement as the server last had it, or null if it is not in the list. */
  function savedConfigOf(engagementId: string): EngagementConfig | null {
    const row = engagementRows.current?.find((item) => item.id === engagementId);
    return row ? engagementFromBackend(row) : null;
  }

  /** Saves the recalculation inputs now, folding in any Setup edit still waiting to save. */
  async function saveRecalculationInputs(recalculation: RecalculationSettings) {
    if (saveTimer.current !== null) window.clearTimeout(saveTimer.current);
    saveTimer.current = null;
    const base = pendingSave.current ?? engagement;
    pendingSave.current = null;
    const requested = { ...base, recalculation };
    if (dataMode === "fixture") {
      const next = withDemoGroupIds(requested, demoEngagement());
      setDemoEngagement(next);
      setEngagement(next);
      return;
    }
    const next = requested;
    const row = await saveEngagement(next);
    setEngagements((current) => (current ?? []).map((item) => (item.id === row.id ? row : item)));
    setEngagement(next);
    adoptSavedGroups(row);
  }

  /** The server gives every vehicle group an id when it is first saved. Take the ids of the groups added since
   *  the last save, here and in a Setup save still waiting, so the next save sends them back. */
  function adoptSavedGroups(row: BackendEngagement) {
    if (!stillOpen(row.id)) return;
    const recalculation = (row.settings?.recalculation ?? {}) as { vehicle_groups?: VehicleGroupSetting[] };
    setEngagement((current) => adoptGroupIds(current, recalculation.vehicle_groups));
    if (pendingSave.current) pendingSave.current = adoptGroupIds(pendingSave.current, recalculation.vehicle_groups);
  }

  /** Takes the reviewer lines the server answered with. The server owns them: the page, the list of
   *  engagements and a Setup save still waiting all carry the same list. An answer for an engagement that
   *  is no longer the open one is dropped (the user switched while the request ran). */
  function adoptLines(engagementId: string, answer: LineAnswer) {
    if (!stillOpen(engagementId)) return;
    const evidenceLines = answer.evidenceLines;
    setEngagement((current) => ({ ...current, evidenceLines }));
    if (pendingSave.current) pendingSave.current = { ...pendingSave.current, evidenceLines };
    setEngagements((current) =>
      (current ?? []).map((item) => (item.id === engagementId ? { ...item, settings: { ...item.settings, evidenceLines } } : item))
    );
    void refreshEvidenceActivity(engagementId);
  }

  /** Evidence line actions: each one is a request of its own, recorded by the server with who made it.
   *  They reject with the server's sentence (for example, a line the system already has). */
  async function createLine(entry: EvidenceLineSetting) {
    const id = engagement.engagementId;
    adoptLines(id, await createEvidenceLine(id, entry));
  }

  async function renameLine(line: CalculationLine, label: string) {
    const id = engagement.engagementId;
    adoptLines(id, await renameEvidenceLine(id, line.key, label));
  }

  async function deleteLine(line: CalculationLine): Promise<number> {
    const id = engagement.engagementId;
    const answer = await deleteEvidenceLine(id, line.key);
    adoptLines(id, answer);
    // The documents the delete moved come back whole, as saved: take them as they are (as a move does), so a
    // later save of one of them can't undo the move or carry another reviewer's older copy.
    if (stillOpen(id) && answer.documents) {
      const changed = answer.documents;
      if (dataMode === "backend") for (const [docId, decision] of Object.entries(changed)) workpaper.markSaved("document", docId, decision);
      setDocumentDecisions((cur) => ({ ...cur, ...changed }));
    }
    return answer.documents_moved ?? 0;
  }

  /** Takes the Block 1 folders the server answered with, the same way as the lines (the server owns them). */
  function adoptFolders(engagementId: string, answer: FolderAnswer) {
    if (!stillOpen(engagementId)) return;
    const evidenceFolders = answer.evidenceFolders;
    setEngagement((current) => ({ ...current, evidenceFolders }));
    if (pendingSave.current) pendingSave.current = { ...pendingSave.current, evidenceFolders };
    setEngagements((current) =>
      (current ?? []).map((item) => (item.id === engagementId ? { ...item, settings: { ...item.settings, evidenceFolders } } : item))
    );
    void refreshEvidenceActivity(engagementId);
  }

  /** The saved payloads of documents a folder action changed, taken as they are (as a move does). */
  function adoptDocuments(engagementId: string, changed: Record<string, DocumentDecision>) {
    if (!stillOpen(engagementId)) return;
    if (dataMode === "backend") for (const [docId, decision] of Object.entries(changed)) workpaper.markSaved("document", docId, decision);
    setDocumentDecisions((cur) => ({ ...cur, ...changed }));
  }

  async function createFolder(name: string) {
    const id = engagement.engagementId;
    adoptFolders(id, await createEvidenceFolder(id, name));
  }

  async function renameFolder(folder: TreeFolder, name: string) {
    const id = engagement.engagementId;
    adoptFolders(id, await renameEvidenceFolder(id, folder.folder_id, name));
  }

  async function deleteFolder(folder: TreeFolder): Promise<number> {
    const id = engagement.engagementId;
    const answer = await deleteEvidenceFolder(id, folder.folder_id);
    adoptFolders(id, answer);
    if (answer.documents) adoptDocuments(id, answer.documents);
    return answer.documents_moved ?? 0;
  }

  async function setFolderOfDocument(documentId: string, folderId: string | null) {
    const id = engagement.engagementId;
    if (dataMode === "backend") {
      if (!workpaper.loaded) throw new Error("Your saved work is still loading. Try again in a moment.");
      await workpaper.whenSaved("document", documentId);
    }
    const { payload } = await setDocumentFolder(id, documentId, folderId);
    adoptDocuments(id, { [documentId]: payload });
    void refreshEvidenceActivity(id);
  }

  /** What the server recorded on the Evidence page, newest first (the Activity log reads it): the newest page. */
  async function refreshEvidenceActivity(engagementId: string = engagement.engagementId) {
    if (!engagementId) return;
    try {
      const page = await getEvidenceActivity(engagementId);
      if (!stillOpen(engagementId)) return;
      setEvidenceEvents(page.items);
      setEvidenceOlder(page.next_cursor);
    } catch {
      // The log is a read; the Evidence page keeps working without it.
    }
  }

  async function showOlderEvidenceActivity() {
    const id = engagement.engagementId;
    if (!id || !evidenceOlder) return;
    try {
      const page = await getEvidenceActivity(id, evidenceOlder);
      if (!stillOpen(id)) return;
      setEvidenceEvents((current) => [...current, ...page.items]);
      setEvidenceOlder(page.next_cursor);
    } catch {
      // Stay on what is shown; the button is still there to try again.
    }
  }

  /** Moves one placement of a document on the server (409 when it was already moved from there). A document moved
   *  onto a line of another type is then read again as that type: the move is saved first, so if the read fails the
   *  document stays where it was put and the page says so. */
  async function moveDocumentPlacement(documentId: string, move: Placement, choice?: RereadChoice) {
    const id = engagement.engagementId;
    if (dataMode === "backend") {
      // Until the saved decisions have loaded, a move here could be judged against a stale document.
      if (!workpaper.loaded) throw new Error("Your saved work is still loading. Try again in a moment.");
      // A save of this document that is already on its way finishes first.
      await workpaper.whenSaved("document", documentId);
    }
    const { payload, reread } = await moveEvidenceDocument(id, documentId, move, choice);
    if (!stillOpen(id)) return;
    if (dataMode === "backend") workpaper.markSaved("document", documentId, payload);
    setDocumentDecisions((cur) => ({ ...cur, [documentId]: payload }));
    void refreshEvidenceActivity(id);
    if (reread && dataMode === "backend") void rereadAs(documentId, reread.canonical_type_id, reread.type_name);
  }

  /** "Place on <facility>": the reviewer takes Claude's suggestion, which is their own facility decision (audited). */
  async function placeDocumentOnFacility(documentId: string, facilityId: string) {
    const id = engagement.engagementId;
    if (dataMode === "backend") {
      if (!workpaper.loaded) throw new Error("Your saved work is still loading. Try again in a moment.");
      await workpaper.whenSaved("document", documentId);
    }
    const { payload } = await setDocumentFacility(id, documentId, facilityId, decisionsRef.current[documentId]?.facilityId ?? null);
    if (!stillOpen(id)) return;
    if (dataMode === "backend") workpaper.markSaved("document", documentId, payload);
    setDocumentDecisions((cur) => ({ ...cur, [documentId]: payload }));
    void refreshEvidenceActivity(id);
  }

  function changeEngagement(requested: EngagementConfig) {
    const next = dataMode === "fixture" ? withDemoGroupIds(requested, demoEngagement()) : requested;
    setEngagement(next);
    if (dataMode === "fixture") setDemoEngagement(next);
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

  /** A company summary document, or one opened from a methodology source, that has no extracted values: it opens with its methodology facts. */
  function isSummaryView(documentId: string, field?: string): boolean {
    if (reviewValuesView.some((v) => v.documentId === documentId)) return false;
    return Boolean(field) || inSummaryBlock(documentId);
  }

  function openExtraction(documentId: string, valueId?: string, at?: SourceAt) {
    const item = evidenceItems.find((i) => i.documentId === documentId);
    setActiveView({
      name: "extraction",
      documentId,
      mode: "snippet",
      nodeKey: item ? nodeKeyForEvidence(item) : undefined,
      valueId,
      // A methodology source: open at the cited page with its quote highlighted.
      ...(at ? { field: at.fieldId, ...(at.entry !== null ? { entry: at.entry } : {}), ...(at.page ? { page: at.page } : {}) } : {}),
    });
  }

  function uploadFiles(pick: UploadPick) {
    if (dataMode === "backend") {
      void handleUploadFiles(pick);
      return;
    }
    void handleFixtureUpload(pick);
  }

  // Fixture-mode upload: rows appear immediately, then progress as they process.
  async function handleFixtureUpload(pick: UploadPick) {
    // Folders and zips are unpacked here too; what can't be uploaded is told in the pop-up.
    const expanded = await expandUploads(pick);
    const files: File[] = [];
    const skipped: string[] = expanded.items.flatMap((item) => (item.reason && !item.open ? [`${item.path}: ${item.reason}`] : []));
    for (const item of expanded.items) {
      if (!item.open) continue;
      try {
        files.push(await item.open());
      } catch (error) {
        skipped.push(`${item.path}: ${error instanceof ZipError ? error.message : "Couldn't be unpacked."}`);
      }
    }
    setUploadSummary([
      ...expanded.summaries,
      ...skipped.slice(0, 5),
      ...(skipped.length > 5 ? [`And ${skipped.length - 5} more can't be read.`] : []),
    ]);
    const created = files.map((file) => makeUploadItem(file));
    if (created.length === 0) return;
    setEvidenceItems((cur) => [...created, ...cur]);
    setSessionUploads((cur) => [...created.map((c) => c.documentId), ...cur]);
    const patch = (id: string, next: Partial<EvidenceItem>) =>
      setEvidenceItems((cur) => cur.map((x) => (x.documentId === id ? { ...x, ...next } : x)));
    // Several files dropped together are one batch with a progress table, as on staging; the demo
    // backend scripts its reading over these files. A single file has no batch.
    const batchFiles = created.map((item) => ({ documentId: item.documentId, fileName: item.filename }));
    const aiTyped = created.length > 1 ? demoBatchAiTypeDocument(batchFiles) : null;
    setUploadBatchId(null);
    setBatchCreateFailed(false);
    if (created.length > 1) {
      createDocumentBatch(engagement.engagementId)
        .then((batchId) => {
          registerDemoBatch(batchId, batchFiles);
          setUploadBatchId(batchId);
        })
        .catch(() => setBatchCreateFailed(true));
    }
    created.forEach((item, i) => {
      window.setTimeout(() => patch(item.documentId, { processingState: "ingested" }), 700 + i * 140);
      window.setTimeout(() => {
        patch(item.documentId, classifyGuess(item.filename, engagement));
        // The type Claude suggested waits for a reviewer to confirm it.
        if (item.documentId === aiTyped)
          patch(item.documentId, { typeReviewBand: "needs_review", typeReviewReason: AI_TYPE.suggested, typeConfirmed: false });
      }, 1600 + i * 180);
    });
  }

  // A document the URL or history names that this engagement doesn't have (any longer): open
  // Evidence with a plain notice, never a blank page. Checked once the workspace has loaded.
  const workspaceLoaded = dataMode !== "backend" || (demoState !== "loading" && !!engagement.engagementId);
  useEffect(() => {
    if (activeView.name !== "extraction" || !workspaceLoaded) return;
    if (evidenceItems.some((i) => i.documentId === activeView.documentId)) return;
    history.replaceView({ name: "evidence" });
    queueMicrotask(() =>
      setBackendError({ title: "Couldn't open that document", message: "That document is no longer in this engagement." })
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeView, workspaceLoaded, evidenceItems]);

  // Screens that read the engagement's documents wait for them: loading while they are fetched, a
  // plain error if the fetch failed, and only then the screen (which may truly have 0 documents).
  const workspaceStatus: "loading" | "failed" | "ready" =
    dataMode !== "backend"
      ? "ready"
      : demoState === "loading"
        ? "loading"
        : demoState === "error_degraded" && evidenceItems.length === 0
          ? "failed"
          : "ready";
  const retryWorkspace = () => {
    if (!engagement.engagementId) {
      window.location.reload();
      return;
    }
    setDemoState("loading");
    void refreshBackendWorkspace();
  };
  // The schedule is asked for under the engagement's id, which a reload only learns once the
  // engagement has loaded: asking sooner is answered 404 and would send the reader to Evidence.
  const waitsForWorkspace =
    activeView.name === "schedule" ||
    activeView.name === "dashboard" ||
    activeView.name === "evidence" ||
    activeView.name === "requests" ||
    activeView.name === "coverage" ||
    activeView.name === "results" ||
    activeView.name === "output";

  const navCurrent: NavKey = navForView(activeView);
  const uploadSetupWarning = setupGapWarning(engagement);
  /** The dashboard's "values waiting for review": the review, at the first such value (Evidence if none are loaded). */
  function openFirstReview(documentIds?: string[]) {
    const next = firstValueToReview(reviewValuesView, documentIds);
    if (next) openExtraction(next.documentId, next.valueId);
    else setActiveView({ name: "evidence" });
  }

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
    return requests.saveAsk({
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
  async function rereadAs(documentId: string, typeId: string, typeName?: string) {
    const title = "Couldn't read the document as that type";
    // A move onto a line of another type shows "Re-reading as <type>…" on the document's row until the read ends.
    const showOnRow = (state: RereadState | null) =>
      setRereads((cur) => {
        const { [documentId]: _gone, ...rest } = cur;
        void _gone;
        return state ? { ...rest, [documentId]: state } : rest;
      });
    const engagementId = engagement.engagementId;
    // The server keeps what became of the read, so the wait and a failure survive a reload (best effort: the
    // row already shows it, and a document that was not moved by a re-read has nothing to keep).
    const keep = (state: "pending" | "failed" | "done", message?: string) => {
      if (typeName) movedRereads.current.add(documentId);
      if (dataMode === "backend" && movedRereads.current.has(documentId)) {
        void setRereadState(engagementId, documentId, state, message).catch(() => undefined);
        if (state === "done" || state === "failed") movedRereads.current.delete(documentId);
      }
    };
    if (typeName) {
      showOnRow({ typeId, typeName, status: "reading" });
      keep("pending");
    }
    const failed = (message: string) => {
      if (typeName) showOnRow({ typeId, typeName, status: "failed", message });
      keep("failed", message);
    };
    try {
      const run = await requestRead(documentId, typeId);
      if (isActiveRun(run)) {
        rereadRuns.current.set(run.run_id, title);
        reads.track(run);
        return;
      }
      await refreshBackendWorkspace("populated");
      if (run.status === "failed") {
        failed(readFailureMessage(run));
        setBackendError({ title, message: readFailureMessage(run) });
      } else {
        showOnRow(null);
        keep("done");
      }
    } catch (error) {
      if (handleSessionEnded(error)) return;
      failed(userFacingApiError(error));
      setBackendError({ title, message: userFacingApiError(error) });
    }
  }

  /** Sends the given tasks one at a time (utils/uploadRunner.ts has the rules: one upload id per row so a
   *  retry never makes a second document, Cancel, and never sending into another engagement). */
  async function runUploads(
    engagementId: string,
    taskIds: string[],
    batch: UploadBatch,
    batchId: string | undefined,
    signal: AbortSignal
  ) {
    const patchTask = (id: string, next: Partial<UploadTask>) =>
      setUploadTasks((current) => current.map((task) => (task.id === id ? { ...task, ...next } : task)));
    return runUploadQueue(taskIds, {
      engagementId,
      isCurrent: () => activeEngagementId.current === engagementId && !unmounted.current,
      signal,
      batchId,
      items: uploadItems.current,
      clientIds: uploadClientIds.current,
      patch: patchTask,
      upload: uploadDocumentWithProgress,
      retryAfter: (error) => {
        const busy = error instanceof ApiError && [429, 502, 503, 504].includes(error.status);
        return {
          retry: busy || error instanceof UploadInterruptedError,
          seconds: error instanceof ApiError ? error.retryAfter : null,
        };
      },
      describe: userFacingApiError,
      onSessionEnded: (error) => {
        if (!handleSessionEnded(error)) return false;
        setIsUploading(false);
        return true;
      },
      onNotUploaded: (taskId, item, reason, retryable) => {
        patchTask(taskId, { stage: "not_uploaded", progress: 0, error: reason, retryable });
        batch.notUploaded.set(taskId, reason.includes(item.name) ? reason : `${item.path}: ${reason}`);
        if (retryable) uploadRetryIds.current.add(taskId);
      },
      onStoredButFailed: (taskId, item, reason) => {
        patchTask(taskId, { stage: "failed", error: reason });
        batch.notRead.push(`${item.path}: ${reason}`);
      },
      onStored: async (uploaded, file, item, taskId) => {
        batch.names.set(uploaded.document_id, item.path);
        patchTask(taskId, { stage: "reading", progress: 1, documentId: uploaded.document_id });
        setEvidenceItems((current) => [
          {
            documentId: uploaded.document_id,
            filename: uploaded.file_name,
            downloadUrl: undefined,
            format: file.name.toLowerCase().endsWith(".pdf") ? "pdf" : "other",
            uploadedBy: { id: uploaded.uploaded_by, name: uploaded.uploaded_by, actorType: "preparer" },
            uploadedAt: uploaded.uploaded_at,
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
          ...current.filter((existing) => existing.documentId !== uploaded.document_id),
        ]);
        setDemoState("populated");
        // Queued, the read is only started: the runs hook follows it and the next file goes up. Inline,
        // this waits for the read itself. A document the server already had (a retried upload) comes
        // with its read, so no second read is asked for.
        const start = await readAfterUpload(uploaded);
        if (start.kind === "reading") {
          reads.track(start.run);
        } else if (start.kind === "done") {
          patchTask(taskId, { stage: "done" });
        } else {
          patchTask(taskId, { stage: "failed", error: start.reason });
          batch.notRead.push(`${item.path}: ${start.reason}`);
        }
      },
    });
  }

  async function handleUploadFiles(pick: UploadPick) {
    if (dataMode !== "backend") return;
    if (!engagement.engagementId) {
      setBackendError({ title: "Couldn't upload", message: "Create or pick an engagement in Setup before uploading." });
      return;
    }
    if (pick.sources.length === 0 && pick.refused.length === 0) return;
    if (uploadRunning.current) {
      // One upload at a time: a second pick would reset the list under the one in progress.
      setUploadNotice("Another upload is still running. Wait for it to finish, or cancel it, then add these again.");
      return;
    }
    uploadRunning.current = true;
    setUploadNotice(null);
    const engagementId = engagement.engagementId; // fixed for this whole upload
    uploadEngagementId.current = engagementId;
    const controller = new AbortController();
    uploadAbort.current = controller;
    setIsUploading(true);
    setBackendError(null);
    setUploadTasks([]);
    setUploadSummary([]);
    setUnpackNote("Looking through what you added…");
    let expanded;
    try {
      expanded = await expandUploads(pick, { signal: controller.signal, onProgress: setUnpackNote });
    } catch {
      setUnpackNote(null);
      setIsUploading(false);
      uploadRunning.current = false;
      setBackendError({ title: "Couldn't upload", message: "Couldn't look through what you added. Try again." });
      return;
    }
    setUnpackNote(null);
    if (controller.signal.aborted) {
      setIsUploading(false);
      uploadRunning.current = false;
      return;
    }
    setUploadSummary(expanded.summaries);
    // A file no parser can read is set aside as not uploaded and never sent.
    const tasks = uploadTasksForItems(expanded.items, Date.now().toString(36));
    uploadItems.current = new Map(tasks.map((task, index) => [task.id, expanded.items[index]]));
    uploadClientIds.current = new Map(tasks.map((task) => [task.id, newUploadId()]));
    uploadRetryIds.current = new Set();
    setUploadTasks(tasks);
    // One line per file for the Evidence banner: not uploaded, then uploaded but not read. Reads
    // that fail after the upload has moved on (queued reads) are added by handleReadsFinished.
    const batch: UploadBatch = {
      notUploaded: new Map(
        tasks.flatMap((task) =>
          task.stage === "not_uploaded" && task.error
            ? [[task.id, task.error.includes(task.filename) ? task.error : `${task.path ?? task.filename}: ${task.error}`] as [string, string]]
            : []
        )
      ),
      notRead: [],
      names: new Map(),
    };
    uploadBatch.current = batch;
    const waiting = tasks.filter((task) => task.stage === "waiting").map((task) => task.id);
    // Several files at once are one batch with one progress table. A batch that can't be made
    // is not worth stopping the upload for: the files go up without one.
    let batchId: string | undefined;
    setUploadBatchId(null);
    setBatchCreateFailed(false);
    if (waiting.length > 1) {
      try {
        batchId = await createDocumentBatch(engagement.engagementId);
        setUploadBatchId(batchId);
      } catch (error) {
        if (handleSessionEnded(error)) {
          setIsUploading(false);
          uploadRunning.current = false;
          return;
        }
        setBatchCreateFailed(true);
      }
    }
    uploadBatchRef.current = batchId;
    const outcome = await runUploads(engagementId, waiting, batch, batchId, controller.signal);
    finishUpload(engagementId, outcome, waiting.length > 0, batch);
  }

  /** The end of a run: refresh and report only if the person is still in the engagement it belonged to. */
  async function finishUpload(engagementId: string, outcome: "finished" | "ended", sent: boolean, batch: UploadBatch) {
    const stillHere = activeEngagementId.current === engagementId && !unmounted.current;
    if (outcome === "ended" || !stillHere) {
      if (stillHere) setIsUploading(false);
      uploadRunning.current = false;
      return;
    }
    if (sent) await refreshBackendWorkspace("populated");
    showUploadProblems(batch);
    setIsUploading(false);
    uploadRunning.current = false;
  }

  /** Stops looking through folders and zips, and stops sending the files not yet sent. */
  function cancelUpload() {
    uploadAbort.current?.abort();
  }

  /** Sends again only the files that failed because of a hiccup. */
  async function retryFailedUploads() {
    const ids = Array.from(uploadRetryIds.current);
    const engagementId = uploadEngagementId.current;
    if (ids.length === 0 || uploadRunning.current || engagementId !== activeEngagementId.current) return;
    uploadRunning.current = true;
    uploadRetryIds.current = new Set();
    const controller = new AbortController();
    uploadAbort.current = controller;
    const batch = uploadBatch.current;
    for (const id of ids) batch.notUploaded.delete(id);
    setUploadTasks((current) =>
      current.map((task) => (ids.includes(task.id) ? { ...task, stage: "waiting", progress: 0, error: undefined, retryable: false } : task))
    );
    setIsUploading(true);
    setBackendError(null);
    const outcome = await runUploads(engagementId, ids, batch, uploadBatchRef.current, controller.signal);
    await finishUpload(engagementId, outcome, true, batch);
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
        ? withAutoRead(
            withReadingState(applyDocumentView(evidenceItems, facts, documentDecisions, engagement.facilities, engagement.clientName), reads.runs),
            autoRead
          )
        : evidenceItems,
    [dataMode, evidenceItems, facts, documentDecisions, engagement.facilities, engagement.clientName, reads.runs, autoRead]
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
  // Where each document sits, read from the Evidence tree (never filtered), again when the documents, a
  // placement or a read changes. Backend mode only. A failed read is shown, with a way to retry; the review
  // screen waits for it and never guesses from the document's type.
  useEffect(() => {
    if (dataMode !== "backend" || !engagement.engagementId) return;
    let live = true;
    getEvidenceTree(engagement.engagementId)
      .then((tree) => {
        if (!live) return;
        setPlacements(placementOfDocuments(tree));
        setPlacementsError(null);
      })
      .catch((error: unknown) => {
        if (!live || handleSessionEnded(error)) return;
        setPlacementsError(userFacingApiError(error));
      });
    return () => {
      live = false;
    };
    // handleSessionEnded changes every render; the placements load when these change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataMode, engagement.engagementId, evidenceSignature, documentDecisions, workspaceFields, placementsRetry]);
  const placementsReady = placements !== null && placementsError === null;

  /** Block 1 is decided by where a document sits, never by its type: reference documents carry no values to accept. */
  function inSummaryBlock(documentId: string): boolean {
    return placements?.get(documentId) === "summary";
  }

  // A document opened from a link, a dashboard or after a reload lands on the tab that holds it.
  const tabSyncedFor = useRef<string | null>(null);
  useEffect(() => {
    if (activeView.name !== "extraction") {
      tabSyncedFor.current = null;
      return;
    }
    const where = placements?.get(activeView.documentId);
    if (!where || tabSyncedFor.current === activeView.documentId) return;
    tabSyncedFor.current = activeView.documentId;
    if (where === "summary" || where === "supporting") setEvidenceTab(where); // Block 2 shows on both tabs: stay
  }, [activeView, placements]);

  const reviewValuesView = useMemo(() => {
    // A card's latest request decides whether it is requested, in the session and after a reload.
    // Block 1 documents are reference only: none of their values is offered for review or counted.
    const settled = withRequestsFromAsks(reviewValues, requests.asks).filter((v) => placements?.get(v.documentId) !== "summary");
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
  }, [dataMode, reviewValues, evidenceView, requests.asks, placements]);
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
                    evidenceEvents,
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
    [dataMode, engagement, evidenceView, reviewValuesView, requests.asks, verification.examinations, verification.findings, auditIntents, evidenceEvents, methodology.log]
  );
  const foundFacilities = useMemo(
    () => (dataMode === "backend" ? unmatchedFacilities(facts, engagement.facilities, engagement.clientName) : []),
    [dataMode, facts, engagement.facilities, engagement.clientName]
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
      <AssignTaskProvider
        orgId={dataMode === "backend" ? (user?.orgId ?? null) : null}
        engagementId={engagement.engagementId || null}
      >
      <S1Chrome
        engagement={engagement}
        engagementLoading={dataMode === "backend" && !engagement.engagementId && demoState === "loading"}
        user={dataMode === "backend" ? user : undefined}
        onSignOut={dataMode === "backend" && user ? () => void signOut() : undefined}
        current={navCurrent}
        onNavigate={onNavigate}
        onReset={dataMode === "fixture" ? resetDemo : undefined}
        onOpenActivity={() => {
          setActivityOpen(true);
          void refreshEvidenceActivity();
        }}
        assistant={assistantData ? { data: assistantData, onOpenDocument: openExtraction, onNavigate } : undefined}
        onOpenGlossary={() =>
          setActiveView((current) =>
            current.name === "glossary" ? current : { name: "glossary", previous: current }
          )
        }
      >
        {waitsForWorkspace && workspaceStatus !== "ready" ? (
          <WorkspaceStateGate status={workspaceStatus} problem={backendError} onRetry={retryWorkspace} />
        ) : activeView.name === "dashboard" ? (
          STAGING_SCREENS ? (
            <BackendDashboard
              methodologyKey={methodologyActivity.map((a) => `${a.at}${a.what}`).join("|")}
              engagement={engagement}
              evidence={evidenceView}
              values={reviewValuesView}
              asks={requests.asks}
              findings={verification.findings}
              examinations={verification.examinations}
              onNavigate={onNavigate}
              onOpenReview={() => openFirstReview()}
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
              onOpenReview={() => openFirstReview()}
            />
          )
        ) : activeView.name === "setup" ? (
          <SetupScreen
            engagement={engagement}
            onChange={changeEngagement}
            teamDirectory={teamDirectory}
            save={dataMode === "backend" && engagement.engagementId ? { ...setupSave, onSaveNow: saveSetupNow } : undefined}
            picker={
              dataMode === "backend" && engagements !== null ? (
                <EngagementPicker
                  engagements={engagements.map((e) => ({ id: e.id, name: e.name, clientName: e.client_name }))}
                  selectedId={engagement.engagementId}
                  onSelect={selectEngagement}
                  onCreate={createAndSelectEngagement}
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
            vehicleReference={dataMode === "backend" ? vehicleReference : undefined}
            lookupZip={dataMode === "backend" ? lookupEgridZip : undefined}
            foundFacilities={foundFacilities}
          />
        ) : activeView.name === "requests" || activeView.name === "coverage" ? (
          <EvidenceRequests
            engagement={engagementForUser}
            asks={requests.asks}
            coverage={dataMode === "backend" ? backendCoverage : { rules: coverageRules }}
            valuesToReview={reviewValuesView.filter((v) => !v.withdrawn && v.reviewState === "to_review").length}
            onReview={() => openFirstReview()}
            onReviewRule={(rule) => openFirstReview(rule.awaitingDocumentIds)}
            onSaveAsk={requests.saveAsk}
            onSend={(ids, lineNumbers) => andThen(requests.sendAsks(ids, lineNumbers), (sent) => sent.requestNumber)}
            onResolve={requests.resolveAsk}
            onWithdraw={requests.withdrawAsk}
            onEdit={requests.editAsk}
            onRaiseFollowUp={raiseFollowUp}
            onOpenSource={(ask) => ask.source.documentId && openExtraction(ask.source.documentId)}
            serverRecordsActor={dataMode === "backend"}
          />
        ) : activeView.name === "methodology" ? (
          STAGING_SCREENS ? (
            <BackendMethodologyReview
              engagementId={engagement.engagementId}
              onOpenDocument={(documentId, at) => openExtraction(documentId, undefined, at)}
              onError={handleSessionEnded}
              onActivity={setMethodologyActivity}
              followUp={{
                engagement: engagementForUser,
                asks: requests.asks,
                onSaveAsk: requests.saveAsk,
                onOpenRequests: () => setActiveView({ name: "requests" }),
                serverRecordsActor: dataMode === "backend",
              }}
            />
          ) : (
            <MethodologyReview
              stated={methodologyStated}
              review={methodology}
              onChange={setMethodology}
              verifier={engagement.engagementTeam?.find((m) => m.login === engagement.signedInLogin)?.name ?? DEMO_ACTOR ?? "Verifier"}
            />
          )
        ) : activeView.name === "results" ? (
          STAGING_SCREENS ? (
            <BackendVerificationResults
              engagement={engagementForUser}
              store={verification}
              onSaveInputs={saveRecalculationInputs}
              onError={handleSessionEnded}
              onOpenDocument={openExtraction}
              focusLineKey={activeView.lineKey}
              canDecide={dataMode !== "backend" || user?.role === "org_admin" || user?.role === "org_member"}
              onOpenEvidence={(key) => setActiveView(scheduleViewForLine(key))}
              onOpenEvidenceTree={() => setActiveView({ name: "evidence" })}
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
          STAGING_SCREENS ? (
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
            onOpenSetup={() => setActiveView({ name: "setup" })}
            onOpenMethodology={() => setActiveView({ name: "methodology" })}
            tree={
              STAGING_SCREENS
                ? {
                    openIds: evidenceTreeOpen,
                    view: evidenceGrouping,
                    onViewChange: setEvidenceGrouping,
                    facilityId: evidenceFacility,
                    onFacilityChange: setEvidenceFacility,
                    tab: evidenceTab,
                    onTabChange: setEvidenceTab,
                    onOpenIdsChange: setEvidenceTreeOpen,
                    onOpenSchedule: (lineKey) => setActiveView({ name: "schedule", lineKey }),
                    onMovePlacement: moveDocumentPlacement,
                    onPlaceOnFacility: placeDocumentOnFacility,
                    onCreateLine: createLine,
                    onRenameLine: renameLine,
                    onDeleteLine: deleteLine,
                    rereads,
                    onRetryReread: (documentId, typeId, typeName) => {
                      movedRereads.current.add(documentId);
                      void rereadAs(documentId, typeId, typeName);
                    },
                    onCreateFolder: createFolder,
                    onRenameFolder: renameFolder,
                    onDeleteFolder: deleteFolder,
                    onSetDocumentFolder: setFolderOfDocument,
                    onError: handleSessionEnded,
                  }
                : undefined
            }
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
            serverRecordsActor={dataMode === "backend"}
          />
        ) : activeView.name === "schedule" ? (
          <SupportingSchedule
            engagementId={engagement.engagementId}
            lineKey={activeView.lineKey}
            onBack={() => goBack({ name: "evidence" })}
            backLabel={backLabel}
            onOpenEvidence={() => setActiveView({ name: "evidence" })}
            onMissing={() => {
              history.replaceView({ name: "evidence" });
              setBackendError({ title: "Couldn't open that data point review", message: "That data point review is no longer in this engagement." });
            }}
            onOpenDocument={openExtraction}
            onOpenCalculationLine={(key) => setActiveView(resultsViewForLine(key))}
            onError={handleSessionEnded}
          />
        ) : activeView.name === "extraction" && !workspaceLoaded ? (
          // Opened from a reload or a link: wait for the workspace, then pick the value.
          <section className="s1-content">
            <ContainerStateSurface state="loading" />
          </section>
        ) : activeView.name === "extraction" && dataMode === "backend" && !placementsReady ? (
          // Whether the document is in Block 1 decides whether it has values to accept, so nothing is offered until known.
          <section className="s1-content s1-xr s1-xr--doconly">
            <button className="s1-linklike s1-backlink" type="button" onClick={() => goBack({ name: "evidence" })}>
              ‹ Back to {backLabel}
            </button>
            {placementsError ? (
              <div className="s1-system-banner" role="alert">
                <strong>Couldn&apos;t check where this document sits</strong>
                <span>{placementsError} </span>
                <button className="s1-button" type="button" onClick={() => setPlacementsRetry((n) => n + 1)}>
                  Retry
                </button>
              </div>
            ) : (
              <ContainerStateSurface state="loading" label="Loading document" />
            )}
          </section>
        ) : activeView.name === "extraction" && STAGING_SCREENS && dataMode === "backend" && isSummaryView(activeView.documentId, activeView.field) ? (
          <SummaryDocumentReview
            key={`${activeView.documentId}:${activeView.field ?? ""}:${activeView.entry ?? ""}:${activeView.page ?? ""}`}
            engagementId={engagement.engagementId}
            documentId={activeView.documentId}
            fileName={evidenceView.find((e) => e.documentId === activeView.documentId)?.filename}
            at={{ fieldId: activeView.field, entry: activeView.entry, page: activeView.page }}
            backLabel={backLabel}
            onBack={() => goBack({ name: "evidence" })}
            onError={handleSessionEnded}
            renderViewer={(viewer) => {
              const format = evidenceItems.find((e) => e.documentId === activeView.documentId)?.format;
              return format === "pdf" || format === "image" ? (
                <BackendPageView
                  key={viewer.viewerKey}
                  documentId={activeView.documentId}
                  span={viewer.span}
                  openPage={viewer.page}
                  marks={viewer.marks}
                  selectedMarkIds={viewer.selectedMarkIds}
                  pageNote={viewer.pageNote}
                  onPickMark={viewer.onPickMark}
                />
              ) : (
                <>
                  {viewer.pageNote ? <p className="s1-mb-notlocated" role="status">{viewer.pageNote}</p> : null}
                  <DocumentContentView key={activeView.documentId} documentId={activeView.documentId} marks={[]} selectedId={null} />
                </>
              );
            }}
          />
        ) : activeView.name === "extraction" ? (
          (() => {
            const review = (facts?: MethodologyFacts) => (
          <ExtractionReview
            facts={facts}
            factsDeepLinked={Boolean(activeView.field)}
            engagement={engagementForUser}
            values={reviewValuesView}
            onValuesChange={setReviewValues}
            key={`${activeView.documentId}:${activeView.valueId ?? ""}`}
            initialDocumentId={activeView.documentId}
            initialDocumentName={evidenceView.find((e) => e.documentId === activeView.documentId)?.filename}
            typeItem={evidenceView.find((e) => e.documentId === activeView.documentId)}
            inSummaryBlock={inSummaryBlock(activeView.documentId)}
            onPlaceOnFacility={placeDocumentOnFacility}
            onOpenMethodology={() => setActiveView({ name: "methodology" })}
            initialValueId={activeView.valueId}
            initialNodeKey={activeView.nodeKey}
            onSaveAsk={requests.saveAsk}
            asks={requests.asks}
            serverRecordsActor={dataMode === "backend"}
            onBack={() => goBack({ name: "evidence" })}
            backLabel={backLabel}
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
            onPersistReject={
              dataMode === "backend"
                ? async (value, reason) => {
                    try {
                      await submitFieldReview({ field: { reviewToken: value.reviewToken }, decision: "rejected", reviewerNote: reason });
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
                  key={`${documentId}:${pick?.viewerKey ?? span?.page ?? 0}`}
                  documentId={documentId}
                  span={span}
                  openPage={pick?.openPage}
                  selectedMarkIds={pick?.selectedMarkIds}
                  pageNote={pick?.pageNote}
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
            );
            // A company summary document that also has reported values: its Methodology facts are a second tab.
            return STAGING_SCREENS && dataMode === "backend" && (activeView.field || inSummaryBlock(activeView.documentId)) ? (
              <WithMethodologyFacts
                key={`${activeView.documentId}:${activeView.field ?? ""}:${activeView.entry ?? ""}:${activeView.page ?? ""}`}
                engagementId={engagement.engagementId}
                documentId={activeView.documentId}
                at={{ fieldId: activeView.field, entry: activeView.entry, page: activeView.page }}
                onError={handleSessionEnded}
              >
                {review}
              </WithMethodologyFacts>
            ) : (
              review()
            );
          })()
        ) : (
          <GlossaryPage onBack={() => goBack(activeView.previous)} />
        )}
        {uploadOpen ? (
          <UploadDialog
            setupWarning={uploadSetupWarning}
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
            summaryLines={uploadSummary}
            unpackNote={unpackNote}
            onCancelUpload={dataMode === "backend" ? cancelUpload : undefined}
            onRetryFailed={dataMode === "backend" ? () => void retryFailedUploads() : undefined}
            tasks={dataMode === "backend" ? uploadTasks : undefined}
            items={dataMode === "backend" ? evidenceItems : undefined}
            batchProgress={batchProgress.view}
            batchNote={uploadNotice ?? (batchCreateFailed ? BATCH_NOT_CREATED : batchProgress.error)}
            onOpenDocument={(documentId) => {
              setUploadOpen(false);
              openExtraction(documentId);
            }}
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
              evidenceEvents,
              methodology: dataMode === "fixture" ? methodology.log : methodologyActivity,
            })}
            hasOlder={evidenceOlder !== null}
            onShowOlder={() => void showOlderEvidenceActivity()}
            onClose={() => setActivityOpen(false)}
          />
        ) : null}
      </S1Chrome>
      </AssignTaskProvider>
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

/** Upload is never blocked, but without a period and facilities documents cannot be placed or checked against the year. */
export function setupGapWarning(config: EngagementConfig): string | null {
  const noPeriod = !config.reportingPeriod.start || !config.reportingPeriod.end;
  const noFacilities = config.facilities.length === 0;
  if (!noPeriod && !noFacilities) return null;
  const missing = noPeriod && noFacilities ? "the reporting period and facilities" : noPeriod ? "the reporting period" : "facilities";
  return `Add ${missing} first, so documents can be placed on facilities and checked against the year.`;
}
