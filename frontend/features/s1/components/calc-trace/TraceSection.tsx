"use client";

import { Component, useState, type ReactNode } from "react";

import { TraceActionsProvider, useTraceDecisions } from "./TraceActions";
import { TracePanel } from "./TracePanel";
import { useLineTrace } from "./useLineTrace";

const ERROR_TEXT = "The step-by-step trace could not be loaded. The line's summary figures are shown instead.";

/** A trace that cannot be drawn falls back to the summary panel; it never takes the page down. */
class Boundary extends Component<{ fallback: ReactNode; children: ReactNode; resetKey: unknown }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidUpdate(prev: { resetKey: unknown }) {
    // A newly fetched trace gets its own chance to draw.
    if (this.state.failed && prev.resetKey !== this.props.resetKey) this.setState({ failed: false });
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

/**
 * Draws a line's trace when the backend has one. While it loads, and when there is none, the `fallback`
 * (the summary panel); when the fetch fails, an error here plus the `fallback`.
 */
export function TraceSection({
  engagementId,
  lineKey,
  version,
  fallback,
  onOpenDocument,
  onDecided,
  canDecide = true,
}: {
  /** False for a read-only role (provider_admin): no action is drawn; the 403 handling stays as a fallback. */
  canDecide?: boolean;
  engagementId?: string;
  lineKey: string;
  /** Changes when the line's figures change, so the trace is fetched again. */
  version: string;
  fallback: ReactNode;
  onOpenDocument?: (documentId: string, valueId?: string) => void;
  /** Called after a decision is saved (or refused as out of date): the caller fetches the recalculation again. */
  onDecided?: () => void;
}) {
  // A decision refetches this trace here and, through `onDecided`, the recalculation the totals come from.
  const [reload, setReload] = useState(0);
  const { actions, notice, clearNotice } = useTraceDecisions(engagementId ?? "", lineKey, () => {
    setReload((n) => n + 1);
    onDecided?.();
  });
  const state = useLineTrace(engagementId, lineKey, version, reload);
  const failed = (
    <>
      <p className="s1-cp-error" role="alert">
        {ERROR_TEXT}
      </p>
      {fallback}
    </>
  );
  // While the trace loads, the summary panel shows, so the numbers are never missing.
  if (state.status === "error") return failed;
  if (state.status === "ready")
    return (
      <Boundary key={version} resetKey={state.trace} fallback={failed}>
        {notice ? (
          <p className={notice.kind === "conflict" ? "s1-cp-note" : "s1-cp-error"} role={notice.kind === "conflict" ? "status" : "alert"}>
            {notice.text}{" "}
            <button type="button" className="s1-mr-link" onClick={clearNotice}>
              Dismiss
            </button>
          </p>
        ) : null}
        <TraceActionsProvider value={engagementId ? { ...actions, canAct: actions.canAct && canDecide } : { ...actions, canAct: false }}>
          <TracePanel trace={state.trace} decisions={state.decisions} onOpenDocument={onOpenDocument} />
        </TraceActionsProvider>
      </Boundary>
    );
  return <>{fallback}</>;
}
