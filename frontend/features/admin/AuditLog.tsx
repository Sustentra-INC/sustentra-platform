"use client";

import { useCallback, useEffect, useState } from "react";

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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listAuditLog(orgId, { type });
      setEvents(res.items);
    } catch {
      setError("Could not load the audit log.");
    } finally {
      setLoading(false);
    }
  }, [orgId, type]);

  useEffect(() => {
    void load();
  }, [load]);

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
