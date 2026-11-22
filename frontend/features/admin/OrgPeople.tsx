"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";

import { ApiError } from "../../lib/api";
import {
  deleteUser,
  inviteUser,
  listOrgUsers,
  resendInvite,
  type OrgUser,
  type UserRole,
} from "./orgApi";
import { StatusBadge } from "./StatusBadge";
import styles from "./admin.module.css";

/** "12 Nov 2026", the same on every machine. */
function day(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}

/** Admins first, then by name (email when there is no name). */
function sortPeople(items: OrgUser[]): OrgUser[] {
  const label = (p: OrgUser) => `${p.first_name} ${p.last_name}`.trim() || p.email;
  return [...items].sort((a, b) => {
    if (a.role !== b.role) return a.role === "org_admin" ? -1 : 1;
    return label(a).localeCompare(label(b));
  });
}

/** Provider admin › Organization › People: who is in this org, and invite someone. The same org-user
 *  and invite routes an org admin uses (a provider admin may act on any org). */
export function OrgPeople({ orgId, onChanged }: { orgId: string; onChanged?: () => void }) {
  const [people, setPeople] = useState<OrgUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const res = await listOrgUsers(orgId);
      setPeople(sortPeople(res.items));
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
      onChanged?.();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Something went wrong. Please try again.");
    }
  }

  return (
    <>
      <section className={styles.card} aria-labelledby="org-people-title">
        <h2 id="org-people-title" className={styles.label}>
          People
        </h2>
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
        {loading ? (
          <p className={styles.muted}>Loading…</p>
        ) : people.length === 0 ? (
          !error ? <p className={styles.muted}>No one has been added to this organization yet.</p> : null
        ) : (
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
                {people.map((p) => {
                  const name = `${p.first_name} ${p.last_name}`.trim() || p.email;
                  const sent = day(p.created_at);
                  return (
                    <tr key={p.id}>
                      <td>{name}</td>
                      <td className={styles.muted}>{p.email}</td>
                      <td>{p.role === "org_admin" ? "Org admin" : "Member"}</td>
                      <td>
                        <StatusBadge status={p.status} />
                        {p.status === "invited" && sent ? <span className={styles.muted}> · invited {sent}</span> : null}
                      </td>
                      <td>
                        {p.status === "invited" ? (
                          <div className={styles.actions}>
                            <button
                              type="button"
                              className={`${styles.button} ${styles.ghost}`}
                              aria-label={`Resend invite to ${p.email}`}
                              onClick={() => void act(() => resendInvite(orgId, p.id), `Invite sent again to ${p.email}.`)}
                            >
                              Resend invite
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
                          </div>
                        ) : null}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <InviteSomeone
        orgId={orgId}
        onInvited={() => {
          void reload();
          onChanged?.();
        }}
      />
    </>
  );
}

function InviteSomeone({ orgId, onInvited }: { orgId: string; onInvited: () => void }) {
  const [email, setEmail] = useState("");
  const [first, setFirst] = useState("");
  const [last, setLast] = useState("");
  const [role, setRole] = useState<UserRole>("org_member");
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSent(null);
    if (!email.trim()) {
      setError("Enter an email address.");
      return;
    }
    setSubmitting(true);
    try {
      const to = email.trim();
      await inviteUser(orgId, { email: to, role, first_name: first.trim(), last_name: last.trim() });
      setSent(to);
      setEmail("");
      setFirst("");
      setLast("");
      onInvited();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not send the invite. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className={styles.card} onSubmit={onSubmit} noValidate aria-labelledby="invite-someone-title">
      <h2 id="invite-someone-title" className={styles.label}>
        Invite someone
      </h2>
      {error ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}
      {sent ? (
        <p className={styles.success} role="status">
          Invite sent to {sent}
        </p>
      ) : null}
      <div className={styles.field}>
        <label className={styles.label} htmlFor="invite-email">
          Email
        </label>
        <input
          id="invite-email"
          className={styles.input}
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
      </div>
      <div className={styles.actions}>
        <div className={styles.field} style={{ flex: 1 }}>
          <label className={styles.label} htmlFor="invite-first">
            First name
          </label>
          <input id="invite-first" className={styles.input} value={first} onChange={(e) => setFirst(e.target.value)} />
        </div>
        <div className={styles.field} style={{ flex: 1 }}>
          <label className={styles.label} htmlFor="invite-last">
            Last name
          </label>
          <input id="invite-last" className={styles.input} value={last} onChange={(e) => setLast(e.target.value)} />
        </div>
      </div>
      <div className={styles.field}>
        <label className={styles.label} htmlFor="invite-role">
          Role
        </label>
        <select
          id="invite-role"
          className={styles.select}
          value={role}
          onChange={(e) => setRole(e.target.value as UserRole)}
        >
          <option value="org_member">Member</option>
          <option value="org_admin">Org admin</option>
        </select>
      </div>
      <div className={styles.actions}>
        <button type="submit" className={styles.button} disabled={submitting}>
          {submitting ? "Sending…" : "Send invite"}
        </button>
      </div>
    </form>
  );
}
