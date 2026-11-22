"use client";

import { useEffect, useState, type FormEvent } from "react";
import Link from "next/link";

import { ApiError } from "../../lib/api";
import { logout } from "../auth/api";
import { resendInvite } from "./orgApi";
import {
  activateOrg,
  getOrg,
  suspendOrg,
  updateOrg,
  type InitialAdminStatus,
  type OrgDetail as OrgDetailData,
} from "./providerApi";
import { ConfirmByTyping } from "./ConfirmByTyping";
import { OrgPeople } from "./OrgPeople";
import { StatusBadge } from "./StatusBadge";
import styles from "./admin.module.css";

/** Org detail (FE-004): edit name + seat limit, suspend / activate. Suspend
 *  requires typing the org name to confirm. */
export function OrgDetail({ orgId }: { orgId: string }) {
  const [org, setOrg] = useState<OrgDetailData | null>(null);
  const [name, setName] = useState("");
  const [maxUsers, setMaxUsers] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
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
    setSaved(false);
    const max = Number(maxUsers);
    if (!Number.isInteger(max) || max < 1) {
      setError("Seat limit must be a whole number of at least 1.");
      return;
    }
    setSaving(true);
    try {
      const updated = await updateOrg(orgId, { name: name.trim(), max_users: max });
      // The update answers with the org only; keep the first admin and the counts already loaded.
      setOrg((current) => ({ ...current, ...updated }));
      setSaved(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not save changes.");
    } finally {
      setSaving(false);
    }
  }

  /** Re-read the org (counts, first admin) without blanking the page; the form fields are left as typed. */
  async function refreshOrg() {
    try {
      const fetched = await getOrg(orgId);
      setOrg((current) => ({ ...current, ...fetched }));
    } catch {
      // The counts stay as they were; the people list has its own error line.
    }
  }

  async function doResend(admin: InitialAdminStatus) {
    setError(null);
    setNotice(null);
    try {
      await resendInvite(orgId, admin.user_id);
      setNotice("Invite sent again.");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not send the invite again.");
    }
  }

  async function onSignOut() {
    try {
      await logout();
    } catch {
      // Clear client state regardless.
    }
    window.location.assign("/provider-admin/login");
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
      <div className={styles.topBar}>
        <nav aria-label="Breadcrumb" className={styles.breadcrumb}>
          <Link className={styles.crumbLink} href="/provider-admin/orgs">
            Organizations
          </Link>
          <span aria-hidden="true">/</span>
          <span aria-current="page">{org.name}</span>
        </nav>
        <button type="button" className={`${styles.button} ${styles.ghost}`} onClick={() => void onSignOut()}>
          Sign out
        </button>
      </div>

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
      {notice ? (
        <p className={styles.success} role="status">
          {notice}
        </p>
      ) : null}

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
          {saved ? (
            <span className={styles.savedNote} role="status">
              Saved. <Link href="/provider-admin/orgs">Back to Organizations</Link>
            </span>
          ) : null}
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

      <FirstAdmin admin={org.initial_admin ?? null} counts={org.user_counts} onResend={(a) => void doResend(a)} />

      <OrgPeople orgId={orgId} onChanged={() => void refreshOrg()} />

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

/** "12 Nov 2026", the same on every machine. */
function day(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}

/** Whether the org's first admin has accepted their invite, and the seats by status. The provider
 *  can send the invite again while it is waiting (the same call an org admin uses). */
function FirstAdmin({
  admin,
  counts,
  onResend,
}: {
  admin: InitialAdminStatus | null;
  counts: OrgDetailData["user_counts"];
  onResend: (admin: InitialAdminStatus) => void;
}) {
  const invited = day(admin?.invited_at);
  const sent = day(admin?.last_invite_sent_at);
  const state =
    admin === null
      ? null
      : admin.status === "invited"
        ? admin.invite_expired
          ? "Invited · link expired"
          : "Invited · waiting"
        : admin.status === "active"
          ? "Active"
          : "Suspended";
  return (
    <section className={styles.card} aria-labelledby="first-admin-title">
      <h2 id="first-admin-title" className={styles.label}>
        First admin
      </h2>
      {admin ? (
        <>
          <p>
            <span>{[admin.first_name, admin.last_name].filter(Boolean).join(" ") || admin.email}</span>
            <span className={styles.muted}> · {admin.email}</span>
          </p>
          <p>
            <span
              className={`${styles.badge} ${
                admin.status === "active" ? styles.badgeActive : admin.status === "suspended" ? styles.badgeSuspended : styles.badgeInvited
              }`}
              data-testid="first-admin-state"
            >
              {state}
            </span>
            {invited ? <span className={styles.muted}> · invited {invited}</span> : null}
            {admin.status === "invited" && sent && sent !== invited ? (
              <span className={styles.muted}> · last sent {sent}</span>
            ) : null}
          </p>
          {admin.status === "invited" ? (
            <div className={styles.actions}>
              <button type="button" className={`${styles.button} ${styles.ghost}`} onClick={() => onResend(admin)}>
                Resend invite
              </button>
            </div>
          ) : null}
        </>
      ) : (
        <p className={styles.muted}>No admin has been invited yet.</p>
      )}
      {counts ? (
        <p className={styles.muted}>
          {counts.active} active · {counts.invited} invited · {counts.suspended} suspended
        </p>
      ) : null}
    </section>
  );
}
