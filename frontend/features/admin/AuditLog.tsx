"use client";

import { useEffect, useState } from "react";

import { listAuditLog, type AuditEvent } from "./orgApi";
import styles from "./admin.module.css";

/** Event names as the backend writes them (audit_logs.event_type). */
const EVENT_LABELS: Record<string, string> = {
  user_invited: "User invited",
  user_invite_resent: "Invite resent",
  invite_accepted: "Invite accepted",
  user_role_changed: "Role changed",
  user_suspended: "User suspended",
  user_reactivated: "User reactivated",
  user_deleted: "User deleted",
  login_success: "Signed in",
  login_fail: "Sign-in failed",
  account_locked: "Account locked",
  logout: "Signed out",
  password_reset: "Password reset",
  engagement_created: "Engagement created",
  org_created: "Organization created",
  org_updated: "Organization updated",
  org_suspended: "Organization suspended",
  org_activated: "Organization reactivated",
};

const EVENT_TYPES = [
  { value: "", label: "All events" },
  ...Object.entries(EVENT_LABELS).map(([value, label]) => ({ value, label })),
];

function label(eventType: string): string {
  return EVENT_LABELS[eventType] ?? eventType;
}

function when(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}

/** Org audit log (FE-005 / COMP-002): paginated event table with a type filter. */
export function AuditLog({ orgId }: { orgId: string }) {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [type, setType] = useState("");
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Refetch whenever the filters change. State is only set once
  // the request settles, so the effect never calls setState synchronously
  // (react-hooks/set-state-in-effect); `loading` is derived from whether the
  // latest request has finished.
  const requestKey = JSON.stringify([orgId, type]);
  const loading = loadedKey !== requestKey;

  useEffect(() => {
    let active = true;
    listAuditLog(orgId, { type })
      .then((res) => {
        if (!active) return;
        setEvents(res.items);
        setNextCursor(res.next_cursor);
        setError(null);
      })
      .catch(() => {
        if (active) setError("Could not load the audit log.");
      })
      .finally(() => {
        if (active) setLoadedKey(requestKey);
      });
    return () => {
      active = false;
    };
    // requestKey captures every input of the request.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestKey]);

  async function loadMore() {
    if (!nextCursor) return;
    setLoadingMore(true);
    try {
      const res = await listAuditLog(orgId, { type, cursor: nextCursor });
      setEvents((prev) => [...prev, ...res.items]);
      setNextCursor(res.next_cursor);
    } catch {
      setError("Could not load more events.");
    } finally {
      setLoadingMore(false);
    }
  }

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>Audit log</h1>
          <p className={styles.subtitle}>Every action taken in this organization.</p>
        </div>
      </div>

      <div className={styles.toolbar}>
        <select
          className={styles.select}
          value={type}
          onChange={(e) => setType(e.target.value)}
          aria-label="Filter by event type"
        >
          {EVENT_TYPES.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>

      {error ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}

      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>When</th>
              <th>Event</th>
              <th>Actor</th>
              <th>Detail</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={4} className={styles.muted}>
                  Loading…
                </td>
              </tr>
            ) : events.length === 0 ? (
              <tr>
                <td colSpan={4} className={styles.muted}>
                  No events yet.
                </td>
              </tr>
            ) : (
              events.map((event) => (
                <tr key={event.id}>
                  <td className={styles.muted}>{when(event.created_at)}</td>
                  <td>{label(event.event_type)}</td>
                  <td>{event.actor ?? "—"}</td>
                  <td className={styles.muted}>{event.target ?? "—"}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {!loading && nextCursor ? (
        <div className={styles.toolbar}>
          <button
            type="button"
            className={styles.button}
            onClick={() => void loadMore()}
            disabled={loadingMore}
          >
            {loadingMore ? "Loading…" : "Load more"}
          </button>
        </div>
      ) : null}
    </div>
  );
}
