"use client";

import { createContext, useContext, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";

import type { DecisionRefusal, TraceSuggestion } from "../../api/calcTrace";
import type { AiExplanation } from "../../api/aiExplanation";
import { ApiError } from "../../../../lib/api";
import { userFacingApiError } from "../../api/s1Backend";
import { AiExplainPopover } from "../AiExplainPopover";

/**
 * What a reviewer can do on a trace: the one place that posts a decision (api/calcTrace.ts), refetches
 * the trace and the recalculation, and turns a failure into a sentence inside the panel. A panel
 * drawn without a provider is read-only.
 */

export const CHANGED_TEXT = "This value changed since you opened it.";
export const READ_ONLY_TEXT = "You can view this calculation but not change it.";

export const STALE_TEXT = "The automatic value changed since you opened this, so your change was not saved.";
const REFUSAL_TEXT: Record<Exclude<DecisionRefusal, "stale">, string> = {
  mixed_line: "This line mixes fuels or units, so a value can't be changed on it yet. Move the other records to their own line first.",
  not_decidable: "This value is set elsewhere, so it can't be changed for one line.",
  no_working: "This line has no working to change yet.",
  not_counted: "This value is not counted in the line's total, so it can't be changed.",
};
const CODES = new Set(["mixed_line", "stale", "not_decidable", "no_working", "not_counted"]);

/** The `code` of a coded 409, or null for a plain one. */
function refusalCode(error: unknown): DecisionRefusal | null {
  const body = error instanceof ApiError ? (error.body as { code?: unknown } | null) : null;
  return typeof body?.code === "string" && CODES.has(body.code) ? (body.code as DecisionRefusal) : null;
}

export interface TraceActions {
  /** False for a read-only role (the server answered 403): no action is drawn. */
  canAct: boolean;
  busy: boolean;
  engagementId: string;
  lineKey: string;
  /**
   * Runs a decision. Resolves to null when it was saved (or handled in the panel's notice), or to the
   * server's sentence when `inline` and the input was refused (422) or the request failed, so the open
   * editor can show it beside the field.
   */
  act: (run: () => Promise<unknown>, options?: { inline?: boolean; entered?: string }) => Promise<string | null>;
}

const Context = createContext<TraceActions | null>(null);

export function TraceActionsProvider({ value, children }: { value: TraceActions; children: ReactNode }) {
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

/** The actions, or null when the panel is read-only (no provider, or the role cannot write). */
export function useTraceActions(): TraceActions | null {
  const actions = useContext(Context);
  return actions && actions.canAct ? actions : null;
}

export interface DecisionNotice {
  kind: "conflict" | "error";
  text: string;
}

/**
 * The state behind the provider. After a saved decision, `onSaved` refetches the trace and the
 * recalculation. A 409 refetches the same way and says the value changed; a 403 hides the actions.
 */
export function useTraceDecisions(engagementId: string, lineKey: string, onSaved: () => void): { actions: TraceActions; notice: DecisionNotice | null; clearNotice: () => void } {
  const [busy, setBusy] = useState(false);
  const [forbidden, setForbidden] = useState(false);
  const [notice, setNotice] = useState<DecisionNotice | null>(null);
  const running = useRef(false);
  const saved = useRef(onSaved);
  useEffect(() => {
    saved.current = onSaved;
  });

  const act: TraceActions["act"] = async (run, options) => {
    if (running.current) return null; // a second click while one is in flight is ignored, never sent twice
    running.current = true;
    setBusy(true);
    setNotice(null);
    try {
      await run();
      saved.current();
      return null;
    } catch (error) {
      const status = error instanceof ApiError ? error.status : 0;
      if (status === 403) {
        setForbidden(true);
        setNotice({ kind: "error", text: READ_ONLY_TEXT });
        return null;
      }
      if (status === 409) {
        const code = refusalCode(error);
        const typed = options?.entered ? ` You entered ${options.entered}.` : "";
        if (code && code !== "stale") {
          // The working cannot take this decision: nothing changed on the server, so nothing to refetch.
          setNotice({ kind: "conflict", text: `${REFUSAL_TEXT[code]}${typed}` });
          return null;
        }
        // A real change of state (or the automatic value moved): the trace and totals are fetched again.
        const changed = code === "stale" ? STALE_TEXT : CHANGED_TEXT;
        setNotice({ kind: "conflict", text: options?.entered ? `${changed.slice(0, -1)} (you entered ${options.entered}).` : changed });
        saved.current();
        return null;
      }
      const message = status === 422 ? userFacingApiError(error) : `Not saved. ${userFacingApiError(error)}`;
      if (options?.inline) return message;
      setNotice({ kind: "error", text: message });
      return null;
    } finally {
      running.current = false;
      setBusy(false);
    }
  };

  return { actions: { canAct: !forbidden, busy, act, engagementId, lineKey }, notice, clearNotice: () => setNotice(null) };
}

/* ------------------------------------------ the AI's suggestion ------------------------------------------ */

/** The server's explanation shape, made from the suggestion the trace carries. */
export function explanationOfSuggestion(s: TraceSuggestion): AiExplanation {
  const src = s.source ?? { kind: "document" as const };
  const location = src.page ? `page ${src.page}` : src.sheet || src.cell ? [src.sheet, src.cell].filter(Boolean).join(", ") : "";
  return {
    reason: s.reason || null,
    reason_note: null,
    read_at: s.suggested_at,
    items: [
      {
        label: null,
        reason: s.reason || null,
        quote: s.quote ?? "",
        document_id: src.document_id ?? "",
        file_name: src.file_name ?? "",
        page: src.page ?? null,
        location,
        checks: [],
        implied: [],
      },
    ],
  };
}

export function SuggestionChip({ suggestion, onOpenDocument }: { suggestion: TraceSuggestion; onOpenDocument?: (documentId: string, valueId?: string) => void }) {
  return (
    <AiExplainPopover
      label="Suggested by Sustentra's AI"
      className="s1-chip s1-mb-chip"
      explanation={explanationOfSuggestion(suggestion)}
      onOpenDocument={onOpenDocument ? (documentId) => onOpenDocument(documentId) : undefined}
    />
  );
}

/* ------------------------------------------ a reason, asked for inline ------------------------------------------ */

/** The reason field of Methodology review's Reject, in a trace: Enter saves, Escape cancels. */
export function ReasonRow({
  label,
  placeholder,
  submitLabel,
  onSubmit,
  onCancel,
  children,
  validate,
}: {
  label: string;
  placeholder: string;
  submitLabel: string;
  /** Resolves to a sentence to show beside the field, or null when done. */
  onSubmit: (reason: string) => Promise<string | null>;
  onCancel: () => void;
  /** Extra fields before the reason (the edit's value). */
  children?: ReactNode;
  /** A reason alone is not enough: the extra fields are checked too. */
  validate?: () => boolean;
}) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const actions = useContext(Context);
  const busy = actions?.busy ?? false;
  const ready = reason.trim().length > 0 && (validate ? validate() : true);

  async function submit(e?: FormEvent) {
    e?.preventDefault();
    if (!ready || busy) return;
    setError(null);
    const message = await onSubmit(reason.trim());
    if (message) setError(message);
  }

  return (
    <form
      className="s1-cp-reason"
      onSubmit={submit}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          onCancel();
        }
      }}
    >
      {children}
      <input
        className="s1-mr-input"
        aria-label={label}
        maxLength={500}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        placeholder={placeholder}
        autoFocus={!children}
      />
      <span className="s1-mr-actions">
        <button type="submit" className="s1-button s1-button--compact s1-button--pri" disabled={busy || !ready}>
          {submitLabel}
        </button>
        <button type="button" className="s1-button s1-button--compact" onClick={onCancel}>
          Cancel
        </button>
      </span>
      {error ? (
        <span className="s1-cp-reason__error" role="alert">
          {error}
        </span>
      ) : null}
    </form>
  );
}
