"use client";

import { ProvenanceLabel } from "../ProvenanceLabel";
import { useState, type ReactNode } from "react";

import { decideInput, type InputDecisionBody, type TraceInput, type TraceInputRow, type TraceSide } from "../../api/calcTrace";
import { ActionMenu, type ActionMenuEntry } from "../ActionMenu";
import { NotAppliedNote, useNotApplied } from "./NotApplied";
import { ReasonRow, SuggestionChip, useTraceActions } from "./TraceActions";
import { prettyUnit } from "./format";

/**
 * The decision state and the actions of a recomputed input's cell: a quiet check when accepted, an "Edited"
 * mark with who edited it, the automatic value struck through when rejected, and a "⋯" menu with the moves
 * the server allows from that state (Accept a suggestion, Edit, Reject, Revert). Edit keeps the unit fixed
 * and asks for a reason, as Methodology review's Reject does.
 */

type Mode = "edit" | "reject" | "accept" | null;

const PLAIN = /^-?(\d+(\.\d+)?|\.\d+)$/;
const GROUPED = /^-?\d{1,3}(,\d{3})+(\.\d+)?$/;

/** A number as typed: a plain number or valid thousands grouping. "1,5" is ambiguous (a decimal comma?) and refused. */
export function parseEntered(text: string): { value: number } | { error: string } {
  const t = text.trim();
  if (!t) return { error: "" };
  if (PLAIN.test(t)) return { value: Number(t) };
  if (GROUPED.test(t)) return { value: Number(t.replace(/,/g, "")) };
  return { error: t.includes(",") ? "Use a point for decimals" : "Enter a number" };
}

/** Numeric when any side holds a number or the trace gives a unit: an input with no value yet stays a number. */
function isNumeric(sides: (TraceSide | undefined)[]): boolean {
  return sides.some((s) => typeof s?.value === "number" || Boolean(s?.unit));
}
const unitOf = (sides: (TraceSide | undefined)[]): string | undefined => sides.find((s) => s?.unit)?.unit || undefined;

export function InputActions({
  input,
  row,
  children,
  onOpenDocument,
}: {
  input: TraceInput;
  /** One record of a summed input: decided on its own, and decidable exactly when its input is. */
  row?: TraceInputRow;
  /** The cell's value, drawn by the panel. */
  children: ReactNode;
  onOpenDocument?: (documentId: string, valueId?: string) => void;
}) {
  const actions = useTraceActions();
  const [mode, setMode] = useState<Mode>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [value, setValue] = useState("");
  const side = row ? row.recomputed : input.recomputed;
  const targetId = row ? `${input.id}/${row.id}` : input.id;
  const label = row ? `${input.label} · ${row.label}` : input.label;
  const sides = [side, row?.company, input.recomputed, input.company];
  const notApplied = useNotApplied("input", targetId);
  const decision = side?.decision && side.decision.status !== "pending" ? side.decision : null;
  const status = decision?.status ?? null;
  const rawUnit = unitOf(sides);
  const unit = rawUnit ? prettyUnit(rawUnit) : "";
  const numeric = isNumeric(sides);

  const mark = decision ? (
    <span className="s1-cp-mark s1-cp-mark--word" tabIndex={0}>
      <ProvenanceLabel
        compact
        source="human"
        action={status === "edited" ? "edited" : status === "rejected" ? "rejected" : "accepted"}
        by={decision.by}
        at={decision.at}
        detail={decision.reason || undefined}
      />
    </span>
  ) : null;

  // Only the trace's own word decides whether a reviewer can act: `decidable` is true. Otherwise the value says why not.
  const decidable = input.decidable === true;
  const cell = (
    <span className="s1-cp-decided" title={!decidable && input.why_not ? `Can't be changed: ${input.why_not}` : undefined}>
      <span className={status === "rejected" ? "is-rejected" : undefined}>{children}</span>
      {mark}
    </span>
  );
  const note = <NotAppliedNote entries={notApplied} />;
  if (!actions || !side || !decidable) return <>{cell}{note}</>;

  const post = (body: InputDecisionBody, entered?: string) => actions.act(() => decideInput(actions.engagementId, actions.lineKey, targetId, "recomputed", body), { inline: true, entered });
  const close = () => {
    setMode(null);
    setValue("");
  };
  const direct = async (body: InputDecisionBody) => {
    // Revert has no field to show a refusal in: the panel's notice says it.
    await actions.act(() => decideInput(actions.engagementId, actions.lineKey, targetId, "recomputed", body));
  };
  const suggestion = side.suggestion && !decision ? side.suggestion : null;
  const entries: ActionMenuEntry[] = [
    ...(suggestion ? [{ label: "Accept suggestion", disabled: actions.busy, action: () => setMode("accept") }] : []),
    { label: "Edit", disabled: actions.busy, action: () => { setValue(side.value === null || side.value === undefined ? "" : String(side.value)); setMode("edit"); } },
    ...(!decision ? [{ label: "Reject", disabled: actions.busy, action: () => setMode("reject") }] : []),
    ...(decision ? [{ label: "Revert", disabled: actions.busy, action: () => void direct({ action: "revert" }) }] : []),
  ];

  const entered = numeric ? parseEntered(value) : null;
  const parsed = entered && "value" in entered ? entered.value : NaN;
  const valueOk = numeric ? Number.isFinite(parsed) : value.trim() !== "";
  const valueError = entered && "error" in entered ? entered.error : "";

  return (
    <>
      <span className="s1-cp-actioncell">
        {cell}
        <ActionMenu label={`Actions for ${label}`} entries={entries} isOpen={menuOpen} onOpenChange={setMenuOpen} />
      </span>
      {note}
      {mode === "edit" ? (
        <ReasonRow
          label={`Reason: ${label}`}
          placeholder="Why is this value changed?"
          submitLabel="Save"
          validate={() => valueOk}
          onCancel={close}
          onSubmit={async (reason) => {
            const message = await post({ action: "edit", value: numeric ? parsed : value.trim(), ...(rawUnit ? { unit: rawUnit } : {}), reason }, value.trim());
            if (!message) close();
            return message;
          }}
        >
          <span className="s1-cp-valuefield">
            <input
              className="s1-mr-input"
              aria-label={`Value: ${label}`}
              inputMode={numeric ? "decimal" : undefined}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              autoFocus
            />
            {unit ? <span className="s1-muted">{unit}</span> : null}
            {valueError ? (
              <span className="s1-cp-reason__error" role="alert">
                {valueError}
              </span>
            ) : null}
          </span>
        </ReasonRow>
      ) : null}
      {mode === "reject" ? (
        <ReasonRow
          label={`Reason: ${label}`}
          placeholder="Why is this wrong?"
          submitLabel="Reject"
          onCancel={close}
          onSubmit={async (reason) => {
            const message = await post({ action: "reject", reason });
            if (!message) close();
            return message;
          }}
        />
      ) : null}
      {mode === "accept" && suggestion ? (
        <span className="s1-cp-reason">
          <SuggestionChip suggestion={suggestion} onOpenDocument={onOpenDocument} />
          <span>
            {String(suggestion.value)}
            {suggestion.unit ? ` ${prettyUnit(suggestion.unit)}` : ""}
          </span>
          <span className="s1-mr-actions">
            <button
              type="button"
              className="s1-button s1-button--compact s1-button--pri"
              disabled={actions.busy}
              onClick={async () => {
                const message = await post({ action: "accept" });
                if (!message) close();
              }}
            >
              Accept
            </button>
            <button type="button" className="s1-button s1-button--compact" onClick={close}>
              Cancel
            </button>
          </span>
        </span>
      ) : null}
    </>
  );
}
