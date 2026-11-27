"use client";

import { Check, X } from "lucide-react";

import { IconUpload } from "./icons";
import { createPortal } from "react-dom";
import { useEffect, useState } from "react";

import type { BatchView } from "../api/documentBatches";
import type { EvidenceItem } from "../types";
import { BatchProgress } from "./BatchProgress";
import { isReadableUpload, MAX_UPLOAD_MB, unreadableUploadMessage, UPLOAD_ACCEPT } from "../constants/uploads";


/** One file in the current upload, as the user picked it (backend mode). */
export interface UploadTask {
  id: string;
  filename: string;
  size: number;
  /** waiting -> uploading (bytes leave the browser) -> reading (parse, classify, extract) -> done | failed.
   *  not_uploaded: the file was never stored (a type no parser reads, or the API refused it). */
  stage: "waiting" | "uploading" | "reading" | "done" | "failed" | "not_uploaded";
  /** Fraction of the file's bytes sent, 0..1 (measured, not estimated). */
  progress: number;
  error?: string;
  /** Set once the server has stored the file. */
  documentId?: string;
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
}: {
  onClose: () => void;
  onUploadFiles: (files: FileList) => void;
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
}) {
  const [drag, setDrag] = useState(false);
  const [before] = useState(() => new Set(batch.map((item) => item.documentId)));
  const added = batch.filter((item) => !before.has(item.documentId));
  const scripting = !!script && script.stage !== "done";
  const busy = scripting || tasks.some((t) => t.stage === "waiting" || t.stage === "uploading" || t.stage === "reading");
  const anything = added.length > 0 || tasks.length > 0;
  const hasRightContent = anything || !!batchNote || (!!batchProgress && batchProgress.items.length > 0);
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
    if (files?.length) onUploadFiles(files);
  };

  return createPortal(
    <div className="s1-updlg-scrim" onPointerDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="s1-updlg" role="dialog" aria-modal="true" aria-labelledby="s1-updlg-title">
        <div className="s1-updlg__head">
          <span className="s1-updlg__icon" aria-hidden="true">
            <IconUpload size={22} aria-hidden />
          </span>
          <div className="s1-updlg__title">
            <h2 id="s1-updlg-title">Upload evidence</h2>
          </div>
          <button className="s1-updlg__close" type="button" aria-label="Close" onClick={onClose}>
            <X aria-hidden />
          </button>
        </div>

        <div className="s1-updlg__body">
          {/* Left column: drop zone or script analysis */}
          <div className="s1-updlg__left">
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
                  pick(e.dataTransfer.files);
                }}
              >
                <span className="s1-updlg__drop-icon" aria-hidden="true">
                  <IconUpload size={22} aria-hidden />
                </span>
                <strong className="s1-updlg__drophead">Drag files here</strong>
                <span className="s1-updlg__hint">Up to {MAX_UPLOAD_MB} MB per file</span>
                <span className="s1-button s1-button--pri" aria-hidden="true">Choose files</span>
                <div className="s1-updlg__chips" aria-hidden="true">
                  <span className="s1-updlg__chip s1-updlg__chip--pdf">PDF</span>
                  <span className="s1-updlg__chip s1-updlg__chip--docx">DOCX</span>
                  <span className="s1-updlg__chip s1-updlg__chip--xlsx">XLSX</span>
                  <span className="s1-updlg__chip s1-updlg__chip--csv">CSV</span>
                  <span className="s1-updlg__chip s1-updlg__chip--eml">EML</span>
                  <span className="s1-updlg__chip s1-updlg__chip--img">
                    <span className="s1-updlg__chip-dot" aria-hidden="true" />JPG / PNG
                  </span>
                </div>
                <input
                  className="s1-file-input"
                  type="file"
                  multiple
                  accept={UPLOAD_ACCEPT}
                  aria-label="Choose files to upload"
                  onChange={(e) => {
                    pick(e.target.files);
                    e.target.value = "";
                  }}
                />
              </label>
            )}

            {!script && onUploadSample && sampleFilename ? (
              <div className="s1-updlg__sample">
                <span className="s1-updlg__pdf" aria-hidden="true">PDF</span>
                <span className="s1-updlg__samplename">
                  <span>{sampleFilename}</span>
                  <span className="s1-updlg__hint">A bill from the client, ready to try</span>
                </span>
                <button className="s1-button" type="button" onClick={onUploadSample}>
                  Upload sample
                </button>
              </div>
            ) : null}
          </div>

          {/* Right column: uploads panel */}
          <div className="s1-updlg__right">
            <div className="s1-updlg__right-head">
              <span className="s1-updlg__right-title">
                Uploads{anything ? <> <span className="s1-updlg__right-count">{added.length + tasks.length}</span></> : null}
              </span>
              {batchProgress && batchProgress.items.length > 0 ? (
                <span style={{ display: "flex", gap: "var(--sp-1-5)", flexWrap: "wrap" }}>
                  {batchProgress.totals.done > 0 ? (
                    <span className="s1-state s1-state--resolved">{batchProgress.totals.done} recognized</span>
                  ) : null}
                  {batchProgress.totals.partial > 0 ? (
                    <span className="s1-state s1-state--open">{batchProgress.totals.partial} need attention</span>
                  ) : null}
                  {batchProgress.totals.failed > 0 ? (
                    <span className="s1-state s1-state--blocking">{batchProgress.totals.failed} can&apos;t be read</span>
                  ) : null}
                </span>
              ) : null}
            </div>
            <div className="s1-updlg__right-body">
              {!hasRightContent ? (
                <div className="s1-updlg__empty">
                  <div className="s1-updlg__empty-bars" aria-hidden="true">
                    <span /><span /><span />
                  </div>
                  <span className="s1-updlg__empty-text">No files yet</span>
                </div>
              ) : (
                <>
                  {tasks.length > 0 ? <UploadProgress tasks={tasks} items={items} /> : null}
                  {batchNote ? (
                    <p className="s1-muted s1-batch__notice" aria-live="polite">{batchNote}</p>
                  ) : null}
                  {batchProgress && batchProgress.items.length > 0 && onOpenDocument ? (
                    <>
                      <p className="s1-batch__section-title">Reading this batch</p>
                      <BatchProgress batch={batchProgress} onOpenDocument={onOpenDocument} />
                    </>
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
                </>
              )}
            </div>
          </div>
        </div>

        <div className="s1-updlg__foot">
          {anything && !scripting ? (
            <span className="s1-updlg__hint">{busy ? "You can close this; reading carries on." : doneHint}</span>
          ) : <span />}
          <span className="s1-updlg__foot-buttons">
            <button className="s1-button" type="button" onClick={onClose}>Close</button>
            {anything && !scripting ? (
              <button
                className="s1-button s1-button--pri"
                type="button"
                onClick={() => {
                  onOpenWorkspace();
                  onClose();
                }}
              >
                Go to Evidence
              </button>
            ) : null}
          </span>
        </div>
      </div>
    </div>,
    document.querySelector(".s1-app") ?? document.body
  );
}

/** Overall and per-file progress. The bar tracks bytes actually sent; reading has no
 *  measurable byte progress. Stage pills show Uploaded → Reading for each file. */
function UploadProgress({ tasks, items }: { tasks: UploadTask[]; items: EvidenceItem[] }) {
  const byId = new Map(items.map((item) => [item.documentId, item]));
  const doneCount = tasks.filter((t) => t.stage === "done").length;
  const notUploadedCount = tasks.filter((t) => t.stage === "not_uploaded").length;
  // A file that was not uploaded has no bytes to send, so it is left out of the overall bar.
  const sending = tasks.filter((t) => t.stage !== "not_uploaded");
  const totalBytes = sending.reduce((sum, t) => sum + t.size, 0);
  const sentBytes = sending.reduce(
    (sum, t) => sum + (t.stage === "waiting" ? 0 : t.stage === "uploading" ? t.size * t.progress : t.size),
    0
  );
  const percent = totalBytes ? Math.round((sentBytes / totalBytes) * 100) : 0;
  const outcome = (t: UploadTask) => (t.stage === "done" && t.documentId ? byId.get(t.documentId) : undefined);

  return (
    <div className="s1-upq" aria-live="polite">
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
      <ul className="s1-upq__list">
        {tasks.map((t) => {
          const ev = outcome(t);
          const blocked = ev?.processingState === "blocked";
          const ext = upqFileExt(t.filename);
          const showStages = t.stage !== "failed" && t.stage !== "not_uploaded";
          const uploadedState =
            t.stage === "waiting" ? "pending"
            : t.stage === "uploading" ? "current"
            : "done";
          const readingState =
            t.stage === "done" ? "done"
            : t.stage === "reading" ? "current"
            : "pending";
          const statusText =
            t.stage === "waiting" ? "Waiting to upload"
            : t.stage === "uploading" ? "Uploading"
            : t.stage === "reading" ? "Reading…"
            : t.stage === "done" ? (blocked ? "Needs your attention in Evidence" : "Done")
            : t.stage === "not_uploaded" ? "Not uploaded"
            : "Failed";

          return (
            <li key={t.id} className={`s1-upq__card s1-upq__card--${t.stage}`}>
              <div className="s1-upq__top">
                <span className="s1-upq__thumb" aria-hidden="true">
                  <span className={`s1-upq__tag s1-upq__tag--${ext}`}>{ext.toUpperCase()}</span>
                </span>
                <span className="s1-upq__info">
                  <span className="s1-upq__name">{t.filename}</span>
                  <span className="s1-upq__status-text">{statusText}</span>
                </span>
                {t.stage === "uploading" ? (
                  <span className="s1-upq__pct">{Math.round(t.progress * 100)}%</span>
                ) : null}
              </div>
              {t.error || blocked ? (
                <span className="s1-upq__error">
                  {blocked
                    ? (ev?.haltReason ?? "Could not be read.") + " Set its type in Evidence to read it again."
                    : t.error}
                </span>
              ) : null}
              {showStages ? (
                <ol className="s1-upq__stages" aria-label="Stages">
                  <li className={`s1-upq__stage-pill s1-upq__stage-pill--${uploadedState}`}>
                    {uploadedState === "done" ? <Check size={13} aria-hidden /> : null}
                    {uploadedState === "current" ? <span className="s1-upq__spin" aria-hidden="true" /> : null}
                    Uploaded
                  </li>
                  <li className={`s1-upq__stage-pill s1-upq__stage-pill--${readingState}`}>
                    {readingState === "done" ? <Check size={13} aria-hidden /> : null}
                    {readingState === "current" ? <span className="s1-upq__spin" aria-hidden="true" /> : null}
                    Reading
                  </li>
                </ol>
              ) : null}
            </li>
          );
        })}
      </ul>
      <div className="s1-upq__summary">
        <span>{doneCount} of {tasks.length} {tasks.length === 1 ? "file" : "files"} uploaded and read</span>
        {notUploadedCount > 0 ? <span>{notUploadedCount} not uploaded</span> : null}
      </div>
    </div>
  );
}

function upqFileExt(name: string): string {
  const parts = name.split(".");
  if (parts.length < 2) return "file";
  const ext = parts.pop()!.toLowerCase();
  if (ext === "jpeg") return "jpg";
  if (ext === "doc") return "docx";
  if (ext === "xls") return "xlsx";
  return ext;
}

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
