"use client";

import { useEffect, useState, type FormEvent } from "react";

import { ApiError } from "../../lib/api";
import { activateOrg, getOrg, suspendOrg, updateOrg, type Org } from "./providerApi";
import { ConfirmByTyping } from "./ConfirmByTyping";
import { StatusBadge } from "./StatusBadge";
import styles from "./admin.module.css";

/** Org detail (FE-004): edit name + seat limit, suspend / activate. Suspend
 *  requires typing the org name to confirm. */
export function OrgDetail({ orgId }: { orgId: string }) {
  const [org, setOrg] = useState<Org | null>(null);
  const [name, setName] = useState("");
  const [maxUsers, setMaxUsers] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirming, setConfirming] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const fetched = await getOrg(orgId);
      setOrg(fetched);
      setName(fetched.name);
      setMaxUsers(String(fetched.max_users));
    } catch {
      setError("Could not load this organization.");
    } finally {
      setLoading(false);
    }
  }

  // Initial fetch: state is only set once the request settles (no synchronous
  // setState in the effect). `load()` above is still used to refresh after actions.
  useEffect(() => {
    let active = true;
    getOrg(orgId)
      .then((fetched) => {
        if (!active) return;
        setOrg(fetched);
        setName(fetched.name);
        setMaxUsers(String(fetched.max_users));
      })
      .catch(() => {
        if (active) setError("Could not load this organization.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [orgId]);

  async function onSave(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setNotice(null);
    const max = Number(maxUsers);
    if (!Number.isInteger(max) || max < 1) {
      setError("Seat limit must be a whole number of at least 1.");
      return;
    }
    setSaving(true);
    try {
      const updated = await updateOrg(orgId, { name: name.trim(), max_users: max });
      setOrg(updated);
      setNotice("Saved.");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not save changes.");
    } finally {
      setSaving(false);
    }
  }

  async function doSuspend() {
    setConfirming(false);
    setError(null);
    setNotice(null);
    try {
      await suspendOrg(orgId);
      setNotice("Organization suspended.");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not suspend the organization.");
    }
  }

  async function doActivate() {
    setError(null);
    setNotice(null);
    try {
      await activateOrg(orgId);
      setNotice("Organization activated.");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not activate the organization.");
    }
  }

  if (loading) {
    return (
      <div className={styles.page}>
        <p className={styles.muted}>Loading…</p>
      </div>
    );
  }

  if (!org) {
    return (
      <div className={styles.page}>
        <p className={styles.error} role="alert">
          {error ?? "Organization not found."}
        </p>
      </div>
    );
  }

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>{org.name}</h1>
          <p className={styles.subtitle}>
            {org.slug} · <StatusBadge status={org.status} />
          </p>
        </div>
      </div>

      {error ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}
      {notice ? <p className={styles.muted}>{notice}</p> : null}

      <form className={styles.card} onSubmit={onSave} noValidate>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="name">
            Name
          </label>
          <input id="name" className={styles.input} value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="max-users">
            Seat limit
          </label>
          <input
            id="max-users"
            className={styles.input}
            type="number"
            min={1}
            value={maxUsers}
            onChange={(e) => setMaxUsers(e.target.value)}
          />
        </div>
        <div className={styles.actions}>
          <button type="submit" className={styles.button} disabled={saving}>
            {saving ? "Saving…" : "Save changes"}
          </button>
          {org.status === "active" ? (
            <button
              type="button"
              className={`${styles.button} ${styles.danger}`}
              onClick={() => setConfirming(true)}
            >
              Suspend
            </button>
          ) : (
            <button
              type="button"
              className={`${styles.button} ${styles.ghost}`}
              onClick={() => void doActivate()}
            >
              Activate
            </button>
          )}
        </div>
      </form>

      {confirming ? (
        <ConfirmByTyping
          title="Suspend organization"
          message={`This signs out all of ${org.name}'s users immediately. They can't sign in until it's reactivated.`}
          confirmPhrase={org.name}
          confirmLabel="Suspend"
          danger
          onConfirm={() => void doSuspend()}
          onCancel={() => setConfirming(false)}
        />
      ) : null}
    </div>
  );
}
