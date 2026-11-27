"use client";

import { useState } from "react";

import type { EngagementConfig } from "../types";
import type { AskOrigin, RequestType } from "../types/requests";
import { REQUEST_TYPES } from "../types/requests";
import { Dialog } from "./Dialog";
import { Dropdown } from "./Dropdown";
import { IconSend } from "./icons";
import { problemText, settle, type MaybePromise } from "../requests/maybePromise";
import type { AskDraft } from "../requests/requestsStore";
import { readablePeriod } from "../utils/formatPeriod";

/**
 * The Add to requests window, shared by the Evidence Workspace row and the
 * Extraction Review value card (the spec's "same window, one difference in the
 * pre-fill"). The caller supplies the stamped header line, the pre-selected
 * type, and the pre-filled "what is needed" text; the modal returns a complete
 * AskDraft for the single persist function.
 */
export interface AddToRequestsTarget {
  origin: AskOrigin;
  documentId?: string | null;
  fieldKey?: string | null;
  itemLabel: string;
  facilityName: string | null;
  period: string | null;
  arrival?: string | null;
  sourcePage?: number | null;
  /** The stamped header line under the title (differs per screen). */
  headerLine: string;
  defaultType: RequestType;
  /** Seed text for "what is needed"; the verifier writes the reason after it. */
  prefill: string;
}

export function AddToRequestsModal({
  target,
  engagement,
  onCancel,
  onAdd,
  serverRecordsActor = false,
}: {
  target: AddToRequestsTarget;
  engagement: EngagementConfig;
  onCancel: () => void;
  /** May answer after the server has: the window waits, and keeps its text if the save fails. */
  onAdd: (draft: AskDraft) => MaybePromise<unknown>;
  /** The server records the signed-in user as the person who raised it, so no one is picked here. */
  serverRecordsActor?: boolean;
}) {
  const [type, setType] = useState<RequestType>(target.defaultType);
  const [whatIsNeeded, setWhatIsNeeded] = useState(target.prefill);
  const team = engagement.engagementTeam ?? [];
  // The signed-in person by default; the Setup team list only adds choices.
  const me = engagement.signedInLogin
    ? { name: engagement.signedInName ?? engagement.signedInLogin, login: engagement.signedInLogin }
    : null;
  const signed = team.find((m) => m.login === engagement.signedInLogin) ?? me ?? team[0] ?? { name: "You", login: "you" };
  const [raisedBy, setRaisedBy] = useState(signed.login);
  const [pending, setPending] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  // While the save is on its way the window cannot be closed: an answer that came back to a
  // closed window would have nowhere to go, and a window opened in its place could be submitted twice.
  const close = () => {
    if (!pending) onCancel();
  };

  const about: [string, string][] = [
    ["Item", target.itemLabel],
    ["Facility", target.facilityName ?? "Not yet known"],
    ["Period", target.period ? readablePeriod(target.period) : "Not stated"],
    ...(target.sourcePage ? ([["Page", String(target.sourcePage)]] as [string, string][]) : []),
  ];
  const add = () => {
    if (pending) return;
    const chosen = serverRecordsActor ? signed : ((team.length ? team : [signed]).find((m) => m.login === raisedBy) ?? signed);
    const draft: AskDraft = {
      origin: target.origin,
      documentId: target.documentId ?? null,
      fieldKey: target.fieldKey ?? null,
      itemLabel: target.itemLabel,
      facilityName: target.facilityName,
      period: target.period,
      arrival: target.arrival ?? null,
      sourcePage: target.sourcePage ?? null,
      type,
      whatIsNeeded,
      raisedByName: chosen.name,
      raisedByLogin: chosen.login,
    };
    setPending(true);
    setProblem(null);
    settle(
      () => onAdd(draft),
      () => setPending(false),
      (e) => {
        setPending(false);
        setProblem(problemText(e));
      }
    );
  };

  return (
    <Dialog
      size="md"
      closeOnScrim
      closeDisabled={pending}
      icon={<IconSend size={18} />}
      title="Add to requests"
      context="Saved to Evidence requests as not yet sent. Nothing is emailed from here."
      onClose={close}
    >
      <dl className="s1-req-add__facts" title={target.headerLine}>
        {about.map(([k, v]) => (
          <div key={k} className="s1-req-add__fact">
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>

      <form
        className="s1-req-add__form"
        onSubmit={(e) => {
          e.preventDefault();
          add();
        }}
      >
        <div className="s1-req-add__row">
          <div className="s1-req-add__field">
            <span id="atr-type-label" className="s1-field-label">
              Request type
            </span>
            <Dropdown
              value={type}
              onChange={(v) => setType(v as RequestType)}
              options={REQUEST_TYPES.map((t) => ({ value: t.value, label: t.label }))}
              labelId="atr-type-label"
            />
          </div>
          {serverRecordsActor ? null : (
            <div className="s1-req-add__field">
              <span id="atr-raisedby-label" className="s1-field-label">
                Raised by
              </span>
              <Dropdown
                value={raisedBy}
                onChange={(v) => setRaisedBy(v)}
                options={(team.length ? team : [signed]).map((m) => ({ value: m.login, label: m.name }))}
                labelId="atr-raisedby-label"
              />
            </div>
          )}
        </div>

        <label className="s1-req-add__field">
          <span className="s1-field-label">What is needed</span>
          <textarea className="s1-textarea s1-req-add__need" autoFocus rows={3} value={whatIsNeeded} onChange={(e) => setWhatIsNeeded(e.target.value)} />
        </label>

        {problem ? (
          <p className="s1-system-banner" role="alert">
            {problem}
          </p>
        ) : null}

        <div className="s1-modal__actions">
          <button className="s1-button" type="button" disabled={pending} onClick={close}>
            Cancel
          </button>
          <button className="s1-button s1-button--pri" type="submit" disabled={!whatIsNeeded.trim() || pending}>
            Add to requests
          </button>
        </div>
      </form>
    </Dialog>
  );
}
