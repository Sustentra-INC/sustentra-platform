"use client";

import { useState } from "react";

import type { EvidenceItem } from "../types";

/**
 * Upload (screen 1). The drop area takes the client's files; a prepared invoice
 * is offered as the primary action, and uploading it plays the scripted
 * analysis beat before opening Extraction Review.
 */

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
  onOpenWorkspace,
}: {
  onUploadFiles: (files: FileList) => void;
  onUploadSample?: () => void;
  sampleFilename?: string;
  script?: SampleScript | null;
  batch: EvidenceItem[];
  onOpenWorkspace: () => void;
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
            <div className="s1-muted">Each file appears as a row in the Evidence Workspace as it uploads.</div>
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
