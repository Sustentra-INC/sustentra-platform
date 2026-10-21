"use client";

import { CloudUpload, X } from "lucide-react";
import { createPortal } from "react-dom";
import { useEffect, useState } from "react";

import type { EvidenceItem } from "../types";
import { MAX_UPLOAD_MB } from "../constants/uploads";


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
  onOpenWorkspace: () => void;
}) {
  const [drag, setDrag] = useState(false);
  const [before] = useState(() => new Set(batch.map((item) => item.documentId)));
  const added = batch.filter((item) => !before.has(item.documentId));
  const scripting = !!script && script.stage !== "done";
  const busy = scripting || tasks.some((t) => t.stage === "waiting" || t.stage === "uploading" || t.stage === "reading");
  const anything = added.length > 0 || tasks.length > 0;

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
          <h2 id="s1-updlg-title">Upload evidence</h2>
          <button className="s1-updlg__close" type="button" aria-label="Close" onClick={onClose}>
            <X aria-hidden />
          </button>
        </div>

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
            <CloudUpload className="s1-updlg__dropicon" aria-hidden />
            <span className="s1-updlg__droptext">
              <strong>Drop files here</strong> or <span className="s1-updlg__browse">choose files</span>
            </span>
            <span className="s1-updlg__hint">PDF, Word, Excel, CSV, scans and photos · up to {MAX_UPLOAD_MB} MB each</span>
            <input
              className="s1-file-input"
              type="file"
              multiple
              onChange={(e) => {
                pick(e.target.files);
                e.target.value = "";
              }}
            />
          </label>
        )}

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

        {tasks.length > 0 ? <UploadProgress tasks={tasks} items={items} /> : null}

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
            <span className="s1-updlg__hint">{busy ? "You can close this; reading carries on." : "Done. Each file is a row in Evidence."}</span>
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
function UploadProgress({ tasks, items }: { tasks: UploadTask[]; items: EvidenceItem[] }) {
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
          {needsYou ? ` · ${needsYou} need${needsYou === 1 ? "s" : ""} you in Evidence` : ""}
        </span>
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
                {outcome(t)?.haltReason ?? "Could not be read."} Set its type in Evidence to read it again.
              </span>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
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
