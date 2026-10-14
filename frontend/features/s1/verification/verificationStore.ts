"use client";

import { useCallback, useState } from "react";

import type { Examination, ExaminationState, Finding, NextActionWith } from "../types/verification";

/**
 * Frontend-owned verification dispositions. The backend supplies machine check
 * results only; examination state, next action and findings prose are the
 * verifier's, so they live here — same single-persist pattern as the requests
 * store, ready to move behind a backend in one place.
 */
export interface VerificationStore {
  examinations: Record<string, Examination>;
  findings: Finding[];
  setExaminationState: (dataPointId: string, state: ExaminationState) => void;
  setNextAction: (dataPointId: string, next: NextActionWith) => void;
  registerFinding: (finding: Omit<Finding, "id">) => Finding;
  /** Record examination on a facility row: the examiner, now, and an optional note. */
  recordExamination: (key: string, examiner: { name: string; login?: string }, note?: string) => void;
  clearExamination: (key: string) => void;
  /** A note on a facility row; it does not count as examination. */
  addNote: (key: string, text: string) => void;
  /** Replace everything with what was loaded from the backend (an engagement was opened). */
  replaceAll: (examinations: Record<string, Examination>, findings: Finding[]) => void;
}

let counter = 0;

export function useVerificationStore(
  initialExaminations: Record<string, Examination> = {},
  initialFindings: Finding[] = [],
  /** Who registers findings in this session (the signed-in person, in backend mode). */
  actorName?: string
): VerificationStore {
  const [examinations, setExaminations] = useState<Record<string, Examination>>(initialExaminations);
  const [findings, setFindings] = useState<Finding[]>(initialFindings);

  const patch = (dataPointId: string, next: Partial<Examination>) =>
    setExaminations((cur) => ({
      ...cur,
      [dataPointId]: {
        examinationState: cur[dataPointId]?.examinationState ?? "not_examined",
        nextActionWith: cur[dataPointId]?.nextActionWith ?? "none",
        ...next,
      },
    }));

  const setExaminationState = useCallback((dataPointId: string, state: ExaminationState) => {
    patch(dataPointId, { examinationState: state });
  }, []);

  const setNextAction = useCallback((dataPointId: string, next: NextActionWith) => {
    patch(dataPointId, { nextActionWith: next });
  }, []);

  const registerFinding = useCallback((finding: Omit<Finding, "id">): Finding => {
    counter += 1;
    // Unique across reloads: saved findings must never be overwritten by a new one.
    const created: Finding = {
      ...finding,
      id: `FND-${Date.now().toString(36)}-${counter}`,
      registeredAt: finding.registeredAt ?? new Date().toISOString(),
      registeredBy: finding.registeredBy ?? actorName,
    };
    setFindings((cur) => [...cur, created]);
    // Raising a finding is an examination outcome.
    patch(finding.dataPointId, { examinationState: "finding_raised" });
    return created;
  }, [actorName]);

  const recordExamination = useCallback((key: string, examiner: { name: string; login?: string }, note?: string) => {
    patch(key, {
      examinationState: "examined_no_exceptions",
      examinedBy: examiner.name,
      examinedByLogin: examiner.login,
      examinedAt: new Date().toISOString(),
      note: note?.trim() || undefined,
    });
  }, []);

  const clearExamination = useCallback((key: string) => {
    patch(key, { examinationState: "not_examined", examinedBy: undefined, examinedByLogin: undefined, examinedAt: undefined, note: undefined });
  }, []);

  const addNote = useCallback((key: string, text: string) => {
    setExaminations((cur) => {
      const existing = cur[key];
      return {
        ...cur,
        [key]: {
          ...existing,
          examinationState: existing?.examinationState ?? "not_examined",
          nextActionWith: existing?.nextActionWith ?? "none",
          notes: [...(existing?.notes ?? []), { text: text.trim(), by: actorName, at: new Date().toISOString() }],
        },
      };
    });
  }, [actorName]);

  const replaceAll = useCallback((nextExaminations: Record<string, Examination>, nextFindings: Finding[]) => {
    setExaminations(nextExaminations);
    setFindings(nextFindings);
  }, []);

  return {
    examinations, findings, setExaminationState, setNextAction, registerFinding, recordExamination, clearExamination, addNote,
    replaceAll,
  };
}
