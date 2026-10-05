"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";

import { ApiError } from "../../lib/api";
import { createOrg, slugIssue } from "./providerApi";
import styles from "./admin.module.css";

/** Create organization + optional initial admin (FE-004). Surfaces API validation
 *  errors (e.g. duplicate slug → 409). */
export function CreateOrgForm({ onCreated }: { onCreated?: (orgId: string) => void }) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [maxUsers, setMaxUsers] = useState("10");
  const [adminEmail, setAdminEmail] = useState("");
  const [adminFirst, setAdminFirst] = useState("");
  const [adminLast, setAdminLast] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (!name.trim()) {
      setError("Enter an organization name.");
      return;
    }
    const slugProblem = slugIssue(slug);
    if (slugProblem) {
      setError(slugProblem);
      return;
    }
    const max = Number(maxUsers);
    if (!Number.isInteger(max) || max < 1) {
      setError("Seat limit must be a whole number of at least 1.");
      return;
    }
    const initialAdmin = adminEmail.trim()
      ? { email: adminEmail.trim(), first_name: adminFirst.trim(), last_name: adminLast.trim() }
      : undefined;

    setSubmitting(true);
    try {
      const org = await createOrg({ name: name.trim(), slug, max_users: max, initial_admin: initialAdmin });
      if (onCreated) onCreated(org.id);
      else router.push(`/provider-admin/orgs/${org.id}`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError("That slug is already taken. Choose another.");
      } else if (err instanceof ApiError) {
        setError(err.detail);
      } else {
        setError("Could not create the organization. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>New organization</h1>
          <p className={styles.subtitle}>Create a client org and, optionally, its first admin.</p>
        </div>
      </div>

      <form className={styles.card} onSubmit={onSubmit} noValidate>
        {error ? (
          <p className={styles.error} role="alert">
            {error}
          </p>
        ) : null}

        <div className={styles.field}>
          <label className={styles.label} htmlFor="name">
            Organization name
          </label>
          <input
            id="name"
            className={styles.input}
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoFocus
          />
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="slug">
            Slug
          </label>
          <input
            id="slug"
            className={styles.input}
            value={slug}
            onChange={(e) => setSlug(e.target.value.toLowerCase())}
            placeholder="acme-foods"
          />
          <span className={styles.hint}>
            Used in the URL: /org/&lt;slug&gt;. Lowercase letters, numbers, hyphens.
          </span>
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

        <div className={styles.field}>
          <span className={styles.label}>Initial admin (optional)</span>
          <span className={styles.hint}>If set, we invite this person as the org’s first admin.</span>
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="admin-email">
            Admin email
          </label>
          <input
            id="admin-email"
            className={styles.input}
            type="email"
            value={adminEmail}
            onChange={(e) => setAdminEmail(e.target.value)}
          />
        </div>
        <div className={styles.actions}>
          <div className={styles.field} style={{ flex: 1 }}>
            <label className={styles.label} htmlFor="admin-first">
              First name
            </label>
            <input
              id="admin-first"
              className={styles.input}
              value={adminFirst}
              onChange={(e) => setAdminFirst(e.target.value)}
            />
          </div>
          <div className={styles.field} style={{ flex: 1 }}>
            <label className={styles.label} htmlFor="admin-last">
              Last name
            </label>
            <input
              id="admin-last"
              className={styles.input}
              value={adminLast}
              onChange={(e) => setAdminLast(e.target.value)}
            />
          </div>
        </div>

        <div className={styles.actions}>
          <button type="submit" className={styles.button} disabled={submitting}>
            {submitting ? "Creating…" : "Create organization"}
          </button>
        </div>
      </form>
    </div>
  );
}
