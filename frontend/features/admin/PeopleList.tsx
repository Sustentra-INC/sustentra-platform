"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";

import { ApiError } from "../../lib/api";
import { parseEmails } from "./emails";
import {
  BULK_INVITE_MAX,
  bulkInvite,
  deleteUser,
  listOrgUsers,
  reactivateUser,
  resendInvite,
  suspendUser,
  type BulkInviteResult,
  type BulkInviteStatus,
  type OrgUser,
  type UserRole,
} from "./orgApi";
import { StatusBadge } from "./StatusBadge";
import styles from "./admin.module.css";

const RESULT_TEXT: Record<BulkInviteStatus, string> = {
  invited: "Invitation sent",
  already_member: "Already in your organization",
  duplicate: "Listed twice",
  invalid: "Not a valid email address",
  seat_limit: "No seats left. Remove someone or ask your provider for more seats.",
};

/** Org admin › People: who is in the company, add people by email, re-send an invite, remove access.
 *  Invitations are the existing invite email (24 hours to accept); every action is audit-logged by the API. */
export function PeopleList({ orgId, startAdding = false }: { orgId: string; startAdding?: boolean }) {
  const [people, setPeople] = useState<OrgUser[]>([]);
  const [seats, setSeats] = useState<{ used: number; max: number } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [adding, setAdding] = useState(startAdding);

  const reload = useCallback(async () => {
    try {
      const res = await listOrgUsers(orgId);
      setPeople(res.items);
      setSeats({ used: res.seats_used, max: res.max_users });
      setError(null);
    } catch {
      setError("Could not load people.");
    } finally {
      setLoading(false);
    }
  }, [orgId]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial fetch; state is set once it settles
    void reload();
  }, [reload]);

  async function act(action: () => Promise<unknown>, done: string) {
    setError(null);
    setNotice(null);
    try {
      await action();
      setNotice(done);
      await reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Something went wrong. Please try again.");
    }
  }

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>People</h1>
          <p className={styles.subtitle}>
            {seats ? `${seats.used} / ${seats.max} seats used` : "Everyone in your company who can use the platform."}
          </p>
        </div>
        <button type="button" className={styles.button} onClick={() => setAdding(true)}>
          Add people
        </button>
      </div>

      {adding ? (
        <AddPeople
          orgId={orgId}
          onClose={() => setAdding(false)}
          onSent={(count) => {
            setNotice(`${count} invitation${count === 1 ? "" : "s"} sent.`);
            void reload();
          }}
        />
      ) : null}

      {notice ? (
        <p className={styles.success} role="status">
          {notice}
        </p>
      ) : null}
      {error ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}

      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Name</th>
              <th>Email</th>
              <th>Role</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={5} className={styles.muted}>
                  Loading…
                </td>
              </tr>
            ) : people.length === 0 ? (
              <tr>
                <td colSpan={5} className={styles.muted}>
                  No one yet. Use Add people to invite your team.
                </td>
              </tr>
            ) : (
              people.map((p) => {
                const name = `${p.first_name} ${p.last_name}`.trim() || p.email;
                return (
                  <tr key={p.id}>
                    <td>{name}</td>
                    <td className={styles.muted}>{p.email}</td>
                    <td>{p.role === "org_admin" ? "Admin" : "Member"}</td>
                    <td>
                      <StatusBadge status={p.status} />
                    </td>
                    <td>
                      <div className={styles.actions}>
                        {p.status === "invited" ? (
                          <>
                            <button
                              type="button"
                              className={`${styles.button} ${styles.ghost}`}
                              aria-label={`Re-send invite to ${p.email}`}
                              onClick={() => act(() => resendInvite(orgId, p.id), `Invitation re-sent to ${p.email}.`)}
                            >
                              Re-send invite
                            </button>
                            <button
                              type="button"
                              className={`${styles.button} ${styles.danger}`}
                              aria-label={`Cancel invite for ${p.email}`}
                              onClick={() => {
                                if (window.confirm(`Cancel the invitation for ${p.email}?`))
                                  void act(() => deleteUser(orgId, p.id), `Invitation for ${p.email} cancelled.`);
                              }}
                            >
                              Cancel invite
                            </button>
                          </>
                        ) : p.status === "suspended" ? (
                          <button
                            type="button"
                            className={`${styles.button} ${styles.ghost}`}
                            aria-label={`Restore access for ${p.email}`}
                            onClick={() => act(() => reactivateUser(orgId, p.id), `Access restored for ${p.email}.`)}
                          >
                            Restore access
                          </button>
                        ) : (
                          <button
                            type="button"
                            className={`${styles.button} ${styles.danger}`}
                            aria-label={`Remove access for ${p.email}`}
                            onClick={() => {
                              if (window.confirm(`Remove ${p.email}'s access? They are signed out at once. You can restore it later.`))
                                void act(() => suspendUser(orgId, p.id), `${p.email} no longer has access.`);
                            }}
                          >
                            Remove access
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function AddPeople({
  orgId,
  onClose,
  onSent,
}: {
  orgId: string;
  onClose: () => void;
  onSent: (count: number) => void;
}) {
  const [text, setText] = useState("");
  const [role, setRole] = useState<UserRole>("org_member");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<BulkInviteResult[] | null>(null);

  const { valid, invalid } = parseEmails(text);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (valid.length === 0) {
      setError("Enter at least one email address.");
      return;
    }
    if (valid.length > BULK_INVITE_MAX) {
      setError(`Invite at most ${BULK_INVITE_MAX} people at a time.`);
      return;
    }
    setBusy(true);
    try {
      // Only valid addresses go out; the ones that are not addresses are shown below as not sent.
      const res = await bulkInvite(orgId, valid, role);
      setResults([...res.results, ...invalid.map((email) => ({ email, status: "invalid" as const }))]);
      setText("");
      if (res.invited > 0) onSent(res.invited);
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 429
          ? "Too many requests. Wait a moment and try again."
          : err instanceof ApiError
            ? err.detail
            : "Could not send the invitations. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className={styles.card} onSubmit={onSubmit} noValidate aria-label="Add people">
      <div className={styles.field}>
        <label className={styles.label} htmlFor="people-emails">
          Email addresses
        </label>
        <textarea
          id="people-emails"
          className={styles.input}
          rows={4}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Paste or type one or more emails, separated by commas, spaces or new lines"
          autoFocus
        />
        <p className={styles.hint}>
          {valid.length} valid{invalid.length ? `, ${invalid.length} not an email address` : ""}. Up to {BULK_INVITE_MAX}{" "}
          at a time.
        </p>
      </div>
      <div className={styles.field}>
        <label className={styles.label} htmlFor="people-role">
          Role
        </label>
        <select id="people-role" className={styles.select} value={role} onChange={(e) => setRole(e.target.value as UserRole)}>
          <option value="org_member">Member</option>
          <option value="org_admin">Admin (can add and remove people)</option>
        </select>
      </div>
      {error ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}
      {results ? (
        <ul aria-label="Invitation results">
          {results.map((r) => (
            <li key={r.email}>
              {r.email}: {RESULT_TEXT[r.status]}
            </li>
          ))}
        </ul>
      ) : null}
      <div className={styles.actions}>
        <button type="submit" className={styles.button} disabled={busy}>
          {busy ? "Sending…" : `Send ${valid.length > 1 ? `${valid.length} invitations` : "invitation"}`}
        </button>
        <button type="button" className={`${styles.button} ${styles.ghost}`} onClick={onClose}>
          Close
        </button>
      </div>
    </form>
  );
}
