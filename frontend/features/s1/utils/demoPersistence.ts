import type { EngagementConfig } from "../types/engagement";
import type { EvidenceItem } from "../types/evidence";
import type { ReviewValue } from "../types/review";
import type { InScopeField } from "../types/scope";
import type { Ask } from "../types/requests";
import type { Examination, Finding } from "../types/verification";

/**
 * Demo-only persistence. The fixture demo has no backend, so a browser refresh
 * used to wipe every edit. This snapshots the app's fixture state to
 * localStorage so a demo survives a reload. It is NOT a substitute for a real
 * backend — it's per-browser, best-effort, and cleared by "Reset demo".
 *
 * Every read/write is wrapped: storage can throw (private windows, disabled
 * site data) or be absent (SSR), and the app must work with nothing stored.
 */

const KEY = "sustentra-demo-v1";

export interface DemoSnapshot {
  version: 1;
  engagement: EngagementConfig;
  evidenceItems: EvidenceItem[];
  reviewValues: ReviewValue[];
  inScopeFields: InScopeField[];
  sessionUploads: string[];
  asks: Ask[];
  examinations: Record<string, Examination>;
  findings: Finding[];
}

export function loadDemoState(): DemoSnapshot | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as DemoSnapshot;
    return parsed && parsed.version === 1 ? parsed : null;
  } catch {
    return null;
  }
}

export function saveDemoState(snapshot: Omit<DemoSnapshot, "version">): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(KEY, JSON.stringify({ version: 1, ...snapshot }));
  } catch {
    // Storage full or unavailable — the demo still works, it just won't persist.
  }
}

export function clearDemoState(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(KEY);
    window.localStorage.removeItem(SIGNED_IN_KEY);
  } catch {
    // ignore
  }
}

const SIGNED_IN_KEY = "sustentra-demo-signedin";

export function loadSignedIn(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(SIGNED_IN_KEY) === "1";
  } catch {
    return false;
  }
}

export function saveSignedIn(signedIn: boolean): void {
  if (typeof window === "undefined") return;
  try {
    if (signedIn) window.localStorage.setItem(SIGNED_IN_KEY, "1");
    else window.localStorage.removeItem(SIGNED_IN_KEY);
  } catch {
    // ignore
  }
}
