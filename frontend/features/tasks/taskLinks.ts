import { viewToSearch, type WorkpaperView } from "../s1/utils/viewHistory";

/**
 * In-app links a task points at. The workpaper is one page whose screens live in the query string
 * (`/?view=review&doc=...&e=...`, see utils/viewHistory), so a task link is that same address: opening
 * it from an email or the bell lands on the same screen. Paths only, never a full URL.
 */
export function workpaperLink(view: WorkpaperView, engagementId: string, extra: Record<string, string> = {}): string {
  const params = new URLSearchParams(viewToSearch(view, engagementId));
  for (const [key, value] of Object.entries(extra)) params.set(key, value);
  return `/?${params.toString()}`;
}

export const documentLink = (documentId: string, engagementId: string) =>
  workpaperLink({ name: "extraction", documentId, mode: "snippet" }, engagementId);

export const dataPointLineLink = (lineKey: string, engagementId: string) =>
  workpaperLink({ name: "schedule", lineKey }, engagementId);

/** The methodology screen; `row` names the row the task is about (ignored by the screen today, kept for people). */
export const methodologyRowLink = (fieldId: string, engagementId: string) =>
  workpaperLink({ name: "methodology" }, engagementId, { row: fieldId });

export const engagementLink = (engagementId: string) => workpaperLink({ name: "dashboard" }, engagementId);
