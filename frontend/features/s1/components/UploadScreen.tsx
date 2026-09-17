"use client";

import { useRef, useState } from "react";

import type { EvidenceItem } from "../types";

/**
 * Upload (screen 1). Where the client's package enters: a drop area that takes
 * folders of mixed, unlabelled files as they were sent. No table — each file
 * appears as a row in the Evidence Workspace as it uploads. This screen shows
 * only the drop area and live progress for the current batch.
 */
export function UploadScreen({
  onUploadFiles,
  batch,
  onOpenWorkspace,
}: {
  onUploadFiles: (files: FileList) => void;
  batch: EvidenceItem[];
  onOpenWorkspace: () => void;
}) {
  const [drag, setDrag] = useState(false);
  const folderInput = useRef<HTMLInputElement>(null);

  return (
    <section className="s1-content s1-upload-screen">
      <header className="s1-ws-header">
        <div className="s1-ws-header__id">
          <h1>Upload evidence</h1>
          <span className="s1-muted">Drop the client&rsquo;s package as it was sent — folders of mixed files are fine.</span>
        </div>
      </header>

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
          <h3>Drop files or folders here</h3>
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

      {batch.length > 0 ? (
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
      ) : (
        <p className="s1-muted s1-upload-screen__hint">
          Nothing uploaded yet. Files you add appear here while they process, then in the Evidence Workspace.
        </p>
      )}
    </section>
  );
}

function uploadStage(item: EvidenceItem): { role: string; label: string } {
  if (item.processingState === "blocked") return { role: "blocking", label: "Blocked" };
  if (item.processingState === "extracted") return { role: "resolved", label: "Extracted" };
  if (item.processingState === "typed" || item.processingState === "ingested")
    return { role: "active", label: "Extracting" };
  return { role: "active", label: "Uploading" };
}
