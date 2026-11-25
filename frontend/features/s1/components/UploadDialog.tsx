"use client";

import { CloudUpload, FolderUp, X } from "lucide-react";
import { createPortal } from "react-dom";
import { memo, useEffect, useState } from "react";

import type { BatchView } from "../api/documentBatches";
import type { EvidenceItem } from "../types";
import { BatchProgress } from "./BatchProgress";
import { BreakableName } from "./BreakableName";
import {
  isReadableUpload,
  MAX_UPLOAD_FILES,
  MAX_UPLOAD_MB,
  MAX_ZIP_MB,
  unreadableUploadMessage,
  UPLOAD_PICKER_ACCEPT,
} from "../constants/uploads";
import type { UploadItem } from "../utils/expandUploads";
import { pickFromDrop, pickFromFileList, type UploadPick } from "../utils/uploadSources";


/** One file in the current upload, as the user picked it (backend mode). */
export interface UploadTask {
  id: string;
  filename: string;
  /** Where it came from, when that is more than its name: "Plant A/2025/jan.pdf". */
  path?: string;
  size: number;
  /** waiting -> uploading (bytes leave the browser) -> reading (parse, classify, extract) -> done | failed.
   *  not_uploaded: the file was never stored (a type no parser reads, or the API refused it). */
  stage: "waiting" | "uploading" | "reading" | "done" | "failed" | "not_uploaded";
  /** Fraction of the file's bytes sent, 0..1 (measured, not estimated). */
  progress: number;
  error?: string;
  /** Set once the server has stored the file. */
  documentId?: string;
  /** Not uploaded because of a hiccup (busy server, dropped connection): trying again may work. */
  retryable?: boolean;
}

/** The tasks for the files found in what was picked: one row each, with the reason when it can't go. */
export function uploadTasksForItems(items: UploadItem[], batchId: string): UploadTask[] {
  return items.map((item, index) => ({
    id: `${batchId}-${index}`,
    filename: item.name,
    ...(item.path !== item.name ? { path: item.path } : {}),
    size: item.size,
    progress: 0,
    ...(item.open ? { stage: "waiting" as const } : { stage: "not_uploaded" as const, error: item.reason }),
  }));
}

/** The tasks for picked files. A file no parser can read is set aside as not uploaded,
 *  with the reason, and is never sent (the API would refuse it with a 415). */
export function uploadTasksFor(files: File[], batchId: string): UploadTask[] {
  return files.map((file, index) => ({
    id: `${batchId}-${index}`,
    filename: file.name,
    size: file.size,
    progress: 0,
    ...(isReadableUpload(file)
      ? { stage: "waiting" as const }
      : { stage: "not_uploaded" as const, error: unreadableUploadMessage(file.name) }),
  }));
}

export interface SampleScript {
  filename: string;
  stage: "uploading" | "analyzing" | "classified" | "done";
  classified?: string;
  found: string[];
  progress: number; // 0..1
}

/**
 * Upload: a small pop-up over the current screen, not a page of its own. It opens
 * from the nav or when files are dropped on Evidence. Each file shows its progress
 * as it is uploaded and read; who uploaded what, and when, goes to the activity log.
 */
export function UploadDialog({
  onClose,
  onUploadFiles,
  onUploadSample,
  sampleFilename,
  script,
  batch,
  tasks = [],
  items = [],
  batchProgress = null,
  batchNote = null,
  onOpenDocument,
  onOpenWorkspace,
  setupWarning = null,
  summaryLines = [],
  unpackNote = null,
  onCancelUpload,
  onRetryFailed,
}: {
  onClose: () => void;
  onUploadFiles: (pick: UploadPick) => void;
  /** One line per folder or zip: how many files were found and how many can't be read. */
  summaryLines?: string[];
  /** While folders and zips are being looked through: what is being looked at. */
  unpackNote?: string | null;
  /** Stops looking through folders and zips, and stops sending the files not yet sent. */
  onCancelUpload?: () => void;
  /** Sends the files that failed because of a hiccup again (only those). */
  onRetryFailed?: () => void;
  onUploadSample?: () => void;
  sampleFilename?: string;
  script?: SampleScript | null;
  /** Fixture mode: the session's uploads; only those added since the pop-up opened are listed. */
  batch: EvidenceItem[];
  /** Backend mode: the files being uploaded right now, with measured progress. */
  tasks?: UploadTask[];
  /** Backend mode: the engagement's documents, to show what reading found. */
  items?: EvidenceItem[];
  /** Backend mode: how reading the files dropped together stands, when they were uploaded as a batch. */
  batchProgress?: BatchView | null;
  /** A line about the batch: its progress could not be loaded, or it could not be made. */
  batchNote?: string | null;
  /** Open a read file's extraction review. */
  onOpenDocument?: (documentId: string) => void;
  onOpenWorkspace: () => void;
  /** A calm note above the drop zone when Setup lacks what placing documents needs. It never blocks the upload. */
  setupWarning?: string | null;
}) {
  const [drag, setDrag] = useState(false);
  const [before] = useState(() => new Set(batch.map((item) => item.documentId)));
  const added = batch.filter((item) => !before.has(item.documentId));
  const scripting = !!script && script.stage !== "done";
  const unpacking = unpackNote !== null;
  const busy = scripting || unpacking || tasks.some((t) => t.stage === "waiting" || t.stage === "uploading" || t.stage === "reading");
  const anything = added.length > 0 || tasks.length > 0;
  const notUploaded = tasks.filter((t) => t.stage === "not_uploaded").length;
  const doneHint =
    notUploaded === 0
      ? "Done. Each file is a row in Evidence."
      : notUploaded === tasks.length && added.length === 0
        ? "Nothing was uploaded."
        : "Done. Each uploaded file is a row in Evidence.";

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const pick = (files: FileList | null) => {
    if (files?.length) onUploadFiles(pickFromFileList(files));
  };
  const retryable = tasks.filter((t) => t.retryable && t.stage === "not_uploaded").length;

  return createPortal(
    <div className="s1-updlg-scrim" onPointerDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`s1-updlg${batchProgress && batchProgress.items.length > 0 ? " s1-updlg--wide" : ""}`} role="dialog" aria-modal="true" aria-labelledby="s1-updlg-title">
        <div className="s1-updlg__head">
          <h2 id="s1-updlg-title">Upload evidence</h2>
          <button className="s1-updlg__close" type="button" aria-label="Close" onClick={onClose}>
            <X aria-hidden />
          </button>
        </div>

        {setupWarning && !script ? (
          <p className="s1-updlg__warn" role="note">
            {setupWarning}
          </p>
        ) : null}

        {script ? (
          <div className="s1-analyze" aria-live="polite">
            <div className="s1-analyze__head">
              <span className="s1-analyze__fn">{script.filename}</span>
              <span className="s1-analyze__stage">{stageHeadline(script.stage)}</span>
            </div>
            <div className="s1-analyze__bar">
              <div className="s1-analyze__bar-fill" style={{ width: `${Math.round(script.progress * 100)}%` }} />
            </div>
            {script.classified ? (
              <div className="s1-analyze__classified">
                <span className="s1-state s1-state--resolved">Recognized</span> {script.classified}
              </div>
            ) : null}
            {script.found.length > 0 ? (
              <ul className="s1-analyze__found">
                {script.found.map((f) => (
                  <li key={f}>
                    <span className="s1-analyze__tick">✓</span> {f}
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : (
          <label
            className={`s1-updlg__drop${drag ? " is-drag" : ""}`}
            onDragOver={(e) => {
              e.preventDefault();
              setDrag(true);
            }}
            onDragLeave={(e) => {
              if (e.currentTarget.contains(e.relatedTarget as Node | null)) return;
              setDrag(false);
            }}
            onDrop={(e) => {
              e.preventDefault();
              setDrag(false);
              if (e.dataTransfer.files.length) void pickFromDrop(e.dataTransfer).then(onUploadFiles);
            }}
          >
            <CloudUpload className="s1-updlg__dropicon" aria-hidden />
            <span className="s1-updlg__droptext">
              <strong>Drop files or folders here</strong> or <span className="s1-updlg__browse">choose files</span>
            </span>
            <span className="s1-updlg__hint">PDF, Word, Excel, CSV, emails, scans and photos · up to {MAX_UPLOAD_MB} MB each. Zip files too (up to {MAX_ZIP_MB} MB, {MAX_UPLOAD_FILES.toLocaleString("en-US")} files).</span>
            <input
              className="s1-file-input"
              type="file"
              multiple
              accept={UPLOAD_PICKER_ACCEPT}
              onChange={(e) => {
                pick(e.target.files);
                e.target.value = "";
              }}
            />
          </label>
        )}

        {!script ? (
          <div className="s1-updlg__folder">
            <label className="s1-button">
              <FolderUp aria-hidden /> Choose a folder
              <input
                className="s1-file-input"
                type="file"
                multiple
                // @ts-expect-error webkitdirectory is not in React's input types
                webkitdirectory=""
                onChange={(e) => {
                  pick(e.target.files);
                  e.target.value = "";
                }}
              />
            </label>
          </div>
        ) : null}

        {unpackNote !== null ? (
          <div className="s1-upq__head" role="status">
            <span>{unpackNote}</span>
            {onCancelUpload ? (
              <button className="s1-linklike" type="button" onClick={onCancelUpload}>
                Cancel
              </button>
            ) : null}
          </div>
        ) : null}

        {summaryLines.length > 0 ? (
          <div className="s1-muted s1-updlg__summary" aria-live="polite">
            {summaryLines.map((line) => (
              <p key={line}>{line}</p>
            ))}
          </div>
        ) : null}

        {!script && onUploadSample && sampleFilename ? (
          <div className="s1-updlg__sample">
            <span className="s1-updlg__pdf" aria-hidden>
              PDF
            </span>
            <span className="s1-updlg__samplename">
              <span>{sampleFilename}</span>
              <span className="s1-updlg__hint">A bill from the client, ready to try</span>
            </span>
            <button className="s1-button s1-button--pri" type="button" onClick={onUploadSample}>
              Upload sample
            </button>
          </div>
        ) : null}

        {tasks.length > 0 ? (
          <UploadProgress tasks={tasks} items={items} onCancel={onCancelUpload} onRetry={retryable ? onRetryFailed : undefined} retryable={retryable} />
        ) : null}

        {batchNote ? (
          <p className="s1-muted s1-batch__notice" aria-live="polite">
            {batchNote}
          </p>
        ) : null}

        {batchProgress && batchProgress.items.length > 0 && onOpenDocument ? (
          <BatchProgress batch={batchProgress} onOpenDocument={onOpenDocument} items={items} />
        ) : null}

        {added.length > 0 && !script ? (
          <ul className="s1-updlg__list" aria-live="polite">
            {added.map((item) => {
              const stage = uploadStage(item);
              return (
                <li key={item.documentId}>
                  <span className="s1-updlg__fn">{item.filename}</span>
                  <span className={`s1-state s1-state--${stage.role}`}>{stage.label}</span>
                </li>
              );
            })}
          </ul>
        ) : null}

        {anything && !scripting ? (
          <div className="s1-updlg__foot">
            <span className="s1-updlg__hint">{busy ? "You can close this; reading carries on." : doneHint}</span>
            <button
              className="s1-button s1-button--pri"
              type="button"
              onClick={() => {
                onOpenWorkspace();
                onClose();
              }}
            >
              View in Evidence
            </button>
          </div>
        ) : null}
      </div>
    </div>,
    document.querySelector(".s1-app") ?? document.body
  );
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Overall and per-file progress. The bar is bytes actually sent; reading has no
 *  measurable progress, so it shows as an in-progress stripe, not a made-up number. */
function UploadProgress({
  tasks,
  items,
  onCancel,
  onRetry,
  retryable,
}: {
  tasks: UploadTask[];
  items: EvidenceItem[];
  onCancel?: () => void;
  onRetry?: () => void;
  retryable: number;
}) {
  const byId = new Map(items.map((item) => [item.documentId, item]));
  // A file that was not uploaded has no bytes to send, so it is left out of the bar.
  const sending = tasks.filter((t) => t.stage !== "not_uploaded");
  const totalBytes = sending.reduce((sum, t) => sum + t.size, 0);
  const sentBytes = sending.reduce(
    (sum, t) => sum + (t.stage === "waiting" ? 0 : t.stage === "uploading" ? t.size * t.progress : t.size),
    0
  );
  const percent = totalBytes ? Math.round((sentBytes / totalBytes) * 100) : 0;
  const finished = tasks.filter((t) => t.stage === "done" || t.stage === "failed" || t.stage === "not_uploaded").length;
  const failed = tasks.filter((t) => t.stage === "failed").length;
  const notUploaded = tasks.length - sending.length;
  // What reading found, once a file is done: blocked files need the reviewer (e.g. set a type).
  const outcome = (t: UploadTask) => (t.stage === "done" && t.documentId ? byId.get(t.documentId) : undefined);
  const needsYou = tasks.filter((t) => outcome(t)?.processingState === "blocked").length;
  const running = finished < tasks.length;
  const waiting = tasks.some((t) => t.stage === "waiting");

  return (
    <div className="s1-upq">
      <div className="s1-upq__head" aria-live="polite">
        <strong>
          {running
            ? `Uploading ${sending.length} file${sending.length === 1 ? "" : "s"} · ${percent}%`
            : `${tasks.length - failed - notUploaded} of ${tasks.length} file${tasks.length === 1 ? "" : "s"} uploaded and read`}
        </strong>
        <span className="s1-muted">
          {finished} of {tasks.length} done{failed ? ` · ${failed} failed` : ""}
          {notUploaded ? ` · ${notUploaded} not uploaded` : ""}
          {needsYou ? ` · ${needsYou} need${needsYou === 1 ? "s" : ""} you in Evidence` : ""}
        </span>
        {onCancel && running && waiting ? (
          <button className="s1-linklike" type="button" onClick={onCancel}>
            Cancel the rest
          </button>
        ) : null}
        {onRetry && !running ? (
          <button className="s1-linklike" type="button" onClick={onRetry}>
            Try {retryable === 1 ? "the 1 file" : `the ${retryable} files`} that didn&rsquo;t send again
          </button>
        ) : null}
      </div>
      <div
        className="s1-upq__bar"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        aria-label="Upload progress"
      >
        <div className="s1-upq__fill" style={{ width: `${percent}%` }} />
      </div>
      <ul
        className={`s1-upq__list${tasks.length > 8 ? " s1-upq__list--long" : ""}`}
        {...(tasks.length > 8 ? { tabIndex: 0, "aria-label": "Files in this upload" } : {})}
      >
        {tasks.map((t) => (
          <UploadRow key={t.id} task={t} outcome={outcome(t)} />
        ))}
      </ul>
    </div>
  );
}

/** One file's row. Memoized: a progress tick on one file must not redraw a thousand rows. */
const UploadRow = memo(function UploadRow({ task: t, outcome }: { task: UploadTask; outcome: EvidenceItem | undefined }) {
  const blocked = outcome?.processingState === "blocked";
  return (
    <li className={`s1-upq__row s1-upq__row--${t.stage}${blocked ? " s1-upq__row--needs" : ""}`}>
      <BreakableName className="s1-upq__name" name={t.path ?? t.filename} title={t.path ?? t.filename} />
      <span className="s1-muted s1-upq__size">{formatSize(t.size)}</span>
      <span className="s1-upq__track" aria-hidden>
        <span
          className={`s1-upq__track-fill${t.stage === "reading" ? " is-reading" : ""}`}
          style={{
            width: `${t.stage === "waiting" || t.stage === "not_uploaded" ? 0 : t.stage === "uploading" ? Math.round(t.progress * 100) : 100}%`,
          }}
        />
      </span>
      <span className="s1-upq__stage">
        {t.stage === "waiting"
          ? "Waiting"
          : t.stage === "uploading"
            ? `${Math.round(t.progress * 100)}%`
            : t.stage === "reading"
              ? "Reading…"
              : t.stage === "done"
                ? blocked
                  ? "Needs you"
                  : "Done"
                : t.stage === "not_uploaded"
                  ? "Not uploaded"
                  : "Failed"}
      </span>
      {t.error ? <span className="s1-upq__error">{t.error}</span> : null}
      {blocked ? (
        <span className="s1-upq__note">{outcome?.haltReason ?? "Could not be read. Choose its type in Evidence to try again."}</span>
      ) : null}
    </li>
  );
});

function stageHeadline(stage: SampleScript["stage"]): string {
  switch (stage) {
    case "uploading":
      return "Uploading…";
    case "analyzing":
    case "classified":
      return "Analyzing document…";
    case "done":
      return "Opening extraction review…";
  }
}

function uploadStage(item: EvidenceItem): { role: string; label: string } {
  if (item.processingState === "blocked") return { role: "blocking", label: "Blocked" };
  if (item.processingState === "extracted") return { role: "resolved", label: "Extracted" };
  if (item.processingState === "typed" || item.processingState === "ingested")
    return { role: "active", label: "Extracting" };
  return { role: "active", label: "Uploading" };
}
