"use client";

import { useEffect, useState } from "react";

import type { EngagementConfig } from "../types";
import type { AskOrigin, RequestType } from "../types/requests";
import { REQUEST_TYPES } from "../types/requests";
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

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !pending) onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel, pending]);

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
    <div className="s1-modal-scrim" role="presentation" onClick={close}>
      <div
        className="s1-modal s1-atr"
        role="dialog"
        aria-modal="true"
        aria-labelledby="s1-atr-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="s1-atr__head">
          <h2 id="s1-atr-title" className="s1-atr__title">
            Add to requests
          </h2>
          <button className="s1-atr__close" type="button" aria-label="Close" disabled={pending} onClick={close}>
            ×
          </button>
        </div>

        <dl className="s1-atr__about" title={target.headerLine}>
          {about.map(([k, v]) => (
            <div key={k} className="s1-atr__fact">
              <dt>{k}</dt>
              <dd>{v}</dd>
            </div>
          ))}
        </dl>

        <form
          className="s1-atr__form"
          onSubmit={(e) => {
            e.preventDefault();
            add();
          }}
        >
          <div className="s1-atr__row">
            <label className="s1-modal__field">
              <span>Request type</span>
              <select value={type} onChange={(e) => setType(e.target.value as RequestType)}>
                {REQUEST_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
            </label>
            {serverRecordsActor ? null : (
              <label className="s1-modal__field">
                <span>Raised by</span>
                <select value={raisedBy} onChange={(e) => setRaisedBy(e.target.value)}>
                  {(team.length ? team : [signed]).map((m) => (
                    <option key={m.login} value={m.login}>
                      {m.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>

          <label className="s1-modal__field">
            <span>What is needed</span>
            <textarea autoFocus rows={4} value={whatIsNeeded} onChange={(e) => setWhatIsNeeded(e.target.value)} />
          </label>

          {problem ? (
            <p className="s1-system-banner" role="alert">
              {problem}
            </p>
          ) : null}

          <div className="s1-atr__foot">
            <p className="s1-muted s1-modal__note">Saved to Evidence requests as not yet sent. Nothing is emailed from here.</p>
            <div className="s1-modal__actions">
              <button className="s1-button" type="button" disabled={pending} onClick={close}>
                Cancel
              </button>
              <button className="s1-button s1-button--pri" type="submit" disabled={!whatIsNeeded.trim() || pending}>
                Add to requests
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}
