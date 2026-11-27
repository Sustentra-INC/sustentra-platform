"use client";

import { useEffect, useId, useRef, type ReactNode, type RefObject } from "react";

import { IconClose } from "./icons";

/**
 * The shared dialog: scrim, panel, a head with an optional icon, title and context line, and a
 * close button. It focuses the first field on open, closes on Escape, and gives focus back to
 * whatever opened it (or `returnFocusTo`) when it closes.
 */
export function Dialog({
  title,
  context,
  icon,
  onClose,
  children,
  size = "sm",
  closeOnScrim = false,
  closeDisabled = false,
  returnFocusTo,
}: {
  title: string;
  context?: string;
  icon?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  /** "sm" is the standard dialog; "md" is a little wider for forms with two columns. */
  size?: "sm" | "md";
  /** A click on the scrim closes the dialog. */
  closeOnScrim?: boolean;
  /** While true (a save on its way), nothing closes the dialog: not the button, Escape or the scrim. */
  closeDisabled?: boolean;
  /** Where focus goes when the dialog closes; defaults to the element focused when it opened. */
  returnFocusTo?: HTMLElement | RefObject<HTMLElement | null> | null;
}) {
  const box = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  const locked = useRef(closeDisabled);
  const returnTo = useRef(returnFocusTo);
  // Taken at first render, before any field inside can take focus.
  const opener = useRef(typeof document === "undefined" ? null : document.activeElement);
  const titleId = useId();
  useEffect(() => {
    close.current = onClose;
    locked.current = closeDisabled;
    returnTo.current = returnFocusTo;
  });
  const restoreTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    // A remount of the same dialog (React's dev double-run) cancels the focus hand-back of its cleanup.
    if (restoreTimer.current !== null) {
      clearTimeout(restoreTimer.current);
      restoreTimer.current = null;
    }
    const openedFrom = opener.current instanceof HTMLElement ? opener.current : null;
    // A field that asked for focus itself (autoFocus) keeps it; otherwise the first field gets it.
    if (!box.current?.contains(document.activeElement)) {
      box.current?.querySelector<HTMLElement>("input, select, textarea, button:not([disabled]):not(.s1-modal__close)")?.focus();
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !locked.current) close.current();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      restoreTimer.current = setTimeout(() => {
        restoreTimer.current = null;
        const target = returnTo.current;
        const el = target && "current" in target ? target.current : (target ?? openedFrom);
        if (el?.isConnected) el.focus();
      });
    };
  }, []);
  return (
    <div
      className="s1-modal-scrim"
      onClick={closeOnScrim ? (e) => e.target === e.currentTarget && !locked.current && close.current() : undefined}
    >
      <div className={`s1-modal${size === "md" ? " s1-modal--md" : ""}`} role="dialog" aria-modal="true" aria-labelledby={titleId} ref={box}>
        <div className="s1-modal__head">
          {icon ? <span className="s1-modal__head-icon" aria-hidden>{icon}</span> : null}
          <div className="s1-modal__head-text">
            <h2 id={titleId} className="s1-modal__title">{title}</h2>
            {context ? <span className="s1-modal__context">{context}</span> : null}
          </div>
          <button
            className="s1-button s1-button--icon s1-modal__close"
            type="button"
            onClick={onClose}
            disabled={closeDisabled || undefined}
            aria-label="Close"
          >
            <IconClose size={15} aria-hidden />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
