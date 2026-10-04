"use client";

import { useState } from "react";

import type { EngagementConfig } from "../types";
import type { AskOrigin, RequestType } from "../types/requests";
import { REQUEST_TYPES } from "../types/requests";
import type { AskDraft } from "../requests/requestsStore";

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
}: {
  target: AddToRequestsTarget;
  engagement: EngagementConfig;
  onCancel: () => void;
  onAdd: (draft: AskDraft) => void;
}) {
  const [type, setType] = useState<RequestType>(target.defaultType);
  const [whatIsNeeded, setWhatIsNeeded] = useState(target.prefill);
  const team = engagement.engagementTeam ?? [];
  const signed = team.find((m) => m.login === engagement.signedInLogin) ?? team[0] ?? { name: "You", login: "you" };
  const [raisedBy, setRaisedBy] = useState(signed.login);

  return (
    <div className="s1-modal-scrim" role="presentation" onClick={onCancel}>
      <div
        className="s1-modal"
        role="dialog"
        aria-modal="true"
        aria-label="Add to requests"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="s1-modal__head">
          <strong>Add to requests</strong>
          <div className="s1-muted">{target.headerLine}</div>
        </div>

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

        <label className="s1-modal__field">
          <span>What is needed</span>
          <textarea rows={3} value={whatIsNeeded} onChange={(e) => setWhatIsNeeded(e.target.value)} />
        </label>

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

        <p className="s1-muted s1-modal__note">Goes to Evidence requests as not yet sent; nothing is sent from here.</p>

        <div className="s1-modal__actions">
          <button
            className="s1-button"
            type="button"
            onClick={() => {
              const chosen = (team.length ? team : [signed]).find((m) => m.login === raisedBy) ?? signed;
              onAdd({
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
              });
            }}
          >
            Add
          </button>
          <button className="s1-button" type="button" onClick={onCancel}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
