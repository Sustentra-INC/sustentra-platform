"use client";

import { useState } from "react";

import type { EvidenceItem } from "../types";
import { MAX_UPLOAD_MB } from "../constants/uploads";

/**
 * Upload (screen 1). The drop area takes the client's files; a prepared invoice
 * is offered as the primary action, and uploading it plays the scripted
 * analysis beat before opening Extraction Review.
 */

/** One file in the current upload, as the user picked it (backend mode). */
export interface UploadTask {
  id: string;
  filename: string;
  size: number;
  /** waiting -> uploading (bytes leave the browser) -> reading (parse, classify, extract) -> done | failed */
  stage: "waiting" | "uploading" | "reading" | "done" | "failed";
  /** Fraction of the file's bytes sent, 0..1 (measured, not estimated). */
  progress: number;
  error?: string;
  /** Set once the server has stored the file. */
  documentId?: string;
}

export interface SampleScript {
  filename: string;
  stage: "uploading" | "analyzing" | "classified" | "done";
  classified?: string;
  found: string[];
  progress: number; // 0..1
}

export function UploadScreen({
  onUploadFiles,
  onUploadSample,
  sampleFilename,
  script,
  batch,
  tasks = [],
  history,
  onOpenWorkspace,
  onOpenDocument,
}: {
  onUploadFiles: (files: FileList) => void;
  onUploadSample?: () => void;
  sampleFilename?: string;
  script?: SampleScript | null;
  batch: EvidenceItem[];
  /** Backend mode: the files being uploaded right now, with measured progress. */
  tasks?: UploadTask[];
  /** Backend mode: every document already uploaded to this engagement. */
  history?: EvidenceItem[];
  onOpenWorkspace: () => void;
  onOpenDocument?: (documentId: string) => void;
}) {
  const [drag, setDrag] = useState(false);
  const scripting = !!script && script.stage !== "done";

  return (
    <section className="s1-content s1-upload-screen">
      <header className="s1-ws-header">
        <div className="s1-ws-header__id">
          <h1>Upload evidence</h1>
          <span className="s1-muted">Add the client&rsquo;s documents as they were sent.</span>
        </div>
      </header>

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
      ) : onUploadSample && sampleFilename ? (
        <div className="s1-sample">
          <div className="s1-sample__doc">
            <div className="s1-sample__icon" aria-hidden>PDF</div>
            <div>
              <div className="s1-sample__fn">{sampleFilename}</div>
              <div className="s1-muted">From the client &middot; ready to add</div>
            </div>
          </div>
          <button className="s1-button s1-button--pri" type="button" onClick={onUploadSample}>
            Upload invoice
          </button>
        </div>
      ) : null}

      {!scripting ? (
        <div
          className={`s1-band s1-upload s1-upload-drop ${drag ? "s1-upload--drag" : ""}`}
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
            if (e.dataTransfer.files.length) onUploadFiles(e.dataTransfer.files);
          }}
        >
          <div>
            <h3>Or drop your own files</h3>
            <div className="s1-muted">
              Each file appears as a row in the Evidence Workspace as it uploads. Up to {MAX_UPLOAD_MB} MB per file.
            </div>
          </div>
          <div className="s1-upload-drop__actions">
            <label className="s1-button">
              Choose files
              <input
                className="s1-file-input"
                type="file"
                multiple
                onChange={(e) => {
                  if (e.target.files?.length) onUploadFiles(e.target.files);
                  e.target.value = "";
                }}
              />
            </label>
            <label className="s1-button">
              Choose folder
              <input
                className="s1-file-input"
                type="file"
                multiple
                ref={(el) => {
                  if (el) {
                    el.setAttribute("webkitdirectory", "");
                    el.setAttribute("directory", "");
                  }
                }}
                onChange={(e) => {
                  if (e.target.files?.length) onUploadFiles(e.target.files);
                  e.target.value = "";
                }}
              />
            </label>
          </div>
        </div>
      ) : null}

      {tasks.length > 0 ? <UploadProgress tasks={tasks} items={history ?? []} onOpenWorkspace={onOpenWorkspace} /> : null}

      {batch.length > 0 && !script ? (
        <div className="s1-upload-batch" aria-live="polite">
          <div className="s1-upload-batch__head">
            <strong>This upload</strong>
            <button className="s1-linklike" type="button" onClick={onOpenWorkspace}>
              View in Evidence Workspace
            </button>
          </div>
          {batch.map((item) => {
            const s = uploadStage(item);
            return (
              <div className="s1-upload-batch__row" key={item.documentId}>
                <span className="s1-upload-batch__fn">{item.filename}</span>
                <span className={`s1-state s1-state--${s.role}`}>{s.label}</span>
              </div>
            );
          })}
        </div>
      ) : null}

      {history ? <UploadHistory items={history} onOpenDocument={onOpenDocument} /> : null}
    </section>
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
  onOpenWorkspace,
}: {
  tasks: UploadTask[];
  items: EvidenceItem[];
  onOpenWorkspace: () => void;
}) {
  const byId = new Map(items.map((item) => [item.documentId, item]));
  const totalBytes = tasks.reduce((sum, t) => sum + t.size, 0);
  const sentBytes = tasks.reduce(
    (sum, t) => sum + (t.stage === "waiting" ? 0 : t.stage === "uploading" ? t.size * t.progress : t.size),
    0
  );
  const percent = totalBytes ? Math.round((sentBytes / totalBytes) * 100) : 0;
  const finished = tasks.filter((t) => t.stage === "done" || t.stage === "failed").length;
  const failed = tasks.filter((t) => t.stage === "failed").length;
  // What reading found, once a file is done: blocked files need the reviewer (e.g. set a type).
  const outcome = (t: UploadTask) => (t.stage === "done" && t.documentId ? byId.get(t.documentId) : undefined);
  const needsYou = tasks.filter((t) => outcome(t)?.processingState === "blocked").length;
  const running = finished < tasks.length;

  return (
    <div className="s1-upq" aria-live="polite">
      <div className="s1-upq__head">
        <strong>
          {running
            ? `Uploading ${tasks.length} file${tasks.length === 1 ? "" : "s"} · ${percent}%`
            : `${tasks.length - failed} of ${tasks.length} file${tasks.length === 1 ? "" : "s"} uploaded and read`}
        </strong>
        <span className="s1-muted">
          {finished} of {tasks.length} done{failed ? ` · ${failed} failed` : ""}
          {needsYou ? ` · ${needsYou} need${needsYou === 1 ? "s" : ""} you in the Evidence Workspace` : ""}
        </span>
        {!running ? (
          <button className="s1-linklike" type="button" onClick={onOpenWorkspace}>
            View in Evidence Workspace
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
      <ul className="s1-upq__list">
        {tasks.map((t) => (
          <li key={t.id} className={`s1-upq__row s1-upq__row--${t.stage}`}>
            <span className="s1-upq__name">{t.filename}</span>
            <span className="s1-muted s1-upq__size">{formatSize(t.size)}</span>
            <span className="s1-upq__track" aria-hidden>
              <span
                className={`s1-upq__track-fill${t.stage === "reading" ? " is-reading" : ""}`}
                style={{ width: `${t.stage === "waiting" ? 0 : t.stage === "uploading" ? Math.round(t.progress * 100) : 100}%` }}
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
                      ? outcome(t)?.processingState === "blocked"
                        ? "Needs you"
                        : "Done"
                      : "Failed"}
            </span>
            {t.error ? <span className="s1-upq__error">{t.error}</span> : null}
            {outcome(t)?.processingState === "blocked" ? (
              <span className="s1-upq__error">
                {outcome(t)?.haltReason ?? "Could not be read."} Set its type in the Evidence Workspace to read it again.
              </span>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

function formatWhen(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function historyStatus(item: EvidenceItem): { role: string; label: string } {
  if (item.processingState === "blocked") return { role: "blocking", label: "Blocked" };
  if (item.processingState === "extracted") {
    const partial = item.fieldsExpected > 0 && item.fieldsExtracted < item.fieldsExpected;
    return {
      role: partial ? "open" : "resolved",
      label: `${partial ? "Partially extracted" : "Extracted"}${item.fieldsExpected ? ` · ${item.fieldsExtracted} of ${item.fieldsExpected} fields` : ""}`,
    };
  }
  return { role: "active", label: "Reading" };
}

/** Every document uploaded to the engagement: what, when, who, and where it stands. */
function UploadHistory({ items, onOpenDocument }: { items: EvidenceItem[]; onOpenDocument?: (documentId: string) => void }) {
  const sorted = [...items].sort((a, b) => b.uploadedAt.localeCompare(a.uploadedAt));
  return (
    <section className="s1-uph" aria-label="Uploaded files">
      <h2 className="s1-uph__title">
        Uploaded files <span className="s1-muted">({items.length})</span>
      </h2>
      {sorted.length === 0 ? (
        <p className="s1-muted">Nothing uploaded to this engagement yet.</p>
      ) : (
        <div className="s1-table-wrap">
          <table className="s1-table s1-uph__table">
            <thead>
              <tr>
                <th>File</th>
                <th>Document type</th>
                <th>Uploaded</th>
                <th>By</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((item) => {
                const status = historyStatus(item);
                return (
                  <tr key={item.documentId}>
                    <td>
                      {onOpenDocument ? (
                        <button className="s1-linklike s1-uph__file" type="button" onClick={() => onOpenDocument(item.documentId)}>
                          {item.filename}
                        </button>
                      ) : (
                        <span className="s1-uph__file">{item.filename}</span>
                      )}
                      <div className="s1-muted s1-uph__fmt">{item.format.toUpperCase()}</div>
                    </td>
                    <td>{item.detectedType ?? <span className="s1-muted">Not identified</span>}</td>
                    <td className="s1-mono">{formatWhen(item.uploadedAt)}</td>
                    <td>{item.uploadedBy.name}</td>
                    <td>
                      <span className={`s1-state s1-state--${status.role}`}>{status.label}</span>
                      {item.haltReason ? <div className="s1-muted s1-uph__why">{item.haltReason}</div> : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
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
