/**
 * Demo backend: reviewer decisions on a calculation line's working
 * (backend/app/api/calculation_line_review.py). The same two POST routes and the same refusals (409 state,
 * 422 input), kept in memory for the tab, and shown on the trace as the backend shows them. Like the
 * backend today, a decision is recorded and shown but moves no total.
 */
import type { LineTrace, TraceDecision, TraceSide, TraceSuggestion } from "../../api/calcTrace";
import { demoError } from "..";
import { engagementNow } from "../linesModel";
import type { DemoRoute } from "../types";
import { resetDemoCompanyRegions, setDemoCompanyRegion } from "./companyRegion";

interface Record_ {
  suggestion: TraceSuggestion | null;
  decision: TraceDecision | null;
  /** The decisions each move replaced, newest last; Revert pops one. */
  history: TraceDecision[];
}

const records = new Map<string, Record_>();

/** Forget every decision (the demo's Reset). */
export function resetDemoDecisions(): void {
  records.clear();
  resetDemoCompanyRegions();
}
const keyOf = (engagement: string, line: string, stream: string) => `${engagement}|${line}|${stream}`;
const MAX_TEXT = 200;
const MAX_REASON = 500;

function actorName(): string {
  const e = engagementNow();
  return e.engagementTeam?.find((m) => m.login === e.signedInLogin)?.name ?? e.signedInName ?? "You";
}

const status = (r: Record_) => r.decision?.status ?? "pending";
const already = (label: string, s: string) => demoError(409, `'${label}' is already ${s}. Revert it to pending first if you want to decide again.`);
function reasonOf(value: unknown, missing: string | null): string | undefined {
  if (value === null || value === undefined || (typeof value === "string" && !value.trim())) {
    if (missing) demoError(422, missing);
    return undefined;
  }
  if (typeof value !== "string") demoError(422, "The reason must be text.");
  const text = (value as string).trim();
  if (text.length > MAX_REASON) demoError(422, `The reason is too long: at most ${MAX_REASON} characters.`);
  return text;
}

function move(rec: Record_, next: Omit<TraceDecision, "by" | "at">): void {
  if (rec.decision && rec.decision.status !== "pending") rec.history.push(rec.decision);
  rec.decision = { ...next, by: actorName(), at: new Date().toISOString() };
}

function revert(rec: Record_, label: string): void {
  if (status(rec) === "pending") demoError(409, `'${label}' is already pending, so there is nothing to revert.`);
  const previous = rec.history.pop();
  rec.decision = previous ?? null;
}


export function applyDecisions(engagementId: string, trace: LineTrace): LineTrace {
  const out = structuredClone(trace);
  for (const c of out.choices) {
    const r = records.get(keyOf(engagementId, trace.line_key, `choice|${c.id}|`));
    if (r?.decision) c.decision = r.decision;
    if (r?.suggestion) c.suggestion = r.suggestion;
  }
  for (const [id, input] of Object.entries(out.inputs)) {
    for (const side of ["company", "recomputed"] as const) {
      const holders: [string, { company?: TraceSide; recomputed?: TraceSide }][] = [[id, input], ...(input.rows ?? []).map((row): [string, { company?: TraceSide; recomputed?: TraceSide }] => [`${id}/${row.id}`, row])];
      for (const [streamId, holder] of holders) {
        const r = records.get(keyOf(engagementId, trace.line_key, `input|${streamId}|${side}`));
        const s = holder[side];
        if (r && s) {
          if (r.decision) s.decision = r.decision;
          if (r.suggestion) s.suggestion = r.suggestion;
        }
      }
    }
  }
  return out;
}

type Traced = (engagementId: string, lineKey: string) => LineTrace | null;

export function decisionRoutes(traceOf: Traced): DemoRoute[] {
  const base = "^\\/engagements\\/(?<id>[^/]+)\\/calculation-lines\\/(?<key>[^/]+)";
  return [
    {
      method: "POST",
      path: new RegExp(`${base}\\/choices\\/(?<target>[^/]+)$`),
      handle: ({ params, body }) => {
        const trace = traceOf(params.id, params.key);
        if (!trace) demoError(404, "No such calculation line. Reload the page to see the current lines.");
        const choice = trace!.choices.find((c) => c.id === params.target);
        if (!choice) demoError(404, "That choice is not on this line. Reload the page.");
        const b = (body ?? {}) as { action?: string; option_id?: string; reason?: string };
        const stream = `choice|${params.target}|`;
        const k = keyOf(params.id, params.key, stream);
        const rec = records.get(k) ?? { suggestion: choice!.suggestion ?? null, decision: null, history: [] };
        const label = choice!.label;
        if (b.action === "choose") {
          const option = choice!.options.find((o) => o.id === b.option_id);
          if (!option) demoError(422, `'${label}': ${JSON.stringify(b.option_id ?? null)} is not one of this line's options.`);
          if (!option!.available) demoError(409, `'${option!.label}' can't be used for this line${option!.why_unavailable ? `: ${option!.why_unavailable.replace(/\.$/, "")}.` : "."}`);
          const automatic = choice!.chosen_by === "default" ? choice!.chosen : null;
          const reason = reasonOf(b.reason, option!.id !== automatic ? `Say why '${label}' is not left as it is: a reason is required.` : null);
          move(rec, { status: "edited", value: option!.id, ...(reason ? { reason } : {}) });
        } else if (b.action === "accept") {
          if (status(rec) !== "pending") already(label, status(rec));
          if (!rec.suggestion) demoError(409, `There is nothing to accept for '${label}': nothing was suggested and no value is set. Pick an option instead.`);
          const offered = choice!.options.find((o) => o.id === String(rec.suggestion!.value));
          if (!offered) demoError(422, `'${label}': ${JSON.stringify(rec.suggestion!.value)} is not one of this line's options.`);
          if (!offered!.available) demoError(409, `'${offered!.label}' can't be used for this line${offered!.why_unavailable ? `: ${offered!.why_unavailable.replace(/\.$/, "")}.` : "."}`);
          move(rec, { status: "accepted", value: rec.suggestion!.value });
        } else if (b.action === "reject") {
          if (status(rec) !== "pending") already(label, status(rec));
          move(rec, { status: "rejected", value: null, reason: reasonOf(b.reason, `Say why '${label}' is rejected: a reason is required.`) });
        } else if (b.action === "revert") revert(rec, label);
        else demoError(422, `'${String(b.action)}' is not an action on a choice.`);
        records.set(k, rec);
        return { line_key: params.key, target: "choice", id: params.target, side: null, decision: rec.decision, suggestion: rec.suggestion, history: [], value_history: rec.history };
      },
    },
    {
      method: "POST",
      path: new RegExp(`${base}\\/inputs\\/(?<target>.+)\\/(?<side>company|recomputed)$`),
      handle: ({ params, body }) => {
        const trace = traceOf(params.id, params.key);
        if (!trace) demoError(404, "No such calculation line. Reload the page to see the current lines.");
        // "<input>" or "<input>/<row id>": input ids hold no slash, row ids may.
        const [baseId, ...rest] = params.target.split("/");
        const whole = trace!.inputs[params.target];
        const input = whole ?? trace!.inputs[baseId];
        const row = whole ? undefined : input?.rows?.find((r) => r.id === rest.join("/"));
        if (!input || (!whole && !row)) demoError(404, "That input is not on this line. Reload the page.");
        const side = params.side as "company" | "recomputed";
        const holder: { company?: TraceSide; recomputed?: TraceSide } = row ?? input!;
        const own = holder[side];
        const sides = [own, holder.recomputed, holder.company, input!.recomputed, input!.company];
        const b = (body ?? {}) as { action?: string; value?: unknown; unit?: string; reason?: string };
        const k = keyOf(params.id, params.key, `input|${params.target}|${side}`);
        const rec = records.get(k) ?? { suggestion: own?.suggestion ?? null, decision: null, history: [] };
        const label = `${input!.label}${row ? ` · ${row.label}` : ""} (${side})`;
        // Like the backend: accept and edit need a decidable input (409, coded); reject and revert are never refused.
        if ((b.action === "accept" || b.action === "edit") && side === "recomputed" && input!.decidable === false) demoError(409, `'${label}' can't be changed for one line: ${input!.why_not ?? "this input cannot be decided for a line"}.`, "not_decidable");
        if (b.action === "edit") {
          const known = sides.filter((x) => x && x.value !== null && x.value !== undefined);
          // With no value on any side, a unit still says the input is a number.
          const numeric = known.length ? known.every((x) => typeof x!.value === "number") : sides.some((x) => Boolean(x?.unit));
          let value: number | string;
          if (typeof b.value === "number" && Number.isFinite(b.value) && Math.abs(b.value) <= 1e15 && numeric) value = b.value;
          else if (typeof b.value === "string" && b.value.trim() && b.value.trim().length <= MAX_TEXT) {
            const text = b.value.trim();
            if (numeric) {
              const n = Number(text.replace(/,/g, ""));
              if (!Number.isFinite(n) || Math.abs(n) > 1e15) demoError(422, `'${label}': enter a number.`);
              value = n;
            } else value = text;
          } else demoError(422, numeric ? `'${label}': enter a number.` : `'${label}': enter a value of at most ${MAX_TEXT} characters, without control characters.`);
          const unit = sides.find((x) => x?.unit)?.unit;
          if (numeric && b.unit && unit && b.unit.trim().toLowerCase() !== unit.toLowerCase()) demoError(422, `'${label}' is in ${unit}: enter the value in ${unit} (it was ${b.unit}).`);
          const reason = reasonOf(b.reason, side === "recomputed" ? `Say why the recomputed value of '${label}' is changed: a reason is required.` : null);
          move(rec, { status: "edited", value: value!, ...(unit && numeric ? { unit } : {}), kind: side === "recomputed" ? "reviewer_entered" : "company_input", ...(reason ? { reason } : {}) });
        } else if (b.action === "accept") {
          if (status(rec) !== "pending") already(label, status(rec));
          if (!rec.suggestion) demoError(409, `There is nothing to accept for '${label}': nothing was suggested and no value is set. Edit it to enter the value.`);
          move(rec, { status: "accepted", value: rec.suggestion!.value });
        } else if (b.action === "reject") {
          if (status(rec) !== "pending") already(label, status(rec));
          move(rec, { status: "rejected", value: null, reason: reasonOf(b.reason, `Say why '${label}' is rejected: a reason is required.`) });
        } else if (b.action === "revert") revert(rec, label);
        else demoError(422, `'${String(b.action)}' is not an action on an input.`);
        records.set(k, rec);
        if (params.target === "grid_region" && side === "company") {
          const d = rec.decision;
          setDemoCompanyRegion(params.id, params.key, d && (d.status === "edited" || d.status === "accepted") && typeof d.value === "string" ? d.value : null);
        }
        return { line_key: params.key, target: "input", id: params.target, side, decision: rec.decision, suggestion: rec.suggestion, history: [], value_history: rec.history };
      },
    },
  ];
}
