"use client";

import { Check } from "lucide-react";
import { useState, type ReactNode } from "react";

import { decideInput, type InputDecisionBody, type TraceInput } from "../../api/calcTrace";
import { ActionMenu, type ActionMenuEntry } from "../ActionMenu";
import { ReasonRow, SuggestionChip, useTraceActions } from "./TraceActions";
import { prettyUnit } from "./format";

/**
 * The decision state and the actions of a recomputed input's cell: a quiet check when accepted, an "Edited"
 * mark with who edited it, the automatic value struck through when rejected, and a "⋯" menu with the moves
 * the server allows from that state (Accept a suggestion, Edit, Reject, Revert). Edit keeps the unit fixed
 * and asks for a reason, as Methodology review's Reject does.
 */

/** Inputs a reviewer can decide on: references and constants, not sums of evidence or methodology settings. */
const DECIDABLE = new Set(["reference", "reviewer_entered", "constant"]);

type Mode = "edit" | "reject" | "accept" | null;

export function isDecidable(input: TraceInput | undefined): input is TraceInput {
  return Boolean(input && input.recomputed && DECIDABLE.has(input.kind));
}

export function InputActions({
  input,
  children,
  onOpenDocument,
}: {
  input: TraceInput;
  /** The cell's value, drawn by the panel. */
  children: ReactNode;
  onOpenDocument?: (documentId: string, valueId?: string) => void;
}) {
  const actions = useTraceActions();
  const [mode, setMode] = useState<Mode>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [value, setValue] = useState("");
  const side = input.recomputed;
  const decision = side?.decision && side.decision.status !== "pending" ? side.decision : null;
  const status = decision?.status ?? null;
  const unit = side?.unit ? prettyUnit(side.unit) : "";
  const numeric = typeof side?.value === "number";

  const mark =
    status === "accepted" ? (
      <span className="s1-cp-mark" title={`Accepted by ${decision?.by}`} aria-label={`Accepted by ${decision?.by}`} role="img">
        <Check className="s1-vw-ico" aria-hidden />
      </span>
    ) : status === "edited" ? (
      <span className="s1-cp-mark s1-cp-mark--word" tabIndex={0} title={`Edited by ${decision?.by}${decision?.reason ? `: ${decision.reason}` : ""}`}>
        Edited<span className="s1-cp-sr"> by {decision?.by}</span>
      </span>
    ) : status === "rejected" ? (
      <span className="s1-cp-mark s1-cp-mark--word" tabIndex={0} title={`Rejected by ${decision?.by}${decision?.reason ? `: ${decision.reason}` : ""}`}>
        Rejected<span className="s1-cp-sr"> by {decision?.by}</span>
      </span>
    ) : null;

  const cell = (
    <span className="s1-cp-decided">
      <span className={status === "rejected" ? "is-rejected" : undefined}>{children}</span>
      {mark}
    </span>
  );
  if (!actions || !side) return cell;

  const post = (body: InputDecisionBody) => actions.act(() => decideInput(actions.engagementId, actions.lineKey, input.id, "recomputed", body), { inline: true });
  const close = () => {
    setMode(null);
    setValue("");
  };
  const direct = async (body: InputDecisionBody) => {
    // Revert has no field to show a refusal in: the panel's notice says it.
    await actions.act(() => decideInput(actions.engagementId, actions.lineKey, input.id, "recomputed", body));
  };
  const suggestion = side.suggestion && !decision ? side.suggestion : null;
  const entries: ActionMenuEntry[] = [
    ...(suggestion ? [{ label: "Accept suggestion", disabled: actions.busy, action: () => setMode("accept") }] : []),
    { label: "Edit", disabled: actions.busy, action: () => { setValue(side.value === null || side.value === undefined ? "" : String(side.value)); setMode("edit"); } },
    ...(!decision ? [{ label: "Reject", disabled: actions.busy, action: () => setMode("reject") }] : []),
    ...(decision ? [{ label: "Revert", disabled: actions.busy, action: () => void direct({ action: "revert" }) }] : []),
  ];

  const parsed = numeric ? Number(value.replace(/,/g, "")) : NaN;
  const valueOk = numeric ? value.trim() !== "" && Number.isFinite(parsed) : value.trim() !== "";

  return (
    <>
      <span className="s1-cp-actioncell">
        {cell}
        <ActionMenu label={`Actions for ${input.label}`} entries={entries} isOpen={menuOpen} onOpenChange={setMenuOpen} />
      </span>
      {mode === "edit" ? (
        <ReasonRow
          label={`Reason: ${input.label}`}
          placeholder="Why is this value changed?"
          submitLabel="Save"
          validate={() => valueOk}
          onCancel={close}
          onSubmit={async (reason) => {
            const message = await post({ action: "edit", value: numeric ? parsed : value.trim(), ...(side.unit ? { unit: side.unit } : {}), reason });
            if (!message) close();
            return message;
          }}
        >
          <span className="s1-cp-valuefield">
            <input
              className="s1-mr-input"
              aria-label={`Value: ${input.label}`}
              inputMode={numeric ? "decimal" : undefined}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              autoFocus
            />
            {unit ? <span className="s1-muted">{unit}</span> : null}
          </span>
        </ReasonRow>
      ) : null}
      {mode === "reject" ? (
        <ReasonRow
          label={`Reason: ${input.label}`}
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
