"use client";

import { Component, type ReactNode } from "react";

import { TracePanel } from "./TracePanel";
import { useLineTrace } from "./useLineTrace";

const ERROR_TEXT = "The step-by-step trace could not be loaded. The line's summary figures are shown instead.";

/** A trace that cannot be drawn falls back to the summary panel; it never takes the page down. */
class Boundary extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
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
}: {
  engagementId?: string;
  lineKey: string;
  /** Changes when the line's figures change, so the trace is fetched again. */
  version: string;
  fallback: ReactNode;
  onOpenDocument?: (documentId: string, valueId?: string) => void;
}) {
  const state = useLineTrace(engagementId, lineKey, version);
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
      <Boundary fallback={failed}>
        <TracePanel trace={state.trace} onOpenDocument={onOpenDocument} />
      </Boundary>
    );
  return <>{fallback}</>;
}
