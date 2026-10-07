import { api } from "../../../lib/api";
import type { EngagementConfig } from "../types";

/**
 * Workpaper engagements (S1-BE-002): stored by the API in Postgres, scoped to the
 * signed-in user's org. The Setup screen edits one; uploads and the Evidence
 * Workspace use its id.
 */

export interface BackendEngagement {
  id: string;
  org_id: string;
  name: string;
  client_name: string | null;
  reporting_period_start: string | null;
  reporting_period_end: string | null;
  status: "active" | "archived";
  settings: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

/** Setup fields the API keeps in `settings` (same names as EngagementConfig). */
export const SETTINGS_KEYS = [
  "facilities",
  "regulation",
  "regulationJurisdiction",
  "conclusionType",
  "assuranceLevel",
  "boundaryApproach",
  "scopeBoundaryStatement",
  "methodology",
  "clientContact",
  "engagementTeam",
  "verifierEmail",
  "dataScope",
  "assuranceStandard",
  "materialityThreshold",
] as const satisfies readonly (keyof EngagementConfig)[];

export interface EngagementPayload {
  name: string;
  client_name: string | null;
  reporting_period_start: string | null;
  reporting_period_end: string | null;
  settings: Record<string, unknown>;
}

export function engagementFromBackend(row: BackendEngagement): EngagementConfig {
  const settings = row.settings ?? {};
  const text = (key: string) => (typeof settings[key] === "string" ? (settings[key] as string) : "");
  const config: EngagementConfig = {
    engagementId: row.id,
    engagementName: row.name,
    clientName: row.client_name ?? "",
    reportingPeriod: { start: row.reporting_period_start ?? "", end: row.reporting_period_end ?? "" },
    facilities: Array.isArray(settings.facilities) ? (settings.facilities as EngagementConfig["facilities"]) : [],
    regulation: text("regulation"),
    conclusionType: text("conclusionType"),
    assuranceLevel: text("assuranceLevel"),
    boundaryApproach: text("boundaryApproach"),
    scopeBoundaryStatement: text("scopeBoundaryStatement"),
  };
  for (const key of SETTINGS_KEYS) {
    if (!(key in config) && settings[key] !== undefined && settings[key] !== null) {
      (config as unknown as Record<string, unknown>)[key] = settings[key];
    }
  }
  return config;
}

export function engagementToBackend(config: EngagementConfig): EngagementPayload {
  const settings: Record<string, unknown> = {};
  for (const key of SETTINGS_KEYS) {
    const value = config[key];
    if (value !== undefined) settings[key] = value;
  }
  return {
    name: (config.engagementName ?? "").trim() || config.clientName.trim() || "Untitled engagement",
    client_name: config.clientName.trim() || null,
    reporting_period_start: config.reportingPeriod.start || null,
    reporting_period_end: config.reportingPeriod.end || null,
    settings,
  };
}

/** A reason the config cannot be saved yet, or null. */
export function engagementSaveProblem(config: EngagementConfig): string | null {
  const { start, end } = config.reportingPeriod;
  if (start && end && end < start) return "The reporting period ends before it starts.";
  return null;
}

export async function listEngagements(): Promise<BackendEngagement[]> {
  return (await api<{ items: BackendEngagement[] }>("/engagements")).items;
}

export function createEngagement(name: string): Promise<BackendEngagement> {
  return api<BackendEngagement>("/engagements", { method: "POST", body: { name: name.trim() } });
}

export function saveEngagement(config: EngagementConfig): Promise<BackendEngagement> {
  return api<BackendEngagement>(`/engagements/${encodeURIComponent(config.engagementId)}`, {
    method: "PATCH",
    body: engagementToBackend(config),
  });
}

// --- the engagement this browser last worked on -------------------------------------

const LAST_KEY = "sustentra.s1.engagementId";

export function rememberEngagement(id: string): void {
  try {
    window.localStorage.setItem(LAST_KEY, id);
  } catch {
    // Storage blocked: the most recently updated engagement opens instead.
  }
}

function rememberedEngagement(): string | null {
  try {
    return window.localStorage.getItem(LAST_KEY);
  } catch {
    return null;
  }
}

/** The remembered engagement if it is still in the list, else the most recently updated. */
export function pickEngagement(items: BackendEngagement[]): BackendEngagement | null {
  const remembered = rememberedEngagement();
  return items.find((item) => item.id === remembered) ?? items[0] ?? null;
}
