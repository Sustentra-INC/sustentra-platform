"use client";

import { useState } from "react";

import type { CatalogField, MethodologyRecord, MethodologyReviewData, MethodologyValue, PrefillResult } from "../api/methodologyReview";
import { dropReasonWords, itemLabel, valueText } from "../utils/methodologyText";

/**
 * The summary shown above the review once Sustentra's AI has read the reports. It is built from the
 * stored suggestions and decisions only: nothing is inferred and nothing is asked of the AI again.
 */

const isObject = (v: MethodologyValue | undefined): v is { [key: string]: MethodologyValue } => v !== null && typeof v === "object" && !Array.isArray(v);

/** What the row holds now: the reviewer's accepted or edited value, else the suggestion's. */
export function currentValue(record: MethodologyRecord | undefined): MethodologyValue | undefined {
  if (!record) return undefined;
  const d = record.decision;
  if (d && (d.status === "accepted" || d.status === "edited")) return d.value;
  return record.suggestion?.value;
}

const hasValue = (v: MethodologyValue | undefined) => v !== null && v !== undefined && v !== "" && !(Array.isArray(v) && v.length === 0);

/** Suggestions still waiting for a reviewer. The header count and the summary footer both use this one number. */
export function waitingForReview(data: MethodologyReviewData): number {
  return data.fields.filter((r) => r.suggestion && (!r.decision || r.decision.status === "pending")).length;
}

const list = (items: string[], and = "and") => (items.length < 2 ? items.join("") : `${items.slice(0, -1).join(", ")} ${and} ${items[items.length - 1]}`);

/** 2 to 4 short lines of what was found. */
export function summaryLines(data: MethodologyReviewData): string[] {
  const rec = new Map(data.fields.map((r) => [r.fieldId, r]));
  const shown = (id: string) => rec.get(id) && rec.get(id)!.shown !== false;
  const val = (id: string) => (shown(id) ? currentValue(rec.get(id)) : undefined);
  const lines: string[] = [];

  const boundary: string[] = [];
  const approach = val("consolidation_approach");
  if (shown("consolidation_approach")) boundary.push(`Boundary: ${hasValue(approach) ? valueText(approach) : "not found"}.`);
  const scopes = val("scopes:covered");
  if (hasValue(scopes)) boundary.push(`Scopes: ${Array.isArray(scopes) ? list(scopes.map((o) => (isObject(o) ? valueText(o.option) : valueText(o)))) : valueText(scopes)}.`);
  if (shown("reporting_period")) boundary.push(`Reporting period: ${hasValue(val("reporting_period")) ? valueText(val("reporting_period")) : "not found"}.`);
  if (boundary.length) lines.push(boundary.join(" "));

  const gases = data.catalog.filter((d) => d.group === "gases" && shown(d.fieldId));
  if (gases.length) {
    const status = (d: CatalogField) => String(val(d.fieldId) ?? "");
    const named = (want: string) => gases.filter((d) => status(d) === want).map((d) => itemLabel(d));
    const none = gases.filter((d) => !["Included", "Declared absent"].includes(status(d))).map((d) => itemLabel(d));
    const parts = [
      named("Included").length ? `${list(named("Included"), "and")} included` : "",
      named("Declared absent").length ? `${list(named("Declared absent"), "and")} declared absent` : "",
      none.length ? `${list(none, "and")} not found` : "",
    ].filter(Boolean);
    lines.push(`Gases: ${parts.join("; ")}.`);
  }

  const cats = (basis: string) =>
    ["electricity", "heating", "steam", "cooling"].filter((k) => shown(`category:${basis}:${k}`) && val(`category:${basis}:${k}`) === "Yes").map((k) => k);
  const s1 = data.catalog.filter((d) => d.group === "scope1" && shown(d.fieldId));
  const scopeParts: string[] = [];
  if (s1.length) {
    const yes = s1.filter((d) => val(d.fieldId) === "Yes").map((d) => d.label.replace(/^Scope 1\s+/i, "").toLowerCase());
    scopeParts.push(`Scope 1: ${yes.length ? list(yes) : "none found"}.`);
  }
  const anyS2 = data.catalog.some((d) => d.group === "scope2" && d.fieldId.startsWith("category:") && shown(d.fieldId));
  if (anyS2) {
    const loc = cats("location");
    const mkt = cats("market");
    const same = loc.length > 0 && loc.join() === mkt.join();
    scopeParts.push(
      same
        ? `Scope 2: ${list(loc)} (location- and market-based).`
        : !loc.length && !mkt.length
          ? "Scope 2: none found."
          : `Scope 2: ${[loc.length ? `${list(loc)} (location-based)` : "", mkt.length ? `${list(mkt)} (market-based)` : ""].filter(Boolean).join("; ")}.`
    );
  }
  if (scopeParts.length) lines.push(scopeParts.join(" "));

  const methods: string[] = [];
  const factors = data.catalog
    .filter((d) => d.kind === "factor" && shown(d.fieldId))
    .map((d) => currentValue(rec.get(d.fieldId)))
    .filter(hasValue)
    .map((v) => (isObject(v) && typeof v.database === "string" && v.database ? `${v.database}${typeof v.edition === "string" && v.edition ? ` (${v.edition})` : ""}` : valueText(v)));
  if (factors.length) methods.push(`Emission factors: ${factors.join(", ")}.`);
  const gwp = val("gwp");
  if (isObject(gwp) && typeof gwp.set === "string" && gwp.set) {
    const horizon = typeof gwp.horizon === "string" && gwp.horizon && gwp.horizon !== "Not stated" ? gwp.horizon : "";
    methods.push(`GWP: ${gwp.set} (${horizon || "horizon not stated"}).`);
  }
  if (methods.length) lines.push(methods.join(" "));
  return lines.slice(0, 4);
}

/** Rows the reader should look at: nothing found for them after a read, or rejected. */
export function attentionItems(data: MethodologyReviewData): { fieldId: string; label: string }[] {
  const rec = new Map(data.fields.map((r) => [r.fieldId, r]));
  return data.catalog
    .filter((d) => {
      const r = rec.get(d.fieldId);
      if (!r || r.shown === false) return false;
      if (r.decision?.status === "rejected") return true;
      return r.displayState === "not_detected" && !hasValue(currentValue(r));
    })
    .map((d) => ({ fieldId: d.fieldId, label: itemLabel(d) }));
}

function readOn(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

const storageKey = (engagementId: string) => `s1.methodologySummary.collapsed.${engagementId}`;

export function MethodologySummary({
  engagementId,
  data,
  result,
  onOpenDocument,
  onJump,
}: {
  engagementId: string;
  data: MethodologyReviewData;
  /** The last read in this session: only it knows what was set aside. */
  result: PrefillResult | null;
  onOpenDocument: (documentId: string) => void;
  onJump: (fieldId: string) => void;
}) {
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return window.localStorage.getItem(storageKey(engagementId)) === "1";
    } catch {
      return false; // storage can be blocked: the summary starts open
    }
  });
  const [details, setDetails] = useState(false);
  const toggle = () => {
    const next = !collapsed;
    setCollapsed(next);
    try {
      window.localStorage.setItem(storageKey(engagementId), next ? "1" : "0");
    } catch {
      /* not remembered */
    }
  };

  const suggestions = data.fields.flatMap((r) => (r.suggestion ? [r.suggestion] : []));
  if (suggestions.length === 0) return null;
  const docs = new Map(suggestions.map((s) => [s.document_id, s.file_name]));
  const latest = suggestions.map((s) => s.suggested_at).sort().at(-1) ?? "";
  const lines = summaryLines(data);
  const attention = attentionItems(data);
  const waiting = waitingForReview(data);
  const setAside = result ? Object.entries(result.dropped).filter(([, n]) => n > 0) : [];
  const setAsideTotal = setAside.reduce((sum, [, n]) => sum + n, 0);
  const [firstId, firstName] = [...docs][0];

  return (
    <section className="s1-mb-summary" aria-label="Summary of the read">
      <div className="s1-mb-summary__head">
        <p className="s1-mb-summary__title">
          Summary of{" "}
          {docs.size === 1 ? (
            <button type="button" className="s1-mr-link" onClick={() => onOpenDocument(firstId)}>
              {firstName}
            </button>
          ) : (
            `${docs.size} documents`
          )}{" "}
          · read by Sustentra&apos;s AI{latest ? ` · ${readOn(latest)}` : ""}
        </p>
        <button type="button" className="s1-mr-link" aria-expanded={!collapsed} onClick={toggle}>
          {collapsed ? "Show summary" : "Hide summary"}
        </button>
      </div>
      {collapsed ? null : (
        <>
          {lines.length ? (
            <div className="s1-mb-summary__block">
              <span className="s1-mr-label">What it found</span>
              {lines.map((line) => (
                <p key={line} className="s1-mb-summary__line">
                  {line}
                </p>
              ))}
            </div>
          ) : null}
          {attention.length ? (
            <div className="s1-mb-summary__block">
              <span className="s1-mr-label">Needs your attention</span>
              <p className="s1-mb-summary__line">
                {attention.length} {attention.length === 1 ? "item" : "items"}:
              </p>
              <span className="s1-mb-summary__chips">
                {attention.map((item) => (
                  <button key={item.fieldId} type="button" className="s1-chip s1-mb-summary__chip" onClick={() => onJump(item.fieldId)}>
                    {item.label}
                  </button>
                ))}
              </span>
            </div>
          ) : null}
          <p className="s1-mb-summary__foot s1-mr-muted">
            {waiting} {waiting === 1 ? "value" : "values"} suggested, waiting for review
            {setAsideTotal ? (
              <>
                {" "}
                · {setAsideTotal} set aside{" "}
                <button type="button" className="s1-mr-link" aria-expanded={details} onClick={() => setDetails(!details)}>
                  Details {details ? "▾" : "▸"}
                </button>
              </>
            ) : null}
          </p>
          {details && setAsideTotal ? (
            <ul className="s1-mb-summary__reasons">
              {setAside.map(([code, n]) => (
                <li key={code} className="s1-mr-muted">
                  {n} · {dropReasonWords(code)}
                </li>
              ))}
            </ul>
          ) : null}
        </>
      )}
    </section>
  );
}
