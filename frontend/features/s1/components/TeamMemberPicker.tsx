"use client";

import { useState } from "react";

import { isEmail } from "../../admin/emails";
import type { OrgMember } from "../../admin/orgApi";

/** The company's people, for picking the engagement team (backend mode). */
export interface TeamDirectory {
  orgName: string;
  members: OrgMember[];
  /** Only org admins can invite. Others are told to ask one. */
  canInvite: boolean;
  /** Sends the invitation email (the same one as Org admin › People). Rejects with a readable message. */
  invite: (email: string) => Promise<void>;
}

export interface PickedMember {
  name: string;
  login: string;
}

/** Search the org's members; pick one to add to the team. An address that is not a member yet offers
 *  "Invite <email> to <Company>": it sends the invitation and adds them to the team, marked Invited until they accept.
 *  Nobody is created silently. */
export function TeamMemberPicker({
  directory,
  taken,
  onPick,
}: {
  directory: TeamDirectory;
  /** Logins already on the team. */
  taken: string[];
  onPick: (member: PickedMember) => void;
}) {
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const q = query.trim().toLowerCase();
  const onTeam = new Set(taken.map((t) => t.toLowerCase()));
  const matches = q
    ? directory.members
        .filter((m) => !onTeam.has(m.email.toLowerCase()) && (m.email.toLowerCase().includes(q) || m.name.toLowerCase().includes(q)))
        .slice(0, 8)
    : [];
  const looksLikeEmail = isEmail(q);
  const isMember = directory.members.some((m) => m.email.toLowerCase() === q);
  const offerInvite = looksLikeEmail && !isMember && !onTeam.has(q);

  function pick(member: OrgMember) {
    onPick({ name: member.name || member.email, login: member.email });
    setQuery("");
    setError(null);
  }

  async function invite() {
    setBusy(true);
    setError(null);
    try {
      await directory.invite(q);
      onPick({ name: q, login: q });
      setQuery("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send the invitation.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="s1-team-picker">
      <input
        aria-label="Add a team member"
        placeholder={`Search ${directory.orgName || "your company"}'s people or type an email`}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      {matches.length > 0 ? (
        <ul className="s1-team-picker__list" aria-label="Matching people">
          {matches.map((m) => (
            <li key={m.id}>
              <button type="button" className="s1-linklike" onClick={() => pick(m)}>
                {m.name || m.email}
                <span className="s1-muted">
                  {" "}
                  · {m.email}
                  {m.status === "invited" ? " · invited" : ""}
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {offerInvite && directory.canInvite ? (
        <button type="button" className="s1-setup-add" disabled={busy} onClick={invite}>
          Invite {q} to {directory.orgName || "your company"}
        </button>
      ) : null}
      {offerInvite && !directory.canInvite ? (
        <p className="s1-muted">{q} is not in {directory.orgName || "your company"} yet. Ask an org admin to add them.</p>
      ) : null}
      {q && matches.length === 0 && !offerInvite ? <p className="s1-muted">No one matches. Type a full email to invite.</p> : null}
      {error ? <p role="alert" className="s1-muted">{error}</p> : null}
    </div>
  );
}
