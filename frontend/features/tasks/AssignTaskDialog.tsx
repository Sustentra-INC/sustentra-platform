"use client";

import { useEffect, useState } from "react";

import { ApiError } from "../../lib/api";
import type { AssignTarget } from "./AssignTaskContext";
import { createTask, listAssignees, todayIso, type Assignee } from "./tasksApi";

/**
 * "Assign to…": pick a teammate, add a note and an optional due date. The person is told in Sustentra
 * and by email (the email says only who assigned a task, with a link to the app; nothing about the work). Uses the same window as Add to requests.
 */
export function AssignTaskDialog({
  orgId,
  engagementId,
  target,
  onClose,
}: {
  orgId: string;
  engagementId: string | null;
  target: AssignTarget;
  onClose: () => void;
}) {
  const [people, setPeople] = useState<Assignee[] | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [assigneeId, setAssigneeId] = useState("");
  const [title, setTitle] = useState(target.title);
  const [note, setNote] = useState("");
  const [due, setDue] = useState("");
  const [pending, setPending] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [assignedTo, setAssignedTo] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    listAssignees(orgId)
      .then((result) => active && setPeople(result.items))
      .catch(() => active && setLoadFailed(true));
    return () => {
      active = false;
    };
  }, [orgId]);

  const close = () => {
    if (!pending) onClose();
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !pending) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, pending]);

  const submit = async () => {
    if (pending || !assigneeId || !title.trim()) return;
    setPending(true);
    setProblem(null);
    try {
      const task = await createTask(orgId, {
        title: title.trim(),
        assignee_user_id: assigneeId,
        note: note.trim() || null,
        engagement_id: engagementId,
        target: engagementId ? target.target : null,
        due_date: due || null,
      });
      setAssignedTo(task.assignee_name);
    } catch (error) {
      setProblem(
        error instanceof ApiError && error.status === 429
          ? "You have assigned a lot of tasks in the last hour. Try again a little later."
          : error instanceof ApiError && error.status === 422
            ? "That person cannot be assigned this task. Choose another teammate."
            : "Could not assign the task. Nothing was sent. Try again.",
      );
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="s1-modal-scrim" role="presentation" onClick={close}>
      <div
        className="s1-modal s1-atr"
        role="dialog"
        aria-modal="true"
        aria-labelledby="s1-assign-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="s1-atr__head">
          <h2 id="s1-assign-title" className="s1-atr__title">
            Assign to…
          </h2>
          <button className="s1-atr__close" type="button" aria-label="Close" disabled={pending} onClick={close}>
            ×
          </button>
        </div>

        <dl className="s1-atr__about">
          <div className="s1-atr__fact">
            <dt>{target.kind}</dt>
            <dd>{target.label}</dd>
          </div>
        </dl>

        {assignedTo ? (
          <div className="s1-atr__form">
            <p role="status">
              Assigned to {assignedTo}. They have a notification in Sustentra and an email with a link.
            </p>
            <div className="s1-atr__foot">
              <span />
              <div className="s1-modal__actions">
                <button className="s1-button s1-button--pri" type="button" onClick={onClose}>
                  Done
                </button>
              </div>
            </div>
          </div>
        ) : (
          <form
            className="s1-atr__form"
            onSubmit={(e) => {
              e.preventDefault();
              void submit();
            }}
          >
            <label className="s1-modal__field">
              <span>Assign to</span>
              <select value={assigneeId} onChange={(e) => setAssigneeId(e.target.value)} disabled={!people}>
                <option value="">{people ? "Choose a person" : loadFailed ? "Could not load people" : "Loading people…"}</option>
                {(people ?? []).map((person) => (
                  <option key={person.id} value={person.id}>
                    {person.name}
                    {person.name !== person.email ? ` (${person.email})` : ""}
                  </option>
                ))}
              </select>
            </label>

            <label className="s1-modal__field">
              <span>Task</span>
              <input type="text" maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} />
            </label>

            <label className="s1-modal__field">
              <span>Note (optional)</span>
              <textarea rows={3} maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} />
            </label>

            <label className="s1-modal__field">
              <span>Due date (optional)</span>
              <input type="date" min={todayIso()} value={due} onChange={(e) => setDue(e.target.value)} />
            </label>

            {problem ? (
              <p className="s1-system-banner" role="alert">
                {problem}
              </p>
            ) : null}

            <div className="s1-atr__foot">
              <p className="s1-muted s1-modal__note">
                They are told in Sustentra and by email. The email says only that you assigned them a task and links to Sustentra; the details show after they sign in.
              </p>
              <div className="s1-modal__actions">
                <button className="s1-button" type="button" disabled={pending} onClick={close}>
                  Cancel
                </button>
                <button className="s1-button s1-button--pri" type="submit" disabled={!assigneeId || !title.trim() || pending}>
                  Assign
                </button>
              </div>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
