"use client";

import { useEffect, useId, useRef } from "react";

/**
 * The app's own confirmation window, in place of the browser's `confirm()`. It says what will happen
 * and offers the one action by name ("Withdraw", not "OK"). Escape, Cancel or a click outside cancel;
 * the cursor starts on Cancel so a stray Enter never confirms.
 */
export function ConfirmDialog({
  title,
  message,
  confirmLabel,
  onConfirm,
  onCancel,
}: {
  title: string;
  message: string;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const cancel = useRef<HTMLButtonElement>(null);
  const close = useRef(onCancel);
  const noteId = useId();
  useEffect(() => {
    close.current = onCancel;
  });
  useEffect(() => {
    cancel.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close.current();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);
  return (
    <div className="s1-modal-scrim" onPointerDown={(e) => e.target === e.currentTarget && onCancel()}>
      <div className="s1-modal" role="dialog" aria-modal="true" aria-label={title} aria-describedby={noteId}>
        <div className="s1-modal__head">
          <h2>{title}</h2>
        </div>
        <p className="s1-modal__note" id={noteId}>
          {message}
        </p>
        <div className="s1-modal__actions">
          <button className="s1-button s1-button--pri" type="button" onClick={onConfirm}>
            {confirmLabel}
          </button>
          <button className="s1-linklike" type="button" ref={cancel} onClick={onCancel}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
