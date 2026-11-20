"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import { NO_REASON, type AiExplanation } from "../api/aiExplanation";
import { AI_EXPLAIN } from "../constants/copy";

function when(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });
}

/**
 * "Suggested by Sustentra's AI" as a button that opens the explanation: Why (the AI's own reason), Evidence (the
 * quote and the document and page, a link when the screen can open the document) and Checks passed (what the
 * server verified, and what was implied and how). Click or Enter/Space opens it, Esc or a click elsewhere closes it
 * and returns focus to the button; Tab moves into the panel's links. Uses the info tip's popover styles.
 */
export function AiExplainPopover({
  label,
  explanation,
  onOpenDocument,
  className,
  testId,
}: {
  label: ReactNode;
  explanation: AiExplanation;
  onOpenDocument?: (documentId: string, at: { entry: number | null; page: number | null }) => void;
  /** The trigger's look: the caller's chip classes. */
  className?: string;
  testId?: string;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLSpanElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const id = useId();

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        trigger.current?.focus();
      }
    };
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const items = explanation.items;
  const many = items.length > 1;
  const tag = (label: string | null) => (many && label ? <strong>{label}: </strong> : null);
  const read = AI_EXPLAIN.readBy(when(explanation.read_at));

  return (
    <span
      className="s1-infotip s1-explain"
      ref={root}
      onBlur={(e) => {
        if (open && !root.current?.contains(e.relatedTarget as Node | null)) setOpen(false);
      }}
    >
      <button
        ref={trigger}
        type="button"
        className={`s1-explain__btn ${className ?? ""}`.trim()}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        data-testid={testId}
        onClick={() => setOpen((v) => !v)}
      >
        {label}
      </button>
      {open ? (
        <span className="s1-infotip__panel s1-explain__panel" role="dialog" id={id} aria-label={AI_EXPLAIN.dialog} data-testid="ai-explanation">
          <section className="s1-explain__sec">
            <h4>{AI_EXPLAIN.why}</h4>
            {items.some((i) => i.reason) ? (
              items.map((item, index) => (
                <p key={index}>
                  {tag(item.label)}
                  {item.reason ?? explanation.reason_note ?? NO_REASON}
                </p>
              ))
            ) : (
              <p>{explanation.reason_note ?? NO_REASON}</p>
            )}
          </section>
          <section className="s1-explain__sec">
            <h4>{AI_EXPLAIN.evidence}</h4>
            {items.some((i) => i.quote) ? (
              items.map((item, index) => (
                <p key={index}>
                  {tag(item.label)}
                  <q>{item.quote}</q>{" "}
                  {item.file_name ? (
                    onOpenDocument && item.document_id ? (
                      <button type="button" className="s1-explain__link" onClick={() => onOpenDocument(item.document_id, { entry: many ? index : null, page: item.page })}>
                        {item.file_name}
                        {item.location ? `, ${item.location}` : ""}
                      </button>
                    ) : (
                      <span>
                        {item.file_name}
                        {item.location ? `, ${item.location}` : ""}
                      </span>
                    )
                  ) : item.location ? (
                    <span>{item.location}</span>
                  ) : null}
                </p>
              ))
            ) : (
              <p>{AI_EXPLAIN.noEvidence}</p>
            )}
          </section>
          <section className="s1-explain__sec">
            <h4>{AI_EXPLAIN.checks}</h4>
            {items.some((i) => i.checks.length || i.implied.length) ? (
              <ul>
                {items.flatMap((item, index) => [
                  ...item.checks.map((c, n) => (
                    <li key={`${index}-c${n}`}>
                      {tag(item.label)}
                      {c}
                    </li>
                  )),
                  ...item.implied.map((c, n) => (
                    <li key={`${index}-i${n}`}>
                      {tag(item.label)}
                      <strong>{AI_EXPLAIN.implied}. </strong>
                      {c}
                    </li>
                  )),
                ])}
              </ul>
            ) : (
              <p>{AI_EXPLAIN.noChecks}</p>
            )}
          </section>
          {explanation.read_at ? <p className="s1-explain__foot">{read}</p> : null}
        </span>
      ) : null}
    </span>
  );
}
