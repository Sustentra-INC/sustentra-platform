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
}

let counter = 0;

export function useVerificationStore(
  initialExaminations: Record<string, Examination> = {},
  initialFindings: Finding[] = []
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
    const created: Finding = { ...finding, id: `FND-${counter}` };
    setFindings((cur) => [...cur, created]);
    // Raising a finding is an examination outcome.
    patch(finding.dataPointId, { examinationState: "finding_raised" });
    return created;
  }, []);

  return { examinations, findings, setExaminationState, setNextAction, registerFinding };
}
