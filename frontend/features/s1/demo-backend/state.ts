/**
 * What the demo backend remembers for the tab: the engagement settings the screens save
 * (lines added in Evidence, recalculation inputs) and each document's saved decision
 * (placement moves). The app writes the engagement here in fixture mode instead of PATCHing it.
 */
import type { EngagementConfig } from "../types/engagement";
import type { DocumentDecision } from "../types/evidence";

let engagement: EngagementConfig | null = null;
const decisions = new Map<string, DocumentDecision>();

export function setDemoEngagement(next: EngagementConfig): void {
  engagement = next;
}

export function demoEngagement(): EngagementConfig | null {
  return engagement;
}

export function saveDemoDecision(decision: DocumentDecision): void {
  decisions.set(decision.documentId, decision);
}

export function demoDecisions(): ReadonlyMap<string, DocumentDecision> {
  return decisions;
}
