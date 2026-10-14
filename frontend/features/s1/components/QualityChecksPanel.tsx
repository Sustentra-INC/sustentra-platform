"use client";

import { useState } from "react";

import type { QualityCheck } from "../api/recalculation";

/**
 * Data quality checks on the evidence (missing months, duplicates, overlapping and
 * cross-year bills): what a reviewer should look at before relying on the numbers. Each is
 * a signal, never a conclusion, and none of them changes a number.
 */
const SEVERITY: Record<QualityCheck["severity"], { label: string; className: string }> = {
  warning: { label: "Look at", className: "s1-qc__sev--warning" },
  review: { label: "Confirm", className: "s1-qc__sev--review" },
  info: { label: "Note", className: "s1-qc__sev--info" },
};

const CHECK_NAME: Record<QualityCheck["check"], string> = {
  "Q-001": "Months covered",
  "Q-003": "Duplicate evidence",
  "Q-004": "Overlapping periods",
  "Q-005": "Across the reporting year",
  "N-003": "Service period",
};

export function QualityChecksPanel({ checks }: { checks: QualityCheck[] }) {
  const toLookAt = checks.filter((c) => c.severity !== "info").length;
  const [open, setOpen] = useState(toLookAt > 0);
  return (
    <section className="s1-rc s1-qc" aria-label="Data quality checks">
      <button className="s1-rc__head" type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <span className="s1-rc__title">Data quality checks</span>
        <span className="s1-muted">
          {checks.length === 0
            ? "Nothing found: no missing months, duplicates or overlapping bills."
            : `${toLookAt} to look at${checks.length > toLookAt ? `, ${checks.length - toLookAt} noted` : ""}`}
        </span>
        <span className="s1-rc__meta s1-muted">{open ? "Hide" : "Show"}</span>
      </button>
      {open && checks.length > 0 ? (
        <ul className="s1-qc__list">
          {checks.map((c, i) => (
            <li key={`${c.check}:${c.trigger}:${i}`} className="s1-qc__item">
              <span className={`s1-qc__sev ${SEVERITY[c.severity].className}`}>{SEVERITY[c.severity].label}</span>
              <div className="s1-qc__text">
                <div className="s1-qc__what">
                  {CHECK_NAME[c.check] ?? c.check} <span className="s1-mono s1-muted">{c.check}</span>
                </div>
                <p className="s1-qc__msg">{c.message}</p>
              </div>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

/** A short line per document for the Evidence screen's Issue column. */
export function qualityIssueLines(
  checks: QualityCheck[] | undefined,
  documentId: string,
  fileName: (id: string) => string
): string[] {
  const lines: string[] = [];
  for (const c of checks ?? []) {
    if (!c.documents.includes(documentId)) continue;
    const others = c.documents.filter((d) => d !== documentId).map(fileName);
    if (c.check === "Q-003") lines.push(others.length ? `Possible duplicate of ${others.join(", ")}` : "Possible duplicate");
    else if (c.check === "Q-004")
      lines.push(
        others.length
          ? `Overlaps ${others.join(", ")} (${String(c.detail.overlap_days)} days)`
          : `Records overlap (${String(c.detail.overlap_days)} days)`
      );
    else if (c.check === "Q-005") lines.push(`Crosses the reporting period (${String(c.detail.share_percent)}% counted)`);
    else if (c.check === "N-003") lines.push("No service period: counted in full");
  }
  return Array.from(new Set(lines));
}
