"use client";

import { useState } from "react";

import { decideChoice, type TraceChoice, type TraceChoiceOption, type TraceTag } from "../../api/calcTrace";
import { ReasonRow, SuggestionChip, useTraceActions } from "./TraceActions";

const TAG_TEXT: Partial<Record<TraceTag, string>> = { detected_from_evidence: "Detected from the evidence", not_used_for_this_line: "Not used for this line" };

/** The option used when nobody has decided: the backend's `default_option`. Any other pick needs a reason. */
const automaticOption = (choice: TraceChoice): string | null => (choice.chosen_by === "default" ? choice.chosen : null);

type Mode = { kind: "choose"; option: TraceChoiceOption } | { kind: "reject" } | null;

/**
 * The options of a choice, the one used marked. Where the reviewer can act, an enabled option is a
 * button that chooses it (a reason is asked for when it is not the automatic one), a disabled option
 * says why in its tooltip, and a decided choice says who decided and can be reverted. A pending AI
 * suggestion is a chip with Accept; it never sets the chosen option.
 */
export function ChoicePills({
  choice,
  compact = false,
  onOpenDocument,
}: {
  choice: TraceChoice;
  compact?: boolean;
  onOpenDocument?: (documentId: string, valueId?: string) => void;
}) {
  const actions = useTraceActions();
  const [mode, setMode] = useState<Mode>(null);
  const editable = Boolean(actions);
  const decision = choice.decision && choice.decision.status !== "pending" ? choice.decision : null;
  const suggested = !decision && choice.suggestion ? choice.suggestion : null;
  const suggestedOption = suggested ? choice.options.find((o) => o.id === String(suggested.value)) : undefined;

  const post = (body: Parameters<typeof decideChoice>[3], inline = false) =>
    actions ? actions.act(() => decideChoice(actions.engagementId, actions.lineKey, choice.id, body), { inline }) : Promise.resolve(null);

  function pick(option: TraceChoiceOption) {
    if (!option.available || option.id === choice.chosen) return;
    if (option.id === automaticOption(choice)) void post({ action: "choose", option_id: option.id });
    else setMode({ kind: "choose", option });
  }

  return (
    <div className="s1-cp-pills" role="group" aria-label={choice.label}>
      {compact ? null : <span className="s1-cp-pills__label">{choice.label}</span>}
      {choice.options.map((o) => {
        const chosen = o.id === choice.chosen;
        const why = o.why_unavailable ?? "not available for this line";
        const className = `s1-cp-pill${chosen ? " is-chosen" : ""}${o.available ? "" : " is-unavailable"}`;
        const tag = o.detection && TAG_TEXT[o.detection] ? <span className="s1-cp-pill__tag"> · {TAG_TEXT[o.detection]}</span> : null;
        if (!editable) {
          return (
            <span key={o.id} className={className} aria-current={chosen ? "true" : undefined} title={o.available ? undefined : why}>
              {o.label}
              {o.available ? null : <span className="s1-cp-sr"> (not available: {why})</span>}
              {tag}
            </span>
          );
        }
        return (
          <button
            key={o.id}
            type="button"
            className={`${className} is-button`}
            aria-pressed={chosen}
            aria-disabled={!o.available || undefined}
            disabled={actions?.busy && o.available && !chosen}
            title={o.available ? undefined : why}
            onClick={() => pick(o)}
          >
            {o.label}
            {o.available ? null : <span className="s1-cp-sr"> (not available: {why})</span>}
            {tag}
          </button>
        );
      })}
      {editable && suggested ? (
        <span className="s1-cp-suggest">
          <SuggestionChip suggestion={suggested} onOpenDocument={onOpenDocument} />
          <span className="s1-muted">{suggestedOption ? suggestedOption.label : String(suggested.value)}</span>
          {suggestedOption?.available === false ? null : (
            <button type="button" className="s1-button s1-button--compact" aria-label={`Accept: ${choice.label}`} disabled={actions?.busy} onClick={() => void post({ action: "accept" })}>
              Accept
            </button>
          )}
          <button type="button" className="s1-button s1-button--compact" aria-label={`Reject suggestion: ${choice.label}`} disabled={actions?.busy} onClick={() => setMode({ kind: "reject" })}>
            Reject
          </button>
        </span>
      ) : null}
      {editable && decision ? (
        <span className="s1-cp-change s1-muted">
          {decision.status === "rejected" ? "Suggestion rejected" : decision.status === "accepted" ? "Accepted" : "Chosen"} by {decision.by}
          {decision.reason ? ` · ${decision.reason}` : ""}
          {" · "}
          <button type="button" className="s1-mr-link" aria-label={`Revert: ${choice.label}`} disabled={actions?.busy} onClick={() => void post({ action: "revert" })}>
            Revert
          </button>
        </span>
      ) : null}
      {mode?.kind === "choose" ? (
        <ReasonRow
          label={`Reason: ${choice.label}`}
          placeholder="Why is this not the automatic choice?"
          submitLabel={`Use ${mode.option.label}`}
          onCancel={() => setMode(null)}
          onSubmit={async (reason) => {
            const message = await post({ action: "choose", option_id: mode.option.id, reason }, true);
            if (!message) setMode(null);
            return message;
          }}
        />
      ) : null}
      {mode?.kind === "reject" ? (
        <ReasonRow
          label={`Reason: ${choice.label}`}
          placeholder="Why is this wrong?"
          submitLabel="Reject"
          onCancel={() => setMode(null)}
          onSubmit={async (reason) => {
            const message = await post({ action: "reject", reason }, true);
            if (!message) setMode(null);
            return message;
          }}
        />
      ) : null}
    </div>
  );
}
