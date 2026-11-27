"use client";

import { ChevronRight } from "lucide-react";

import type {
  LineTrace,
  TraceBlock,
  TraceChoice,
  TraceColumn,
  TraceInput,
  TraceInputRow,
  TraceOperand,
  TraceOperation,
  TraceStep,
} from "../../api/calcTrace";
import { differenceText, operandText, prettyUnit } from "./format";
import { TraceSourceNote } from "./TraceSourceNote";

/**
 * The step-by-step calculation of one line, drawn from its trace (api/calcTrace.ts): method pills,
 * Steps 1 to 4 and Results, each block a Company row and a Recomputed row of `a × b × c = result`.
 * It draws what the trace says and calculates nothing: every number, difference and source is the
 * backend's. Read-only; reviewer actions come later.
 */

type Side = "company" | "recomputed";
type OpenDocument = (documentId: string, valueId?: string) => void;
type Inputs = Record<string, TraceInput>;

const TAG_TEXT = { detected_from_evidence: "Detected from the evidence", not_used_for_this_line: "Not used for this line" } as const;
const REVIEW_TEXT: Record<string, string> = {
  accepted: "Accepted",
  edited: "Edited by reviewer",
  suggested: "Awaiting review",
  awaiting_review: "Awaiting review",
  rejected: "Rejected",
  reference: "Reference",
  derived: "Derived",
};

const SIDE_NAME: Record<Side, string> = { company: "Company", recomputed: "Recomputed" };

/* ------------------------------------------ operands ------------------------------------------ */

/** A value on a side that is still awaiting a reviewer is never shown as a number. */
function isPending(operand: TraceOperand, inputs: Inputs, side: Side): boolean {
  if (side !== "recomputed" || !operand.input_id) return false;
  const status = inputs[operand.input_id]?.recomputed?.status;
  return status === "awaiting_review" || status === "suggested";
}

function OperandValue({
  operand,
  column,
  side,
  inputs,
  withDifference,
  isResult = false,
  onOpenDocument,
}: {
  operand: TraceOperand;
  /** A boxed result cell: the only operand (with the Step 1 total) that carries a numeric difference, as on the boards. */
  isResult?: boolean;
  column?: TraceColumn;
  side: Side;
  inputs: Inputs;
  /** False when the company side has no value: nothing to differ from. */
  withDifference: boolean;
  onOpenDocument?: OpenDocument;
}) {
  const text = isPending(operand, inputs, side) ? null : operandText(operand, column);
  if (text === null) return <em className="s1-muted">{side === "company" ? "not reported" : "Awaiting review"}</em>;
  const input = operand.input_id ? inputs[operand.input_id] : undefined;
  const diff =
    side === "recomputed" && withDifference
      ? operand.differs === true && typeof operand.value === "string"
        ? "differs"
        : isResult
          ? differenceText(operand.difference, operand.value, column?.display)
          : null
      : null;
  return (
    <>
      {input ? <TraceSourceNote label={text} source={input[side]?.source} side={side} onOpenDocument={onOpenDocument} /> : text}
      {diff ? <span className="s1-cp-diff"> ({diff})</span> : null}
    </>
  );
}

/* ------------------------------------------ one block ------------------------------------------ */

/** How many decimals a quantity actually has, 0 to 2. */
function decimalsPresent(v: unknown): number {
  if (typeof v !== "number" || !Number.isFinite(v)) return 0;
  const hundredths = Math.round(Math.abs(v) * 100);
  if (hundredths % 100 === 0) return 0;
  return hundredths % 10 === 0 ? 1 : 2;
}

const isSingle = (op: TraceOperation) => op.terms.length === 1 && op.terms[0].operand.column === op.result.column;
const hasValue = (op: TraceOperation | undefined) => Boolean(op) && op?.result.value !== null && op?.result.value !== undefined;

function OperationTable({ block, name, inputs, onOpenDocument }: { block: TraceBlock; name: string; inputs: Inputs; onOpenDocument?: OpenDocument }) {
  const columns = new Map(block.columns.map((c) => [c.key, c]));
  const shape = block.recomputed ?? block.company;
  if (!shape) return <p className="s1-muted s1-cp-block__empty">Not calculated.</p>;
  const single = isSingle(shape);
  const resultColumn = columns.get(shape.result.column);
  const label = (key: string) => columns.get(key)?.label ?? key;
  const resultUnit = resultColumn?.is_result && resultColumn.unit ? ` (${prettyUnit(resultColumn.unit)})` : "";
  const span = single ? 1 : shape.terms.length * 2 + 1;
  // No company number, or no company operation at all: the recomputed row shows no difference.
  const companyHasValue = hasValue(block.company);

  const row = (side: Side, op: TraceOperation | undefined) => {
    const className = side === "company" ? "s1-cp-co" : "s1-cp-rec";
    if (!op) {
      return (
        <tr key={side} className={className}>
          <td>{SIDE_NAME[side]}</td>
          <td colSpan={span}>
            <em className="s1-muted">{side === "company" ? "not reported" : "Awaiting review"}</em>
          </td>
        </tr>
      );
    }
    const withDifference = side === "recomputed" && companyHasValue;
    const cell = (operand: TraceOperand, isResult = false) => (
      <OperandValue operand={operand} column={columns.get(operand.column)} side={side} inputs={inputs} withDifference={withDifference} isResult={isResult} onOpenDocument={onOpenDocument} />
    );
    const own = isSingle(op);
    return (
      <tr key={side} className={className}>
        <td>{SIDE_NAME[side]}</td>
        {own
          ? null
          : op.terms.flatMap((t, i) => [
              i > 0 ? (
                <td key={`op${i}`} className="s1-cp-op">
                  {t.op ?? ""}
                </td>
              ) : null,
              <td key={`v${i}`} className="s1-vw-num">
                {cell(t.operand)}
              </td>,
            ])}
        {own ? null : <td className="s1-cp-op">=</td>}
        <td className="s1-vw-num s1-cp-out">{cell(op.result, true)}</td>
      </tr>
    );
  };

  return (
    <div className="s1-vw-scroll">
      <table className="s1-vw-steps s1-cp-grid s1-cp-ops" aria-label={name}>
        <thead>
          <tr>
            <th />
            {single
              ? null
              : shape.terms.flatMap((t, i) => [
                  i > 0 ? <th key={`o${i}`} /> : null,
                  <th key={`h${i}`} className="s1-vw-num">
                    {label(t.operand.column)}
                  </th>,
                ])}
            {single ? null : <th />}
            <th className="s1-vw-num s1-cp-out-head">
              {label(shape.result.column)}
              {resultUnit ? <span className="s1-cp-unit">{resultUnit}</span> : null}
            </th>
          </tr>
        </thead>
        <tbody>
          {row("company", block.company)}
          {row("recomputed", block.recomputed)}
        </tbody>
      </table>
    </div>
  );
}

/** A summed input (months, deliveries, meters): its parts, then the total with both sides. */
function RowsTable({ block, input, name, onOpenDocument }: { block: TraceBlock; input: TraceInput; name: string; onOpenDocument?: OpenDocument }) {
  const base = block.columns.find((c) => c.key === block.recomputed?.result.column);
  // Quantities are shown as they are: the most decimals any of this block's values has, at most two.
  const values = [
    ...(input.rows ?? []).flatMap((r) => [r.company?.value, r.recomputed?.value]),
    block.company?.result.value,
    block.recomputed?.result.value,
    block.recomputed?.result.difference,
  ];
  const column = base ? { ...base, display: { dp: Math.max(0, ...values.map(decimalsPresent)) } } : base;
  const cellText = (side: Side, r: TraceInputRow) => {
    const s = r[side];
    if (!s || s.value === null || s.value === undefined) return null;
    if (side === "recomputed" && (s.status === "awaiting_review" || s.status === "suggested")) return null;
    return operandText({ column: column?.key ?? "", value: s.value, unit: s.unit }, column);
  };
  const total = (side: Side, op: TraceOperation | undefined) => {
    if (!op) return <em className="s1-muted">{side === "company" ? "not reported" : "Awaiting review"}</em>;
    return <OperandValue operand={op.result} column={column} side={side} inputs={{}} withDifference={side === "recomputed" && hasValue(block.company)} isResult onOpenDocument={onOpenDocument} />;
  };
  return (
    <div className="s1-vw-scroll">
      <table className="s1-vw-steps s1-cp-grid s1-cp-rows" aria-label={name}>
        <thead>
          <tr>
            <th>Record</th>
            <th>Review</th>
            <th className="s1-vw-num">Company-reported</th>
            <th className="s1-vw-num s1-cp-rec">Recomputed (accepted values)</th>
          </tr>
        </thead>
        <tbody>
          {(input.rows ?? []).map((r) => {
            const co = cellText("company", r);
            const rc = cellText("recomputed", r);
            return (
              <tr key={r.id}>
                <td className="s1-cp-wrap">{r.label}</td>
                <td>{r.recomputed ? (REVIEW_TEXT[r.recomputed.status] ?? "") : ""}</td>
                <td className="s1-vw-num">{co ?? <em className="s1-muted">not reported</em>}</td>
                <td className="s1-vw-num s1-cp-rec">
                  {rc === null ? (
                    <em className="s1-muted">Awaiting review</em>
                  ) : (
                    <>
                      <TraceSourceNote label={rc} source={r.recomputed?.source} onOpenDocument={onOpenDocument} />
                    </>
                  )}
                </td>
              </tr>
            );
          })}
          <tr className="s1-vw-steps__total">
            <td colSpan={2}>{block.label}</td>
            <td className="s1-vw-num">{total("company", block.company)}</td>
            <td className="s1-vw-num s1-cp-rec">{total("recomputed", block.recomputed)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function BlockView({ block, step, trace, onOpenDocument }: { block: TraceBlock; step: TraceStep; trace: LineTrace; onOpenDocument?: OpenDocument }) {
  const name = `${step.title} · ${block.label}`;
  const inputs = trace.inputs ?? {};
  // A block whose result is a summed input (twelve monthly bills, any number of parts) is drawn as that
  // input's rows and a total, never as a row of terms: the company gives one figure for the whole.
  const sumId = (block.recomputed ?? block.company)?.result.input_id;
  const summed = sumId ? inputs[sumId] : undefined;
  const choice = block.choice_id ? (trace.choices ?? []).find((c) => c.id === block.choice_id) : undefined;
  const unused = block.tag === "not_used_for_this_line";
  return (
    <div className={`s1-cp-block${unused ? " is-unused" : ""}`}>
      {step.blocks.length > 1 || block.tag || choice ? (
        <div className="s1-cp-block__head">
          <h6>{block.label}</h6>
          {block.tag && TAG_TEXT[block.tag] ? <span className="s1-cp-tag">{TAG_TEXT[block.tag]}</span> : null}
          {choice ? <ChoicePills choice={choice} compact /> : null}
        </div>
      ) : null}
      {summed?.rows?.length ? (
        <RowsTable block={block} input={summed} name={name} onOpenDocument={onOpenDocument} />
      ) : (
        <OperationTable block={block} name={name} inputs={inputs} onOpenDocument={onOpenDocument} />
      )}
    </div>
  );
}

function StepView({ step, trace, onOpenDocument }: { step: TraceStep; trace: LineTrace; onOpenDocument?: OpenDocument }) {
  return (
    <details className="s1-cp-step s1-cp-tstep" open>
      <summary className="s1-cp-step__head">
        <ChevronRight className="s1-vw-ico s1-cp-tstep__chev" aria-hidden />
        <h5>{step.title}</h5>
        {step.note ? <span className="s1-muted">{step.note}</span> : null}
      </summary>
      <div className="s1-cp-tstep__body">
        {(step.blocks ?? []).map((b) => (
          <BlockView key={b.id} block={b} step={step} trace={trace} onOpenDocument={onOpenDocument} />
        ))}
      </div>
    </details>
  );
}

/* ------------------------------------------ method pills ------------------------------------------ */

/** The options of a choice, the one used marked. Read-only: a choice is changed elsewhere. */
export function ChoicePills({ choice, compact = false }: { choice: TraceChoice; compact?: boolean }) {
  return (
    <div className="s1-cp-pills" role="group" aria-label={choice.label}>
      {compact ? null : <span className="s1-cp-pills__label">{choice.label}</span>}
      {choice.options.map((o) => {
        const chosen = o.id === choice.chosen;
        const why = o.why_unavailable ?? "not available for this line";
        return (
          <span
            key={o.id}
            className={`s1-cp-pill${chosen ? " is-chosen" : ""}${o.available ? "" : " is-unavailable"}`}
            aria-current={chosen ? "true" : undefined}
            title={o.available ? undefined : why}
          >
            {o.label}
            {o.available ? null : <span className="s1-cp-sr"> (not available: {why})</span>}
            {o.detection && TAG_TEXT[o.detection] ? <span className="s1-cp-pill__tag"> · {TAG_TEXT[o.detection]}</span> : null}
          </span>
        );
      })}
    </div>
  );
}

/* ------------------------------------------ the panel ------------------------------------------ */

export function TracePanel({ trace, onOpenDocument }: { trace: LineTrace; onOpenDocument?: OpenDocument }) {
  const choices = trace.choices ?? [];
  const placed = new Set((trace.steps ?? []).flatMap((s) => (s.blocks ?? []).map((b) => b.choice_id)));
  const method = choices.find((c) => c.id === "method");
  const route = method?.options.find((o) => o.id === method.chosen);
  // A choice with one option has nothing to pick: the route line already says it.
  const loose = choices.filter((c) => !placed.has(c.id) && c.options.length > 1);
  return (
    <div className="s1-cp-trace" data-trace-state={trace.state}>
      {route ? (
        <p className="s1-cp-route">
          <span className="s1-muted">Route: </span>
          {route.label}
        </p>
      ) : null}
      {loose.length ? (
        <div className="s1-cp-pillrow">
          {loose.map((c) => (
            <ChoicePills key={c.id} choice={c} />
          ))}
        </div>
      ) : null}
      {(trace.blocking ?? []).map((b) => (
        <p key={b.input_id} className="s1-cp-note" role="status">
          Awaiting review: {b.message}
        </p>
      ))}
      {trace.state === "partial" ? (
        <p className="s1-cp-note" role="status">
          Part of this line could not be calculated; what could be is shown.
        </p>
      ) : null}
      {(trace.flags ?? []).includes("company_total_is_reported_figure") ? (
        <p className="s1-cp-note" role="status">
          The company&apos;s total is the figure entered for this line, not the sum of its gases.
        </p>
      ) : null}
      {trace.method_mismatch ? (
        <p className="s1-cp-note" role="status">
          The company used another method, so only the outputs are compared.
        </p>
      ) : null}
      {(trace.steps ?? []).map((s) => (
        <StepView key={s.id} step={s} trace={trace} onOpenDocument={onOpenDocument} />
      ))}
    </div>
  );
}
