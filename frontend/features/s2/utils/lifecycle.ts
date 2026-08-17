import type { Finding, RequestRecord } from "../types";

export interface ExaminationEntry {
  id: string;
  requirementId: string;
  version: number;
  note?: string;
}

export interface NoteEntry {
  id: string;
  subjectId: string;
  version: number;
  text: string;
  withdrawn?: boolean;
}

export function rerecordExamination(
  entries: ExaminationEntry[],
  next: Omit<ExaminationEntry, "id" | "version">
): ExaminationEntry[] {
  const existing = entries.filter((entry) => entry.requirementId === next.requirementId);
  return [
    ...entries,
    {
      ...next,
      id: `exam-${next.requirementId}-${existing.length + 1}`,
      version: existing.length + 1,
    },
  ];
}

export function reviseNote(entries: NoteEntry[], subjectId: string, text: string): NoteEntry[] {
  const existing = entries.filter((entry) => entry.subjectId === subjectId);
  return [
    ...entries,
    {
      id: `note-${subjectId}-${existing.length + 1}`,
      subjectId,
      text,
      version: existing.length + 1,
    },
  ];
}

export function withdrawFinding(findings: Finding[], findingId: string): Finding[] {
  return findings.map((finding) =>
    finding.id === findingId ? { ...finding, state: "withdrawn" } : finding
  );
}

export function countActiveFindings(findings: Finding[]): number {
  return findings.filter((finding) => finding.state !== "withdrawn").length;
}

export function withdrawRequest(requests: RequestRecord[], requestId: string): RequestRecord[] {
  return requests.map((request) =>
    request.id === requestId ? { ...request, state: "withdrawn" } : request
  );
}

export function preserveDraftAfterSendFailure(request: RequestRecord): RequestRecord {
  return { ...request, state: "drafted" };
}

export function rollbackAssignment<T extends { assignedTo?: string | null }>(
  current: T,
  previous: T
): T {
  return { ...current, assignedTo: previous.assignedTo ?? null };
}

