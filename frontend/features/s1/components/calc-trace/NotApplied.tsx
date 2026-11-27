"use client";

import { createContext, useContext, type ReactNode } from "react";

import type { AutomaticFigure, DecisionEntry, TraceChoice } from "../../api/calcTrace";
import { prettyUnit } from "./format";

/**
 * A decision the working did not use (the trace response's `decisions.not_applied`, or a recalculation
 * line's): said on the input or choice it is about, or on the line when that is gone. The totals use the
 * automatic value meanwhile.
 */

const Context = createContext<DecisionEntry[]>([]);

export function NotAppliedProvider({ entries, children }: { entries: DecisionEntry[]; children: ReactNode }) {
  return <Context.Provider value={entries}>{children}</Context.Provider>;
}

/** The not-applied entries about one input (or row) or choice. */
export function useNotApplied(target: "choice" | "input", id: string): DecisionEntry[] {
  return useContext(Context).filter((e) => e.target === target && e.id === id && e.side !== "company");
}

function figure(value: AutomaticFigure | undefined, choice?: TraceChoice): string {
  if (value === undefined || value === null) return "not set";
  if (typeof value === "string") return choice?.options.find((o) => o.id === value)?.label ?? value;
  const unit = value.unit ? ` ${prettyUnit(value.unit)}` : "";
  if (value.value !== null && value.value !== undefined) return `${value.value}${unit}`;
  return value.grid_region ? String(value.grid_region) : "not set";
}

/** "Your edit was not applied: <why>", or for a stale one what the automatic value was and is. */
export function notAppliedText(entry: DecisionEntry, choice?: TraceChoice): string {
  if (entry.reason === "stale") {
    return `Your edit was made when the automatic value was ${figure(entry.automatic_then, choice)}; it's now ${figure(entry.automatic_now, choice)}, so it wasn't applied.`;
  }
  const why = (entry.message ?? entry.reason ?? "").replace(/^Not applied:\s*/i, "").trim();
  return `Your edit was not applied${why ? `: ${why}` : "."}`;
}

export function NotAppliedNote({ entries, choice }: { entries: DecisionEntry[]; choice?: TraceChoice }) {
  if (!entries.length) return null;
  return (
    <>
      {entries.map((e, i) => (
        <p key={`${e.target}|${e.id}|${i}`} className="s1-cp-note" role="status">
          {notAppliedText(e, choice)}
        </p>
      ))}
    </>
  );
}
