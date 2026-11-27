"use client";

import { useId, useRef, useState, type KeyboardEvent } from "react";

import { EXACT_COPY } from "../constants/copy";
import type { StateDimension } from "../types";
import { CountBadge } from "./CountBadge";
import { IconChevronLeft } from "./icons";
import { StateIndicator } from "./StateIndicator";

type GlossaryTab = "vocabulary" | "states";
const TABS: { key: GlossaryTab; label: string }[] = [
  { key: "vocabulary", label: "Vocabulary" },
  { key: "states", label: "States" },
];

/** Approved names for codes that are not a plain word. */
const DISPLAY_NAMES: Record<string, string> = {
  facilityResolution: "Facility resolution",
  periodResolution: "Period resolution",
  valueProperty: "Value property",
};

/** "processing" reads as "Processing"; other codes use an approved name, or show as code alone. */
function displayName(code: string): string | null {
  if (DISPLAY_NAMES[code]) return DISPLAY_NAMES[code];
  return /^[a-z]+$/.test(code) ? code[0].toUpperCase() + code.slice(1) : null;
}

/** A term's anchor on the page, so a card can be linked to. */
function slug(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

export function GlossaryPage({ onBack }: { onBack: () => void }) {
  const [tab, setTab] = useState<GlossaryTab>("vocabulary");
  const tabRefs = useRef<Record<GlossaryTab, HTMLButtonElement | null>>({ vocabulary: null, states: null });
  const id = useId();
  const counts: Record<GlossaryTab, number> = { vocabulary: VOCABULARY_ROWS.length, states: STATE_ENUMERATION_ROWS.length };

  const onTabKey = (e: KeyboardEvent<HTMLButtonElement>) => {
    const keys = TABS.map((t) => t.key);
    const at = keys.indexOf(tab);
    const next =
      e.key === "ArrowRight" ? keys[(at + 1) % keys.length]
      : e.key === "ArrowLeft" ? keys[(at - 1 + keys.length) % keys.length]
      : e.key === "Home" ? keys[0]
      : e.key === "End" ? keys[keys.length - 1]
      : null;
    if (!next) return;
    e.preventDefault();
    setTab(next);
    tabRefs.current[next]?.focus();
  };

  return (
    <section className="s1-content s1-glossary-page">
      <button className="s1-linklike s1-linklike--quiet s1-glossary__back" type="button" onClick={onBack}>
        <IconChevronLeft size={14} aria-hidden />
        Back
      </button>
      <header className="s1-ws-header s1-ws-top s1-glossary__head">
        <div className="s1-glossary__titles">
          <div className="s1-ws-header__id">
            <h1>Glossary</h1>
          </div>
          <p className="s1-glossary__intro">{EXACT_COPY.glossaryIntro}</p>
        </div>
        <div role="tablist" aria-label="Glossary section" className="s1-ws-factabs s1-ws-factabs--page s1-glossary__tabs">
          {TABS.map((t) => {
            const on = tab === t.key;
            return (
              <button
                key={t.key}
                ref={(el) => {
                  tabRefs.current[t.key] = el;
                }}
                id={`${id}-tab-${t.key}`}
                type="button"
                role="tab"
                aria-selected={on}
                aria-controls={`${id}-panel-${t.key}`}
                tabIndex={on ? 0 : -1}
                className={`s1-ws-factab${on ? " is-on" : ""}`}
                onClick={() => setTab(t.key)}
                onKeyDown={onTabKey}
              >
                {t.label}
                <CountBadge variant={on ? "indigo" : "neutral"}>{counts[t.key]}</CountBadge>
              </button>
            );
          })}
        </div>
      </header>

      {/* Both panels stay in the page so printing gives the whole glossary; only the chosen one shows on screen. */}
      <div
        className="s1-glossary__panel"
        role="tabpanel"
        id={`${id}-panel-vocabulary`}
        aria-labelledby={`${id}-tab-vocabulary`}
        hidden={tab !== "vocabulary"}
      >
        <h2 className="s1-glossary__print-title">Vocabulary</h2>
        <div className="s1-glossary__cards">
          {VOCABULARY_ROWS.map((row) => (
            <article key={row.term} id={slug(row.term)} className="s1-glossary__card">
              <div className="s1-glossary__card-head">
                <span className={`s1-glossary__dot s1-glossary__dot--${row.group}`} aria-hidden />
                <h2>{row.term}</h2>
              </div>
              <p>{row.means}</p>
            </article>
          ))}
        </div>
      </div>

      <div
        className="s1-glossary__panel"
        role="tabpanel"
        id={`${id}-panel-states`}
        aria-labelledby={`${id}-tab-states`}
        hidden={tab !== "states"}
      >
        <h2 className="s1-glossary__print-title">State enumerations</h2>
        <div className="s1-glossary-states" role="table" aria-label="State enumerations">
          <div className="s1-glossary-states__row s1-glossary-states__row--head" role="row">
            <span role="columnheader">Enumeration</span>
            <span role="columnheader">Attaches to</span>
            <span role="columnheader">Values</span>
          </div>
          {STATE_ENUMERATION_ROWS.map((row) => {
            const name = displayName(row.enumeration);
            return (
              <div key={row.dimension} className="s1-glossary-states__row" role="row">
                <span className="s1-glossary-states__name" role="rowheader">
                  {name ? <span className="s1-glossary-states__display">{name}</span> : null}
                  <span className={name ? "s1-glossary-states__code" : "s1-glossary-states__display"}>{row.enumeration}</span>
                </span>
                <span className="s1-glossary-states__applies" role="cell">
                  {row.attachesTo}
                </span>
                <span className="s1-glossary-states__values" role="cell">
                  {row.values.map((value) => (
                    <StateIndicator key={`${row.dimension}-${value.value}`} dimension={row.dimension} value={value.value} label={value.label} />
                  ))}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

/** UI-only grouping for the card dot: what kind of term it is. */
type TermGroup = "typing" | "attention" | "evidence" | "measure";

const VOCABULARY_ROWS: ReadonlyArray<{ term: string; means: string; group: TermGroup }> = [
  {
    term: "Document typing",
    means: "Detecting what a file is · utility bill, contractual instrument, workbook",
    group: "typing",
  },
  {
    term: "Classification",
    means: "Reserved for scope classification: Scope 1/2/3, and within Scope 2, location- vs market-based",
    group: "typing",
  },
  { term: "Gap", means: "User-facing label for an open finding. Not a separate object", group: "attention" },
  { term: "Finding", means: "The object carrying review state, failure cause, impact, disposition", group: "attention" },
  {
    term: "Request",
    means: "Engagement-level client ask. Many-to-many with findings · one request bundles gaps across several review items",
    group: "attention",
  },
  { term: "Main evidence", means: "Extractable, system-verifiable, links to specific Field_IDs", group: "evidence" },
  {
    term: "Supportive evidence",
    means: "Enters the workpaper, no extraction expected, links to a coarse review area",
    group: "evidence",
  },
  { term: "Type review", means: "The classifier's confidence against the vocabulary threshold", group: "measure" },
  { term: "Fields extracted", means: "How many required fields were found inside a typed document", group: "measure" },
];

const STATE_ENUMERATION_ROWS: Array<{
  dimension: StateDimension;
  enumeration: string;
  attachesTo: string;
  values: Array<{ value: string; label: string }>;
}> = [
  {
    dimension: "processing",
    enumeration: "processing",
    attachesTo: "Evidence item / extraction",
    values: [
      { value: "not_ingested", label: "Not ingested" },
      { value: "ingested", label: "Ingested" },
      { value: "typed", label: "Typed" },
      { value: "extracted", label: "Extracted" },
      { value: "blocked", label: "Blocked" },
    ],
  },
  {
    dimension: "review",
    enumeration: "review",
    attachesTo: "Field / finding",
    values: [
      { value: "unreviewed", label: "Unreviewed" },
      { value: "accepted", label: "Accepted" },
      { value: "corrected", label: "Corrected" },
      { value: "keyed_by_reviewer", label: "human-keyed" },
    ],
  },
  {
    dimension: "check",
    enumeration: "check",
    attachesTo: "Verification check",
    values: [
      { value: "not_system_verified", label: "Not system-verified" },
      { value: "not_applicable", label: "Not applicable" },
      { value: "passed", label: "Passed" },
      { value: "failed", label: "Failed" },
      { value: "not_evaluable", label: "Not evaluable" },
    ],
  },
  {
    dimension: "field",
    enumeration: "field",
    attachesTo: "Schema field",
    values: [
      { value: "populated", label: "Populated" },
      { value: "missing_requestable", label: "Missing · requestable" },
      { value: "missing_not_requestable", label: "Missing · not requestable" },
      { value: "system_key", label: "System key" },
      { value: "not_applicable", label: "Not applicable" },
    ],
  },
  {
    dimension: "facilityResolution",
    enumeration: "facilityResolution",
    attachesTo: "Evidence item",
    values: [
      { value: "resolved", label: "Resolved" },
      { value: "unresolved", label: "Unresolved" },
      { value: "multiple", label: "Multiple" },
      { value: "not_facility_scoped", label: "Not facility-scoped" },
    ],
  },
  {
    dimension: "periodResolution",
    enumeration: "periodResolution",
    attachesTo: "Evidence item",
    values: [
      { value: "resolved", label: "Resolved" },
      { value: "unresolved", label: "Unresolved" },
      { value: "spans_multiple", label: "Spans multiple" },
    ],
  },
  {
    dimension: "valueProperty",
    enumeration: "valueProperty",
    attachesTo: "Extracted value",
    values: [
      { value: "estimated_read", label: "Estimated read" },
      { value: "unit_missing", label: "Unit missing" },
      { value: "unit_ambiguous", label: "Unit ambiguous" },
      { value: "format_mismatch", label: "Format mismatch" },
    ],
  },
  {
    dimension: "readiness",
    enumeration: "readiness",
    attachesTo: "Finding / conclusion readiness",
    values: [
      { value: "non-blocking", label: "Non-blocking" },
      { value: "blocking", label: "Blocking" },
    ],
  },
  {
    dimension: "disposition",
    enumeration: "disposition",
    attachesTo: "Evidence item / finding",
    values: [
      { value: "active", label: "Active" },
      { value: "withdrawn", label: "Withdrawn" },
    ],
  },
  {
    dimension: "request",
    enumeration: "request",
    attachesTo: "Client request",
    values: [
      { value: "requested", label: "Requested" },
      { value: "fulfilled", label: "Fulfilled" },
      { value: "cancelled", label: "Cancelled" },
      { value: "waived_below_threshold", label: "Waived below threshold" },
    ],
  },
];
