"use client";

import { useState, type FormEvent } from "react";

/**
 * Setup's engagement chooser (S1-BE-002): pick one of the org's engagements or
 * create a new one. Shown in backend mode only; the fixture demo has one engagement.
 */

export interface EngagementOption {
  id: string;
  name: string;
  clientName?: string | null;
}

export type SaveState = "idle" | "saving" | "saved" | "error";

export function EngagementPicker({
  engagements,
  selectedId,
  onSelect,
  onCreate,
  saveState = "idle",
  message,
}: {
  engagements: EngagementOption[];
  selectedId: string;
  onSelect: (id: string) => void;
  /** Resolves when the engagement exists; rejects with a user-facing message. */
  onCreate: (name: string) => Promise<void>;
  saveState?: SaveState;
  message?: string | null;
}) {
  const [creating, setCreating] = useState(engagements.length === 0);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!name.trim()) {
      setError("Give the engagement a name.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onCreate(name);
      setName("");
      setCreating(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the engagement.");
    } finally {
      setBusy(false);
    }
  }

  const status =
    saveState === "saving" ? "Saving…" : saveState === "saved" ? "Saved" : saveState === "error" ? message : null;

  return (
    <div className="s1-setup-card" aria-label="Engagement">
      <h2>Engagement</h2>
      {engagements.length === 0 && !creating ? null : engagements.length > 0 ? (
        <div className="s1-setup-inline">
          <label className="s1-setup-field">
            <span>Working on</span>
            <select value={selectedId} onChange={(e) => onSelect(e.target.value)} aria-label="Working on">
              {engagements.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.clientName ? `${e.name} — ${e.clientName}` : e.name}
                </option>
              ))}
            </select>
          </label>
          {!creating ? (
            <button className="s1-button" type="button" onClick={() => setCreating(true)}>
              New engagement
            </button>
          ) : null}
          {status ? (
            <span className="s1-muted" role={saveState === "error" ? "alert" : "status"}>
              {status}
            </span>
          ) : null}
        </div>
      ) : (
        <p className="s1-muted">Create your first engagement to start uploading evidence.</p>
      )}

      {creating ? (
        <form className="s1-setup-inline" onSubmit={submit}>
          <label className="s1-setup-field">
            <span>New engagement name</span>
            <input
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                setError(null);
              }}
              placeholder="e.g. FY2024 GHG verification"
              maxLength={200}
              autoFocus
            />
          </label>
          <button className="s1-button s1-button--pri" type="submit" disabled={busy}>
            {busy ? "Creating…" : "Create"}
          </button>
          {engagements.length > 0 ? (
            <button className="s1-linklike" type="button" onClick={() => setCreating(false)}>
              Cancel
            </button>
          ) : null}
          {error ? (
            <span className="s1-muted" role="alert">
              {error}
            </span>
          ) : null}
        </form>
      ) : null}
    </div>
  );
}
