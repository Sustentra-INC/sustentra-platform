"use client";

import { useEffect, useState } from "react";

import { listAuditLog, type AuditEvent } from "./orgApi";
import styles from "./admin.module.css";

const EVENT_TYPES = [
  { value: "", label: "All events" },
  { value: "user.invited", label: "User invited" },
  { value: "user.role_changed", label: "Role changed" },
  { value: "user.suspended", label: "User suspended" },
  { value: "user.reactivated", label: "User reactivated" },
  { value: "user.deleted", label: "User deleted" },
];

/** Org audit log (FE-005 / COMP-002): paginated event table with a type filter. */
export function AuditLog({ orgId }: { orgId: string }) {
  const [events, setEvents] = useState<AuditEvent[]>([]);
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
                  <td className={styles.muted}>{event.created_at}</td>
                  <td>{event.event_type}</td>
                  <td>{event.actor}</td>
                  <td className={styles.muted}>{event.summary ?? event.target ?? "—"}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
