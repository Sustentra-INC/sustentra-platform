import type { ReactNode } from "react";

import { ContainerStateSurface } from "./ContainerStateSurface";
import type { WorkspaceProblem } from "./EvidenceWorkspace";

/**
 * Holds back a screen that reads the engagement's documents until they have been fetched, so
 * it never shows "0 documents" or "No documents yet" for something that is only loading.
 * Loading shows the loading surface; a failed load says what went wrong and offers a retry;
 * only a finished load (even one with no documents) reaches the screen itself.
 */
export function WorkspaceStateGate({
  status,
  problem,
  onRetry,
  children,
}: {
  status: "loading" | "failed" | "ready";
  problem: WorkspaceProblem | null;
  onRetry: () => void;
  children?: ReactNode;
}) {
  if (status === "loading") {
    return (
      <section className="s1-content">
        <ContainerStateSurface state="loading" />
      </section>
    );
  }
  if (status === "failed") {
    return (
      <section className="s1-content">
        <div className="s1-system-banner" role="alert">
          <strong>{problem?.title ?? "Couldn't load the evidence"}</strong>
          <span>{problem?.message ?? "Try again in a moment."}</span>
          <button className="s1-button" type="button" onClick={onRetry}>
            Try again
          </button>
        </div>
      </section>
    );
  }
  return <>{children}</>;
}
