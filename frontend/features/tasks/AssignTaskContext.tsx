"use client";

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

import { AssignTaskDialog } from "./AssignTaskDialog";

/** What a task is about: where "Assign to…" was chosen. */
export interface AssignTarget {
  /** What kind of thing it is, in the words the dialog uses: "document", "data point line"... */
  kind: string;
  /** The thing's name: the file name, the line, the methodology row, the engagement. */
  label: string;
  /** What it is, for the server to check and link to. The client never sends a link. */
  target: { kind: "document" | "line" | "methodology_row" | "engagement"; item_id?: string };
  /** Pre-filled task title; the person can change it. */
  title: string;
}

type Assign = (target: AssignTarget) => void;

const AssignContext = createContext<Assign | null>(null);

/**
 * Lets any screen of the workpaper offer "Assign to…" without carrying the organisation and engagement
 * down to it. Without an organisation (the demo site, signed out) there is nothing to assign to, and
 * `useAssignTask()` returns null so screens simply leave the action out.
 */
export function AssignTaskProvider({
  orgId,
  engagementId,
  children,
}: {
  orgId: string | null;
  engagementId: string | null;
  children: ReactNode;
}) {
  const [target, setTarget] = useState<AssignTarget | null>(null);
  const open = useCallback<Assign>((next) => setTarget(next), []);
  const value = useMemo<Assign | null>(() => (orgId ? open : null), [orgId, open]);
  return (
    <AssignContext.Provider value={value}>
      {children}
      {orgId && target ? (
        <AssignTaskDialog orgId={orgId} engagementId={engagementId} target={target} onClose={() => setTarget(null)} />
      ) : null}
    </AssignContext.Provider>
  );
}

/** Opens the "Assign to…" window for a target, or null where assigning is not available. */
export function useAssignTask(): Assign | null {
  return useContext(AssignContext);
}
