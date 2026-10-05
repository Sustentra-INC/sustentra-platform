"use client";

import { useState } from "react";

import styles from "./admin.module.css";

/** A confirmation dialog that only enables the action once the user types an
 *  exact phrase (e.g. the org name). Used for destructive actions. */
export function ConfirmByTyping({
  title,
  message,
  confirmPhrase,
  confirmLabel = "Confirm",
  danger = false,
  onConfirm,
  onCancel,
}: {
  title: string;
  message: string;
  confirmPhrase: string;
  confirmLabel?: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState("");
  const matches = value.trim() === confirmPhrase;

  return (
    <div className={styles.scrim} role="presentation" onClick={onCancel}>
      <div
        className={styles.dialog}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className={styles.dialogTitle}>{title}</h2>
        <p className={styles.muted}>{message}</p>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="confirm-phrase">
            Type “{confirmPhrase}” to confirm
          </label>
          <input
            id="confirm-phrase"
            className={styles.input}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            autoFocus
            autoComplete="off"
          />
        </div>
        <div className={styles.actions}>
          <button
            type="button"
            className={`${styles.button} ${danger ? styles.danger : ""}`}
            disabled={!matches}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
          <button type="button" className={`${styles.button} ${styles.ghost}`} onClick={onCancel}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
