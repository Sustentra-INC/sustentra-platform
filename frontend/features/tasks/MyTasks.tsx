"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import styles from "../admin/admin.module.css";
import {
  cancelTask,
  completeTask,
  formatDueDate,
  isOverdue,
  listMyTasks,
  type Task,
  type TaskRelation,
  type TaskStatus,
} from "./tasksApi";

const STATUS_WORDS: Record<TaskStatus, string> = { open: "Open", done: "Done", cancelled: "Cancelled" };

/**
 * My tasks: what I was asked to do, and what I asked others to do. Open first; the assignee can mark a
 * task complete (the requester, and the org admins if the requester is not one, are told), the
 * requester can cancel it.
 */
export function MyTasks({ orgId, slug }: { orgId: string; slug: string }) {
  const [relation, setRelation] = useState<TaskRelation>("assigned");
  const [status, setStatus] = useState<TaskStatus | "">("open");
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const result = await listMyTasks(orgId, { relation, status });
      setTasks(result.items);
      setError(null);
    } catch {
      setError("Could not load your tasks. Try again in a moment.");
    }
  }, [orgId, relation, status]);

  useEffect(() => {
    let active = true;
    listMyTasks(orgId, { relation, status })
      .then((result) => {
        if (!active) return;
        setTasks(result.items);
        setError(null);
      })
      .catch(() => active && setError("Could not load your tasks. Try again in a moment."));
    return () => {
      active = false;
    };
  }, [orgId, relation, status]);

  async function act(task: Task, run: () => Promise<Task>, done: string) {
    setBusyId(task.id);
    setMessage(null);
    try {
      await run();
      setMessage(done);
      await load();
    } catch {
      setError("That did not go through. Refresh the list and try again.");
    } finally {
      setBusyId(null);
    }
  }

  const switchRelation = (next: TaskRelation) => {
    setTasks(null);
    setMessage(null);
    setRelation(next);
  };

  return (
    <div className={styles.page}>
      <div className={styles.topBar}>
        <Link className={styles.crumbLink} href={`/org/${slug}`}>
          ← Back
        </Link>
      </div>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>My tasks</h1>
          <p className={styles.subtitle}>Work you were asked to do, and work you asked others to do.</p>
        </div>
      </div>

      <div className={styles.toolbar}>
        <button
          type="button"
          className={`${styles.button} ${relation === "assigned" ? "" : styles.ghost}`}
          aria-pressed={relation === "assigned"}
          onClick={() => switchRelation("assigned")}
        >
          Assigned to me
        </button>
        <button
          type="button"
          className={`${styles.button} ${relation === "requested" ? "" : styles.ghost}`}
          aria-pressed={relation === "requested"}
          onClick={() => switchRelation("requested")}
        >
          Requested by me
        </button>
        <select
          className={styles.select}
          value={status}
          onChange={(e) => {
            setTasks(null);
            setStatus(e.target.value as TaskStatus | "");
          }}
          aria-label="Filter by status"
        >
          <option value="open">Open</option>
          <option value="done">Done</option>
          <option value="cancelled">Cancelled</option>
          <option value="">All</option>
        </select>
      </div>

      {error ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}
      {message ? (
        <p className={styles.savedNote} role="status">
          {message}
        </p>
      ) : null}

      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Task</th>
              <th>{relation === "assigned" ? "From" : "Assigned to"}</th>
              <th>Due</th>
              <th>Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {tasks === null ? (
              <tr>
                <td colSpan={5} className={styles.muted}>
                  Loading…
                </td>
              </tr>
            ) : tasks.length === 0 ? (
              <tr>
                <td colSpan={5} className={styles.muted}>
                  {relation === "assigned" ? "Nothing is assigned to you." : "You have not asked anyone to do anything."}
                </td>
              </tr>
            ) : (
              tasks.map((task) => {
                const overdue = isOverdue(task);
                return (
                  <tr key={task.id}>
                    <td>
                      {task.link ? <a href={task.link}>{task.title}</a> : task.title}
                      {task.engagement_name ? <div className={styles.muted}>{task.engagement_name}</div> : null}
                      {task.note ? <div className={styles.muted}>{task.note}</div> : null}
                    </td>
                    <td>{relation === "assigned" ? task.requested_by_name : task.assignee_name}</td>
                    <td className={styles.muted}>
                      {task.due_date ? formatDueDate(task.due_date) : "—"}
                      {overdue ? <span className={styles.overdue}> · Overdue</span> : null}
                    </td>
                    <td>{STATUS_WORDS[task.status]}</td>
                    <td>
                      {task.status === "open" && relation === "assigned" ? (
                        <button
                          type="button"
                          className={styles.button}
                          disabled={busyId === task.id}
                          onClick={() => void act(task, () => completeTask(orgId, task.id), `Marked complete: ${task.title}`)}
                        >
                          Mark complete
                        </button>
                      ) : null}
                      {task.status === "open" && relation === "requested" ? (
                        <button
                          type="button"
                          className={`${styles.button} ${styles.ghost}`}
                          disabled={busyId === task.id}
                          onClick={() => void act(task, () => cancelTask(orgId, task.id), `Cancelled: ${task.title}`)}
                        >
                          Cancel
                        </button>
                      ) : null}
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
