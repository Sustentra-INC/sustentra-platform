"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { ChevronDown, ChevronRight, SquareDashed, TextAlignJustify } from "lucide-react";

import { userFacingApiError } from "../api/s1Backend";
import {
  acceptField,
  addRow,
  editField,
  getMethodologyReview,
  prefillMethodology,
  autoReadActive,
  rejectField,
  removeRow,
  revealField,
  pageOf,
  revertField,
  explanationOf,
  sourceLocation,
  type SourceAt,
  type AiStatus,
  type CatalogField,
  type MethodologyRecord,
  type MethodologySuggestion,
  type MethodologyReviewData,
  type MethodologyValue,
  type PrefillResult,
} from "../api/methodologyReview";
import { useAssignTask } from "../../tasks/AssignTaskContext";
import type { EngagementConfig } from "../types";
import type { Ask } from "../types/requests";
import type { MaybePromise } from "../requests/maybePromise";
import { andThen } from "../requests/maybePromise";
import type { AskDraft } from "../requests/requestsStore";
import { dropReasonWords, itemLabel, valueText } from "../utils/methodologyText";
import { MethodologySummary, waitingForReview } from "./MethodologySummary";
import { ActionMenu, type ActionMenuEntry } from "./ActionMenu";
import { AddToRequestsModal, type AddToRequestsTarget } from "./AddToRequestsModal";
import { AiExplainPopover } from "./AiExplainPopover";
import { InfoTip } from "./InfoTip";

/**
 * Methodology review in backend mode: what the client's reports state about the inventory
 * boundary and methods, as Claude's suggestions with their quotes, and the reviewer's
 * decision on each. Fields, groups and allowed values all come from the API's catalog.
 * Claude only suggests; nothing counts until a reviewer accepts or edits it.
 */

const STATUS_WORD: Record<string, string> = { pending: "Pending", accepted: "Accepted", edited: "Edited", rejected: "Rejected" };

const ACTION_WORD: Record<string, string> = {
  accept: "Accepted",
  edit: "Edited",
  reject: "Rejected",
  revert: "Reverted",
  add_row: "Row added",
  remove_row: "Row removed",
};

/** The page is two cards. The API's groups under Methods; every other group sits in Inventory Boundary. */
/** What each section's first column is called, and which sections hold Yes / No answers (their value column reads "Included"). */
const GROUP_ITEM: Record<string, string> = { gases: "Gas", scope1: "Category", scope2: "Category", biogenic: "Type", gwp: "GWP set", factors: "Database" };
const INCLUDED_GROUPS = ["scope1", "scope2", "biogenic"];
/** What a GWP row reads when the document gives no horizon: the GHG Protocol default, labelled as assumed. */
export const GWP_ASSUMED = "100-year (assumed — not stated)";
const isObjectValue = (v: MethodologyValue | undefined): v is { [key: string]: MethodologyValue } => v !== null && typeof v === "object" && !Array.isArray(v);
/** Where each row group's "Add" button lives: the header of the block that holds those rows. */
const ADD_ROW_TEXT: Record<string, string> = { entities: "Add entity", "factor:scope1": "Add source", "factor:scope2": "Add source", gwp: "Add GWP set" };
const ADD_ROW_HOME = ["entities", "factor:scope1", "factor:scope2", "gwp"];
/** Boundary rows that come after the entities (Claire's order: period, approach, entities, exclusions, acquisitions, leased space). */
const BOUNDARY_TAIL = ["exclusion:boundary", "boundary:acquisitions", "boundary:leased_space"];
const METHODS_GROUPS = ["factors", "gwp", "calculation"];
const CARDS = [
  { key: "boundary", title: "Inventory Boundary" },
  { key: "methods", title: "Methods" },
] as const;

/** Button words for the row groups the API lists (it gives codes only); any other code gets a general label. */
const ADD_ROW_LABEL: Record<string, string> = {
  entities: "Add entity",
  "factor:scope1": "Add Scope 1 factor row",
  "factor:scope2": "Add Scope 2 factor row",
  gwp: "Add GWP set",
};

/** Options that stand alone (the server's STANDALONE_OPTIONS): the explicit answer when nothing is named. */
const STANDALONE = ["None", "Not stated"];
const isStandalone = (option: string) => STANDALONE.includes(option);

/** "Mark for client follow-up": what a row needs from the page that mounts it (the same request store as Add to requests). */
export interface FollowUpSupport {
  engagement: EngagementConfig;
  asks: Ask[];
  onSaveAsk: (draft: AskDraft) => MaybePromise<unknown>;
  onOpenRequests?: () => void;
  /** The server records the signed-in user as the person who raised it. */
  serverRecordsActor?: boolean;
}

/** The row's open follow-up request (not yet sent, or sent): one per row. A resolved or withdrawn one is closed. */
export function openFollowUp(asks: Ask[], fieldId: string): Ask | undefined {
  return asks.find((a) => a.source.origin === "methodology_row" && a.source.fieldKey === fieldId && (a.state === "not_yet_sent" || a.state === "requested"));
}

/** "Nov 20, 2026" in the reader's locale, or the stamp as it came when it is not a date. */
function requestedOn(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

/** One folding rule for option names, like the server's: case-folded, single spaces. */
const foldOption = (text: string) => text.toLowerCase().replaceAll("\u00df", "ss").split(/\s+/).filter(Boolean).join(" ");

/** What an empty row reads, by the server's display state. Never "Not set". */
export function emptyWords(status: string, displayState: string | undefined): string {
  if (status === "rejected") return "Rejected, no value";
  if (displayState === "not_detected") return "Not detected";
  if (displayState === "has_value") return "Not decided yet";
  return "Not checked yet";
}

export function statusWord(status: string | undefined | null): string {
  if (!status) return "Pending";
  return STATUS_WORD[status] ?? "Status unknown";
}

const AUTO_READ_POLL_MS = 3000;

/** "a.pdf", "a.pdf and b.xlsx", "a.pdf, b.xlsx and 2 more": the files a read names. */
function fileList(names: string[]): string {
  if (names.length === 0) return "the client's summary documents";
  if (names.length <= 2) return names.join(" and ");
  return `${names.slice(0, 2).join(", ")} and ${names.length - 2} more`;
}

/** Null when Claude can be asked; otherwise the server's sentence for why not. */
export { dropReasonWords, itemLabel, valueText };

export function aiStatusWords(ai: AiStatus): string | null {
  if (ai.enabled && ai.reason_code === null) return null;
  return ai.reason ?? "AI suggestions are not available";
}

function when(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

/** The change-log lines for the activity drawer, from every field's history. */
export function methodologyActivityFrom(data: MethodologyReviewData): { at: string; who: string; what: string }[] {
  const label = new Map(data.catalog.map((f) => [f.fieldId, f.label]));
  return data.fields.flatMap((record) => {
    const name = label.get(record.fieldId) ?? record.fieldId;
    const entries = record.history.map((h) => ({
      at: h.at,
      who: h.by?.name ?? "Reviewer",
      what: `${ACTION_WORD[h.action] ?? h.action.replaceAll("_", " ")} on methodology: ${name}`,
    }));
    if (record.suggestion) entries.push({ at: record.suggestion.suggested_at, who: "Sustentra's AI", what: `Suggested by Sustentra's AI on methodology: ${name}` });
    return entries;
  });
}

// The server's limits on what a reviewer can type (docs/api_contract.md).
const TEXT_MAX = 2000;
const LIST_MAX_ITEMS = 20;
const LIST_ITEM_MAX = 100;
const ENTRY_MAX = 10;
const OPTION_MAX = 60;
const OPTION_WORDING_MAX = 200;
const ENTRY_SOURCE_MAX = 60;
const ENTRY_METHOD_MAX = 300;

/** The label an allowed value shows as, where the catalog gives one. */
const optionLabel = (def: CatalogField, key: string | null, value: string) => (key ? def.allowedLabels?.[key]?.[value] : undefined) ?? value;

/** Editor for one field: an enum select, a text field, or one editor per part, as the catalog's parts say. */
function ValueEditor({
  def,
  start,
  onSave,
  onCancel,
  busy,
}: {
  def: CatalogField;
  start: MethodologyValue;
  onSave: (value: MethodologyValue) => void;
  onCancel: () => void;
  busy: boolean;
}) {
  const current = start !== null && typeof start === "object" && !Array.isArray(start) ? start : {};
  // A part flagged show_if_present (operational control as quoted) is shown, and kept, only when the value has it.
  const parts = def.parts ? def.parts.filter((p) => !p.show_if_present || (current[p.key] !== undefined && current[p.key] !== null)) : null;
  const [draft, setDraft] = useState<Record<string, string>>(() =>
    Object.fromEntries((parts ?? []).map((p) => [p.key, valueText(current[p.key] as MethodologyValue)]))
  );
  const [single, setSingle] = useState(valueText(start));

  const [problem, setProblem] = useState<string | null>(null);
  const range = def.kind === "date_range";
  const listed = def.kind === "entry_list";
  const multi = def.kind === "multiselect" && Array.isArray(def.allowed);
  const listedOptions = multi ? (def.allowed as string[]) : [];
  const [picks, setPicks] = useState<{ option: string; wording: string }[]>(() =>
    Array.isArray(start)
      ? start.map((e) => {
          const o = e !== null && typeof e === "object" && !Array.isArray(e) ? e : {};
          return { option: valueText(o.option as MethodologyValue), wording: valueText(o.wording as MethodologyValue) };
        })
      : []
  );
  const [ownOption, setOwnOption] = useState("");
  const toggle = (option: string) =>
    setPicks((all) => {
      if (all.some((p) => p.option === option)) return all.filter((p) => p.option !== option);
      // "None" and "Not stated" stand alone: choosing one clears the others, and choosing another clears it.
      return isStandalone(option) ? [{ option, wording: "" }] : [...all.filter((p) => !isStandalone(p.option)), { option, wording: "" }];
    });
  const addOwn = () => {
    const text = ownOption.trim();
    const folded = foldOption(text);
    if (!folded) return;
    setProblem(null);
    const alone = STANDALONE.find((o) => foldOption(o) === folded);
    if (alone) return setProblem(`${alone} can't be added as an option of your own.`);
    const listed = listedOptions.find((o) => foldOption(o) === folded);
    if (listed) {
      // an own option that is a listed one selects the listed one
      if (!picks.some((p) => p.option === listed)) toggle(listed);
    } else if (!picks.some((p) => foldOption(p.option) === folded)) {
      setPicks((all) => [...all.filter((p) => !isStandalone(p.option)), { option: text, wording: "" }]);
    }
    setOwnOption("");
  };
  const [entries, setEntries] = useState<{ source_type: string; method: string }[]>(() =>
    Array.isArray(start)
      ? start.map((e) => {
          const o = e !== null && typeof e === "object" && !Array.isArray(e) ? e : {};
          return { source_type: valueText(o.source_type as MethodologyValue), method: valueText(o.method as MethodologyValue) };
        })
      : []
  );
  const [dates, setDates] = useState({ start: typeof current.start === "string" ? current.start : "", end: typeof current.end === "string" ? current.end : "" });

  function save() {
    setProblem(null);
    if (multi) {
      if (picks.length === 0) {
        const alone = STANDALONE.find((o) => listedOptions.includes(o));
        return setProblem(
          alone ? `Choose at least one option, or ${alone} if ${alone === "None" ? "there are none" : "the document does not say"}.` : "Choose at least one option, or reject this row if the company has none."
        );
      }
      return onSave(picks.map((p) => ({ option: p.option, wording: p.wording.trim() })));
    }
    if (listed) {
      const kept = entries.map((e) => ({ source_type: e.source_type.trim(), method: e.method.trim() })).filter((e) => e.source_type || e.method);
      if (kept.some((e) => !e.source_type || !e.method)) return setProblem("Give every entry a source type and a method, or remove it.");
      return onSave(kept);
    }
    if (range) {
      if (!dates.start || !dates.end) return setProblem("Enter both a start date and an end date.");
      return onSave({ start: dates.start, end: dates.end });
    }
    if (!parts) return onSave(single);
    const out: Record<string, MethodologyValue> = {};
    for (const p of parts) {
      const text = draft[p.key] ?? "";
      if (p.kind === "list") {
        const names = text.split(",").map((s) => s.trim()).filter(Boolean);
        if (names.length > LIST_MAX_ITEMS || names.some((n) => n.length > LIST_ITEM_MAX)) {
          return setProblem(`${p.label}: at most ${LIST_MAX_ITEMS} names of ${LIST_ITEM_MAX} characters each.`);
        }
        out[p.key] = names;
      }
      else if (p.kind === "percent") {
        const t = text.trim();
        if (t !== "" && !Number.isFinite(Number(t))) return setProblem(`${p.label}: enter a number from 0 to 100.`);
        out[p.key] = t === "" ? null : Number(t);
      }
      else if (p.kind === "enum" && p.optional && text === "") out[p.key] = null; // optional: the document does not say
      else out[p.key] = text;
    }
    onSave(out);
  }

  const control = (label: string, value: string, set: (v: string) => void, options: string[] | undefined, key: string | null, optional = false) =>
    options ? (
      <select className="s1-mr-select" aria-label={label} value={value} onChange={(e) => set(e.target.value)}>
        <option value="">{optional ? "Not stated" : "Choose"}</option>
        {options.map((o) => (
          <option key={o} value={o}>
            {optionLabel(def, key, o)}
          </option>
        ))}
      </select>
    ) : (
      <input className="s1-mr-input" aria-label={label} maxLength={TEXT_MAX} value={value} onChange={(e) => set(e.target.value)} />
    );

  return (
    <div className="s1-mb-edit">
      {multi ? (
        <div className="s1-mb-list-edit">
          {[...listedOptions, ...picks.map((p) => p.option).filter((o) => !listedOptions.includes(o))].map((option) => {
            const pick = picks.find((p) => p.option === option);
            return (
              <span key={option} className="s1-mr-actions">
                <label className="s1-mb-part">
                  <span className="s1-mr-value">
                    <input type="checkbox" aria-label={`${option}: ${def.label}`} checked={Boolean(pick)} onChange={() => toggle(option)} /> {option}
                  </span>
                </label>
                {pick && !isStandalone(option) ? (
                  <input
                    className="s1-mr-input"
                    aria-label={`Company's wording for ${option}: ${def.label}`}
                    maxLength={OPTION_WORDING_MAX}
                    value={pick.wording}
                    onChange={(e) => setPicks((all) => all.map((x) => (x.option === option ? { ...x, wording: e.target.value } : x)))}
                  />
                ) : null}
              </span>
            );
          })}
          {def.free ? (
            <span className="s1-mr-actions">
              <input className="s1-mr-input" aria-label={`Add another option: ${def.label}`} maxLength={OPTION_MAX} value={ownOption} onChange={(e) => setOwnOption(e.target.value)} />
              <button type="button" className="s1-button s1-button--compact" onClick={addOwn}>
                Add option
              </button>
            </span>
          ) : null}
        </div>
      ) : listed ? (
        <div className="s1-mb-list-edit">
          {entries.map((entry, index) => (
            <span key={index} className="s1-mr-actions">
              <input
                className="s1-mr-input"
                aria-label={`Source type ${index + 1}: ${def.label}`}
                maxLength={ENTRY_SOURCE_MAX}
                value={entry.source_type}
                onChange={(e) => setEntries((all) => all.map((x, i) => (i === index ? { ...x, source_type: e.target.value } : x)))}
              />
              <input
                className="s1-mr-input"
                aria-label={`Method ${index + 1}: ${def.label}`}
                maxLength={ENTRY_METHOD_MAX}
                value={entry.method}
                onChange={(e) => setEntries((all) => all.map((x, i) => (i === index ? { ...x, method: e.target.value } : x)))}
              />
              <button type="button" className="s1-mr-link" aria-label={`Remove entry ${index + 1}: ${def.label}`} onClick={() => setEntries((all) => all.filter((_, i) => i !== index))}>
                Remove
              </button>
            </span>
          ))}
          {entries.length < ENTRY_MAX ? (
            <button type="button" className="s1-button s1-button--compact" onClick={() => setEntries((all) => [...all, { source_type: "", method: "" }])}>
              Add entry
            </button>
          ) : null}
        </div>
      ) : range ? (
        <>
          <label className="s1-mb-part">
            <span className="s1-mr-muted">Start date</span>
            <input className="s1-mr-input" type="date" aria-label={`Start date: ${def.label}`} value={dates.start} onChange={(e) => setDates((d) => ({ ...d, start: e.target.value }))} />
          </label>
          <label className="s1-mb-part">
            <span className="s1-mr-muted">End date</span>
            <input className="s1-mr-input" type="date" aria-label={`End date: ${def.label}`} value={dates.end} onChange={(e) => setDates((d) => ({ ...d, end: e.target.value }))} />
          </label>
        </>
      ) : parts
        ? parts.map((p) => {
            const options = p.allowed ?? (def.allowed && !Array.isArray(def.allowed) ? def.allowed[p.key] : undefined);
            return (
              <label key={p.key} className="s1-mb-part">
                <span className="s1-mr-muted">{p.label}</span>
                {control(`${def.label}: ${p.label}`, draft[p.key] ?? "", (v) => setDraft((d) => ({ ...d, [p.key]: v })), options, p.key, Boolean(p.optional))}
              </label>
            );
          })
        : control(`Value: ${def.label}`, single, setSingle, Array.isArray(def.allowed) ? def.allowed : undefined, null)}
      <span className="s1-mr-actions">
        {problem ? <span className="s1-mb-notice" role="alert">{problem}</span> : null}
        <button type="button" className="s1-button s1-button--compact s1-button--pri" disabled={busy} onClick={save}>
          Save
        </button>
        <button type="button" className="s1-button s1-button--compact" onClick={onCancel}>
          Cancel
        </button>
      </span>
    </div>
  );
}

/** The short source label: "p. 4" for a page; a sheet and cell as they are; "" when the location is unknown. */
export function sourceShort(ref: MethodologySuggestion["source_reference"] | undefined): string {
  const place = sourceLocation(ref);
  const page = /^page\s+(\d+)$/i.exec(place);
  return page ? `p. ${page[1]}` : place;
}

/** A suggestion Accept can take: pending, and not a period saved before it became two dates. */
export function acceptable(def: CatalogField, record: MethodologyRecord): boolean {
  const pendingStatus = (record.decision?.status ?? "pending") === "pending";
  const oldText = def.kind === "date_range" && typeof record.suggestion?.value === "string";
  return Boolean(record.suggestion) && pendingStatus && !oldText;
}

/** The small "p. N" link that opens the document where the quote is. */
function SourceLink({ fileName, reference, documentId, at, onOpen }: { fileName: string; reference: MethodologySuggestion["source_reference"] | undefined; documentId: string; at: SourceAt; onOpen: (documentId: string, at?: SourceAt) => void }) {
  const place = sourceLocation(reference);
  return (
    <button type="button" className="s1-mr-link s1-mb-source" aria-label={place ? `${fileName}, ${place}` : fileName} title={place ? `${fileName}, ${place}` : fileName} onClick={() => onOpen(documentId, at)}>
      {sourceShort(reference) || fileName}
    </button>
  );
}

/** A quote in a muted style on one line (the full text on hover), with Show more when it is cut; `trail` follows it on the same line. */
function Quote({ text, truncated, trail }: { text: string; truncated?: boolean; trail?: ReactNode }) {
  const ref = useRef<HTMLQuoteElement>(null);
  const [open, setOpen] = useState(false);
  const [clipped, setClipped] = useState(false);
  useLayoutEffect(() => {
    const el = ref.current;
    if (el && !open) setClipped(el.scrollHeight > el.clientHeight + 1 || el.scrollWidth > el.clientWidth + 1);
  }, [text, open]);
  return (
    <span className={`s1-mb-quote-wrap${open ? " is-open" : ""}`}>
      <q ref={ref} className={`s1-mb-quote${open ? "" : " is-clamped"}`} title={text}>
        {text}
      </q>
      {truncated ? <span className="s1-mr-muted">(quote shortened)</span> : null}
      {trail}
      {clipped || open ? <ExpandButton open={open} onClick={() => setOpen(!open)} /> : null}
    </span>
  );
}

/** A small icon button that opens or closes a cut-off text. */
function ExpandButton({ open, onClick }: { open: boolean; onClick: () => void }) {
  return (
    <button type="button" className="s1-mb-expand" aria-expanded={open} aria-label={open ? "Show less" : "Show more"} title={open ? "Show less" : "Show more"} onClick={onClick}>
      <ChevronDown aria-hidden />
    </button>
  );
}

/** Long text cut to three lines, with the expand button after it. */
function ClampText({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLSpanElement>(null);
  const [open, setOpen] = useState(false);
  const [clipped, setClipped] = useState(false);
  useLayoutEffect(() => {
    const el = ref.current;
    if (el && !open) setClipped(el.scrollHeight > el.clientHeight + 1);
  }, [children, open]);
  return (
    <span className="s1-mb-clamp">
      <span ref={ref} className={`s1-mr-value s1-mb-clamp__text${open ? "" : " is-clamped"}`}>
        {children}
      </span>
      {clipped || open ? <ExpandButton open={open} onClick={() => setOpen(!open)} /> : null}
    </span>
  );
}

export function FieldRow({
  engagementId,
  def,
  record,
  busy,
  entitiesNamed,
  followUp,
  onMarkFollowUp,
  onAct,
  onOpenDocument,
  selected,
  onSelect,
  quoteNote,
  layout = "list",
  statusCol = true,
}: {
  /** How the row is drawn: a list item (the document page's side panel), or a table body, an entity, factor or GWP table, or one cell of the Scope 2 matrix. */
  layout?: "list" | "table" | "entity" | "factor" | "gwp" | "cell";
  /** Table layout: the section has a Status column (only when some row in it has a status). */
  statusCol?: boolean;
  /** On a document's own page: this row is the one whose quote is highlighted, and a click on the row selects it. */
  selected?: boolean;
  onSelect?: () => void;
  /** A line under a quote (entry null: the suggestion's own), such as "Quote not located on this page". */
  quoteNote?: (entry: number | null) => string | null;
  engagementId: string;
  def: CatalogField;
  record: MethodologyRecord;
  busy: boolean;
  /** True when at least one entity row has a name: then a boundary sentence is not "the only" thing the report gives. */
  entitiesNamed: boolean;
  followUp?: FollowUpSupport;
  onMarkFollowUp: (def: CatalogField) => void;
  onAct: (run: () => Promise<unknown>) => void;
  onOpenDocument: (documentId: string, at?: SourceAt) => void;
}) {
  const [mode, setMode] = useState<"view" | "edit" | "reject">("view");
  const [reason, setReason] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);
  const assign = useAssignTask();
  const { suggestion, decision } = record;
  const status = decision?.status ?? "pending";
  const pendingStatus = status === "pending";
  const decided = status === "accepted" || status === "edited";
  const current = decided ? (Array.isArray(decision?.value) && decision.value.length === 0 ? "No entries" : valueText(decision?.value)) : "";
  // A period saved before it became two dates is kept as the text it was; the reviewer re-enters it as dates.
  const oldText = def.kind === "date_range" && typeof decision?.value === "string" && decision.value ? decision.value : null;
  const suggestionIsOldText = def.kind === "date_range" && typeof suggestion?.value === "string";
  // No suggestion and no value: the row offers "Add value" (nothing to reject).
  const noValue = !suggestion && !current && !oldText;
  const asked = followUp ? openFollowUp(followUp.asks, def.fieldId) : undefined;
  const finish = (run: () => Promise<unknown>) => {
    setMode("view");
    setReason("");
    onAct(run);
  };
  const entries: ActionMenuEntry[] = [
    ...(noValue ? [] : [{ label: "Edit", disabled: busy, action: () => setMode("edit") }]),
    ...(pendingStatus && suggestion ? [{ label: "Reject", disabled: busy, action: () => setMode("reject") }] : []),
    ...(assign
      ? [
          {
            label: "Assign to…",
            action: () =>
              assign({
                kind: "Methodology row",
                label: def.label,
                target: { kind: "methodology_row", item_id: def.fieldId },
                title: `Review methodology: ${def.label}`,
              }),
          },
        ]
      : []),
    ...(followUp && !asked ? [{ label: "Mark for client follow-up", disabled: busy, action: () => onMarkFollowUp(def) }] : []),
    ...(!pendingStatus ? [{ label: "Revert", disabled: busy, action: () => finish(() => revertField(engagementId, def.fieldId)) }] : []),
    ...(record.userAdded ? [{ label: "Remove row", disabled: busy, action: () => finish(() => removeRow(engagementId, def.fieldId)) }] : []),
  ];
  const chip = status === "accepted" ? "accepted" : status === "edited" ? "corrected" : status === "rejected" ? "rejected" : null;
  // With a suggestion showing, "Not decided yet" would only repeat it.
  const showEmpty = !(suggestion && pendingStatus);

  const sourceLines = suggestion ? (
    suggestion.evidence?.length ? (
      <div className="s1-mb-sources">
        {suggestion.evidence.map((item, index) => (
          <div key={index} className="s1-mb-srcline">
            <span className="s1-mr-muted s1-mb-srclabel">{item.label}</span>
            <Quote
              text={item.quote}
              truncated={item.quote_truncated}
              trail={
                <span className="s1-mb-trail">
                  <span aria-hidden> · </span>
                  <SourceLink fileName={item.file_name} reference={item.source_reference} documentId={item.document_id} at={{ fieldId: def.fieldId, entry: index, page: pageOf(item.source_reference) }} onOpen={onOpenDocument} />
                </span>
              }
            />
            {quoteNote?.(index) ? <span className="s1-mb-notlocated">{quoteNote(index)}</span> : null}
          </div>
        ))}
        {suggestion.entries_omitted ? (
          <span className="s1-mr-muted">
            {suggestion.entries_omitted} more {suggestion.entries_omitted === 1 ? "entry was" : "entries were"} found but not shown: their quotes were too long to keep.
          </span>
        ) : null}
      </div>
    ) : (
      <div className="s1-mb-srcline">
        <Quote
          text={suggestion.quote}
          truncated={suggestion.quote_truncated}
          trail={
            <span className="s1-mb-trail">
              <span aria-hidden> · </span>
              <SourceLink fileName={suggestion.file_name} reference={suggestion.source_reference} documentId={suggestion.document_id} at={{ fieldId: def.fieldId, entry: null, page: pageOf(suggestion.source_reference) }} onOpen={onOpenDocument} />
            </span>
          }
        />
        {quoteNote?.(null) ? <span className="s1-mb-notlocated">{quoteNote(null)}</span> : null}
      </div>
    )
  ) : null;
  const marker = suggestion ? (
    <AiExplainPopover
      label="Suggested by Sustentra's AI"
      className="s1-chip s1-mb-chip"
      explanation={explanationOf(record)!}
      onOpenDocument={(documentId, at) => onOpenDocument(documentId, { fieldId: def.fieldId, entry: at.entry, page: at.page })}
    />
  ) : null;
  const statusChip = chip ? <span className={`s1-mr-chip s1-mr-chip--${chip}`}>{statusWord(status)}</span> : !pendingStatus ? <span className="s1-chip">{statusWord(status)}</span> : null;
  const decidedBy = decision && status !== "pending" ? (
    <span className="s1-mr-muted">
      {decision.by.name} · {when(decision.at)}
    </span>
  ) : null;
  const actions =
    mode === "view" ? (
        <span className="s1-mr-actions s1-mb-actions">
          {pendingStatus && suggestion && !suggestionIsOldText ? (
            <button
              type="button"
              className="s1-button s1-button--compact"
              disabled={busy}
              aria-label={`Accept: ${def.label}`}
              onClick={() => finish(() => acceptField(engagementId, def.fieldId))}
            >
              Accept
            </button>
          ) : null}
          {noValue ? (
            <button type="button" className="s1-button s1-button--compact" disabled={busy} aria-label={`Add value: ${def.label}`} onClick={() => setMode("edit")}>
              Add value
            </button>
          ) : null}
          {asked ? (
            <>
              <span className="s1-chip s1-mb-chip">Requested · {requestedOn(asked.raisedAt)}</span>
              {followUp?.onOpenRequests ? (
                <button type="button" className="s1-mr-link" aria-label={`View in requests: ${def.label}`} onClick={followUp.onOpenRequests}>
                  View in requests
                </button>
              ) : null}
            </>
          ) : null}
          {entries.length ? <ActionMenu label={`More actions: ${def.label}`} entries={entries} isOpen={menuOpen} onOpenChange={setMenuOpen} /> : null}
        </span>
      ) : null;
  const editor = (
    <>
      {mode === "edit" ? (
        <div className="s1-mb-wide">
          <ValueEditor
            def={def}
            start={(oldText || suggestionIsOldText ? {} : decided ? decision?.value : suggestion?.value) ?? {}}
            busy={busy}
            onCancel={() => setMode("view")}
            onSave={(value) => finish(() => editField(engagementId, def.fieldId, value))}
          />
        </div>
      ) : mode === "reject" ? (
        <div className="s1-mb-edit s1-mb-wide">
          <input
            className="s1-mr-input"
            aria-label={`Reason: ${def.label}`}
            maxLength={500}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Why is this wrong?"
          />
          <span className="s1-mr-actions">
            <button
              type="button"
              className="s1-button s1-button--compact s1-button--pri"
              disabled={busy || !reason.trim()}
              onClick={() => finish(() => rejectField(engagementId, def.fieldId, reason.trim()))}
            >
              Reject
            </button>
            <button type="button" className="s1-button s1-button--compact" onClick={() => setMode("view")}>
              Cancel
            </button>
          </span>
        </div>
      ) : null}
    </>
  );

  // A row with a fixed list of answers is chosen from inline (C-M1: selection only, no free text).
  const choices = def.kind === "enum" && Array.isArray(def.allowed) && !oldText && !suggestionIsOldText ? def.allowed : null;
  const chosen = current || (suggestion && typeof suggestion.value === "string" ? suggestion.value : "");
  const blankLabel = def.group === "gases" ? "Not mentioned" : record.displayState === "not_detected" ? "Not detected" : "Choose…";
  const pick = (value: string) => {
    if (!value || value === current) return;
    // The suggestion's own value is an Accept; any other choice is an Edit. Both go to the existing endpoints.
    if (pendingStatus && suggestion && suggestion.value === value) finish(() => acceptField(engagementId, def.fieldId));
    else finish(() => editField(engagementId, def.fieldId, value));
  };
  const selectNode = choices ? (
    <select className="s1-mr-select s1-mb-select" aria-label={`Choose: ${def.label}`} disabled={busy} value={chosen} onChange={(e) => pick(e.target.value)}>
      {chosen ? null : <option value="">{blankLabel}</option>}
      {choices.filter((o) => chosen || o !== blankLabel).map((o) => (
        <option key={o} value={o}>
          {o}
        </option>
      ))}
    </select>
  ) : null;
  const shown = decided ? decision?.value : suggestion?.value;
  const parts = isObjectValue(shown) ? shown : {};
  const str = (v: MethodologyValue | undefined) => (typeof v === "string" ? v : "");
  const emptyText = def.group === "gases" && status !== "rejected" ? "Not mentioned" : emptyWords(status, record.displayState);
  const statusBlock = (
    <>
      {statusChip}
      {decidedBy}
      {status === "rejected" && decision?.reason ? <span className="s1-mr-muted">Reason: {decision.reason}</span> : null}
    </>
  );
  const bodyProps = { className: "s1-mb-tbody", "data-status": status, "data-field-id": def.fieldId, "data-selected": selected || undefined, onClick: onSelect };
  const editRow = (cols: number) => (mode !== "view" ? <tr className="s1-mr-editrow"><td colSpan={cols}>{editor}</td></tr> : null);

  if (layout === "entity") {
    const name = str(parts.name);
    // The whole entity goes back as the editor sends it, with one part changed; control as quoted only when it was quoted.
    const saveEntity = (change: { [key: string]: MethodologyValue }) =>
      finish(() =>
        editField(engagementId, def.fieldId, {
          name,
          facilities: Array.isArray(parts.facilities) ? parts.facilities : [],
          equity_share_pct: typeof parts.equity_share_pct === "number" ? parts.equity_share_pct : null,
          financial_control: typeof parts.financial_control === "number" ? parts.financial_control : null,
          included: typeof parts.included === "string" && parts.included ? parts.included : null,
          ...(parts.control_quoted !== undefined && parts.control_quoted !== null ? { control_quoted: parts.control_quoted } : {}),
          ...change,
        })
      );
    const saveName = (typed: string) => {
      const next = typed.trim();
      if (next && next !== name) saveEntity({ name: next });
    };
    const facilities = Array.isArray(parts.facilities) ? parts.facilities.length : 0;
    const controlQuoted = valueText((parts.control_quoted ?? parts.operational_control) as MethodologyValue);
    const equity = typeof parts.equity_share_pct === "number" ? `${parts.equity_share_pct}%` : "";
    return (
      <tbody {...bodyProps}>
        <tr>
          <th scope="row" className="s1-mb-item">
            <span className="s1-sr-only">{def.label}</span>
            <input
              key={name}
              className="s1-mr-input s1-mb-nameinput"
              aria-label={`Name: ${def.label}`}
              placeholder={oldText ? `Recorded as: ${oldText}` : "New entity"}
              maxLength={200}
              disabled={busy}
              defaultValue={name}
              onBlur={(e) => saveName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") e.currentTarget.blur();
                if (e.key === "Escape") {
                  e.currentTarget.value = name;
                  e.currentTarget.blur();
                }
              }}
            />
            {facilities ? <span className="s1-mr-muted"> · {facilities} {facilities === 1 ? "facility" : "facilities"}</span> : null} {marker}
            {statusBlock}
          </th>
          <td className="s1-mb-valuecell">
            <select className="s1-mr-select s1-mb-select" aria-label={`Included: ${def.label}`} disabled={busy || !name} value={str(parts.included)} onChange={(e) => saveEntity({ included: e.target.value === "" ? null : e.target.value })}>
              <option value="">Not stated</option>
              <option value="Yes">Yes</option>
              <option value="No">No</option>
            </select>
            {controlQuoted ? <div className="s1-mr-muted">operational control (as quoted): {controlQuoted}</div> : null}
          </td>
          <td className="s1-mb-valuecell">{equity || <span className="s1-mr-muted">—</span>}</td>
          <td className="s1-mb-sourcecell">{sourceLines}</td>
          <td className="s1-mb-actionscell">{actions}</td>
        </tr>
        {editRow(5)}
      </tbody>
    );
  }

  if (layout === "factor") {
    const database = str(parts.database);
    return (
      <tbody {...bodyProps}>
        <tr>
          <th scope="row" className="s1-mb-item">
            <span className="s1-sr-only">{def.label}</span>
            {database ? database : <span className="s1-mr-none">New source</span>} {marker}
            {statusBlock}
          </th>
          <td className="s1-mb-valuecell">{str(parts.edition) || <span className="s1-mr-muted">—</span>}</td>
          <td className="s1-mb-sourcecell">{sourceLines}</td>
          <td className="s1-mb-actionscell">{actions}</td>
        </tr>
        {editRow(4)}
      </tbody>
    );
  }

  if (layout === "gwp") {
    const set = str(parts.set);
    const horizon = str(parts.horizon);
    const hasSet = Boolean(set);
    return (
      <tbody {...bodyProps}>
        <tr>
          <th scope="row" className="s1-mb-item">
            <span className="s1-sr-only">{def.label}</span>
            {hasSet ? def.allowedLabels?.set?.[set] ?? set : <span className="s1-mr-none">{oldText ? `Recorded as: ${oldText}` : emptyText}</span>} {marker}
            {statusBlock}
          </th>
          <td className="s1-mb-valuecell">{hasSet ? (horizon && horizon !== "Not stated" ? horizon : GWP_ASSUMED) : <span className="s1-mr-muted">—</span>}{hasSet && str(parts.applies_to) ? <span className="s1-mr-muted"> · {str(parts.applies_to)}</span> : null}</td>
          <td className="s1-mb-sourcecell">{sourceLines}</td>
          <td className="s1-mb-actionscell">{actions}</td>
        </tr>
        {editRow(4)}
      </tbody>
    );
  }

  if (layout === "cell") {
    const link = suggestion ? (
      <SourceLink fileName={suggestion.file_name} reference={suggestion.source_reference} documentId={suggestion.document_id} at={{ fieldId: def.fieldId, entry: null, page: pageOf(suggestion.source_reference) }} onOpen={onOpenDocument} />
    ) : null;
    return (
      <td className="s1-mb-cell" data-status={status} data-field-id={def.fieldId} data-selected={selected || undefined} onClick={onSelect}>
        <span className="s1-sr-only">{def.label}</span>
        <div className="s1-mb-cellline">
          {selectNode ?? <span className="s1-mr-value" title={suggestion?.quote}>{current || (suggestion ? valueText(suggestion.value) : <span className="s1-mr-none">{emptyText}</span>)}</span>}
          {marker}
          {statusChip}
          {link}
        </div>
        <div className="s1-mb-cellline">{actions}</div>
        {mode !== "view" ? <div className="s1-mb-celledit">{editor}</div> : null}
      </td>
    );
  }

  if (layout === "table") {
    const valueCell = selectNode ?? (oldText ? <span>Recorded as: {oldText}</span> : current ? current : suggestion ? valueText(suggestion.value) : <span className="s1-mr-none">{emptyText}</span>);
    return (
      <tbody {...bodyProps}>
        <tr>
          <th scope="row" className="s1-mb-item">
            {itemLabel(def)}
          </th>
          <td className="s1-mb-valuecell">
            {selectNode ? valueCell : <ClampText>{valueCell}</ClampText>} {marker}
            {def.value_note && !entitiesNamed && (current || suggestion) ? <span className="s1-mr-muted"> {def.value_note}</span> : null}
            {oldText ? <span className="s1-mr-muted"> Enter the start and end dates with Edit.</span> : null}
            {record.shownNote ? <span className="s1-mr-muted"> {record.shownNote}</span> : null}
          </td>
          <td className="s1-mb-sourcecell">{sourceLines}</td>
          {statusCol ? <td className="s1-mb-statuscell">{statusBlock}</td> : null}
          <td className="s1-mb-actionscell">{actions}</td>
        </tr>
        {editRow(statusCol ? 5 : 4)}
      </tbody>
    );
  }

  return (
    <li className="s1-mb-row" data-status={status} data-field-id={def.fieldId} data-selected={selected || undefined} onClick={onSelect}>
      <div className="s1-mb-body">
        <div className="s1-mb-main">
          <span className="s1-mr-label">{def.label}</span>
          {oldText || current || showEmpty ? (
            <span className="s1-mr-value">{oldText ? <span>Recorded as: {oldText}</span> : current || <span className="s1-mr-none">{emptyWords(status, record.displayState)}</span>}</span>
          ) : null}
          {def.value_note && !entitiesNamed && current ? <span className="s1-mr-muted">{def.value_note}</span> : null}
          {statusChip}
          {decidedBy}
          {oldText ? <span className="s1-mr-muted">Enter the start and end dates with Edit.</span> : null}
          {record.shownNote ? <span className="s1-mr-muted">{record.shownNote}</span> : null}
          {status === "rejected" && decision?.reason ? <span className="s1-mr-muted">Reason: {decision.reason}</span> : null}
        </div>
        {suggestion ? (
          <div className="s1-mb-suggest">
            <div className="s1-mb-suggest__head">
              <span className="s1-mr-value">{valueText(suggestion.value)}</span>
              {marker}
              {def.value_note && !entitiesNamed ? <span className="s1-mr-muted">{def.value_note}</span> : null}
            </div>
            {sourceLines}
          </div>
        ) : null}
      </div>
      {actions}
      {editor}
    </li>
  );
}

export function BackendMethodologyReview({
  engagementId,
  onOpenDocument,
  onError,
  onActivity,
  followUp,
}: {
  engagementId: string;
  onOpenDocument: (documentId: string, at?: SourceAt) => void;
  onError?: (error: unknown) => boolean;
  onActivity?: (entries: { at: string; who: string; what: string }[]) => void;
  /** Present on pages that can raise client requests: adds "Mark for client follow-up" to every row. */
  followUp?: FollowUpSupport;
}) {
  const [requestFor, setRequestFor] = useState<CatalogField | null>(null);
  const [added, setAdded] = useState<string | null>(null);
  const [data, setData] = useState<MethodologyReviewData | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [prefilling, setPrefilling] = useState(false);
  const [show, setShow] = useState<"all" | "review">("all");
  const [acceptingAll, setAcceptingAll] = useState<string | null>(null);
  const [folded, setFolded] = useState<Set<string>>(new Set());
  const prefillRunning = useRef(false);
  const [result, setResult] = useState<PrefillResult | null>(null);
  // Sustentra's AI reading the summary documents by itself after an upload (the backend's marker, polled while it lasts).
  const autoActive = autoReadActive(data?.autoRead);

  const load = useCallback(async () => {
    try {
      const next = await getMethodologyReview(engagementId);
      setData(next);
      setLoadError(null);
      onActivity?.(methodologyActivityFrom(next));
    } catch (error) {
      if (onError?.(error)) return;
      setLoadError(userFacingApiError(error));
    }
  }, [engagementId, onError, onActivity]);

  const onErrorRef = useRef(onError);
  const onActivityRef = useRef(onActivity);
  useEffect(() => {
    onErrorRef.current = onError;
    onActivityRef.current = onActivity;
  });

  useEffect(() => {
    let live = true;
    getMethodologyReview(engagementId)
      .then((next) => {
        if (!live) return;
        setData(next);
          setLoadError(null);
        onActivityRef.current?.(methodologyActivityFrom(next));
      })
      .catch((error: unknown) => {
        if (!live || onErrorRef.current?.(error)) return;
        setLoadError(userFacingApiError(error));
      });
    return () => {
      live = false;
    };
  }, [engagementId]);

  async function act(run: () => Promise<unknown>) {
    setBusy(true);
    setNotice(null);
    try {
      await run();
      await load();
    } catch (error) {
      if (!onError?.(error)) {
        setNotice(userFacingApiError(error));
        await load();
      }
    } finally {
      setBusy(false);
    }
  }

  async function runPrefill() {
    if (prefillRunning.current) return;
    prefillRunning.current = true;
    setConfirming(false);
    setPrefilling(true);
    setBusy(true);
    setNotice(null);
    try {
      setResult(await prefillMethodology(engagementId));
      await load();
    } catch (error) {
      if (!onError?.(error)) setNotice(userFacingApiError(error));
    } finally {
      prefillRunning.current = false;
      setPrefilling(false);
      setBusy(false);
    }
  }

  useEffect(() => {
    if (!autoActive) return;
    const timer = setInterval(() => void load(), AUTO_READ_POLL_MS);
    return () => clearInterval(timer);
  }, [autoActive, load]);

  const records = useMemo(() => new Map((data?.fields ?? []).map((r) => [r.fieldId, r])), [data]);
  // Headings and their order come from the API's groups; rows come in catalog order.
  const groups = useMemo(
    () =>
      (data?.groups ?? [])
        .map((g) => {
          const visible = (d: CatalogField) => records.get(d.fieldId)?.shown !== false && records.has(d.fieldId);
          let all = (data?.catalog ?? []).filter((d) => d.group === g.group && visible(d));
          // Claire's order: the exclusion of the boundary sits with the boundary, after the entities.
          if (g.group === "exclusions") all = all.filter((d) => d.fieldId !== "exclusion:boundary");
          if (g.group === "boundary") all = [...all, ...(data?.catalog ?? []).filter((d) => d.fieldId === "exclusion:boundary" && d.group === "exclusions" && visible(d))];
          const toAccept = all.filter((d) => acceptable(d, records.get(d.fieldId)!));
          // "Needs review": a suggestion still waiting for the reviewer.
          const defs = show === "review" ? all.filter((d) => records.get(d.fieldId)?.suggestion && (records.get(d.fieldId)?.decision?.status ?? "pending") === "pending") : all;
          return { ...g, defs, toAccept };
        })
        .filter((g) => g.defs.length > 0),
    [data, records, show]
  );

  // Optional rows with nothing on them stay off the page until "Add an item" brings one on.
  const hiddenOptional = (data?.catalog ?? []).filter((d) => records.get(d.fieldId)?.shown === false);

  if (!data) {
    return (
      <section className="s1-content">
        <p role={loadError ? "alert" : "status"}>{loadError ?? "Loading the methodology review."}</p>
      </section>
    );
  }

  const aiOff = aiStatusWords(data.ai);
  // An entity row counts once it has a name: the reviewer's decision, or Claude's suggestion while still undecided.
  const entitiesNamed = data.catalog.some((d) => {
    if (d.kind !== "entity") return false;
    const r = records.get(d.fieldId);
    const v = r?.decision && r.decision.status !== "pending" ? r.decision.value : r?.suggestion?.value;
    return v !== null && typeof v === "object" && !Array.isArray(v) && typeof v.name === "string" && v.name.trim() !== "";
  });
  const pending = waitingForReview(data);
  // A chip in the summary: open the row's section, drop the filter and bring the row into view.
  function jump(fieldId: string) {
    const def = data?.catalog.find((d) => d.fieldId === fieldId);
    setShow("all");
    if (def) setFolded((f) => new Set([...f].filter((g) => g !== def.group)));
    window.setTimeout(() => {
      const el = Array.from(document.querySelectorAll("[data-field-id]")).find((e) => e.getAttribute("data-field-id") === fieldId);
      el?.scrollIntoView?.({ block: "center", behavior: "smooth" });
    }, 0);
  }

  const rowFor = (def: CatalogField, layout: "table" | "entity" | "factor" | "gwp" | "cell", statusCol = true) => (
    <FieldRow layout={layout} statusCol={statusCol} key={def.fieldId} engagementId={engagementId} def={def} record={records.get(def.fieldId)!} busy={busy} entitiesNamed={entitiesNamed} followUp={followUp} onMarkFollowUp={setRequestFor} onAct={(run) => void act(run)} onOpenDocument={onOpenDocument} />
  );
  const addButton = (rowGroup: string) =>
    data.rowGroups.includes(rowGroup) ? (
      <button type="button" className="s1-button s1-button--compact" disabled={busy} aria-label={ADD_ROW_LABEL[rowGroup] ?? "Add row"} onClick={() => void act(() => addRow(engagementId, rowGroup))}>
        + {ADD_ROW_TEXT[rowGroup] ?? "Add row"}
      </button>
    ) : null;
  const tableOf = (heads: string[], rows: ReactNode, cols: string[]) => (
    <div className="s1-mr-scroll">
      <table className="s1-mr-table s1-mb-table">
        <colgroup>
          {cols.map((c, i) => (
            <col key={i} className={c} />
          ))}
        </colgroup>
        <thead>
          <tr>
            {heads.map((h) => (
              <th key={h} scope="col">
                {h === "Actions" ? <span className="s1-sr-only">Actions</span> : h}
              </th>
            ))}
          </tr>
        </thead>
        {rows}
      </table>
    </div>
  );
  const genericTable = (group: string, defs: CatalogField[]) => {
    if (!defs.length) return null;
    // The Status column appears only when some row in the table has a status to show.
    const statusCol = defs.some((d) => {
      const st = records.get(d.fieldId)?.decision?.status ?? "pending";
      return st !== "pending";
    });
    return tableOf(
      [GROUP_ITEM[group] ?? "Item", INCLUDED_GROUPS.includes(group) ? "Included" : "Value", "Source", ...(statusCol ? ["Status"] : []), "Actions"],
      defs.map((d) => rowFor(d, "table", statusCol)),
      ["s1-mb-col-item", "s1-mb-col-value", "", ...(statusCol ? ["s1-mb-col-status"] : []), "s1-mb-col-actions"]
    );
  };
  const block = (title: string, add: ReactNode, body: ReactNode) => (
    <div className="s1-mb-block">
      <div className="s1-mb-subhead">
        <span className="s1-mr-label">{title}</span>
        {add}
      </div>
      {body}
    </div>
  );
  /** One section's body: its rows as tables, with the entities, factor sources, GWP sets and the Scope 2 matrix as tables of their own. */
  function renderBody(group: string, defs: CatalogField[]): ReactNode {
    const kind = (k: string) => defs.filter((d) => d.kind === k);
    const plain = defs.filter((d) => !["entity", "factor", "gwp"].includes(d.kind));
    const review = show === "review";
    if (group === "boundary") {
      const tail = plain.filter((d) => BOUNDARY_TAIL.includes(d.fieldId)).sort((a, b) => BOUNDARY_TAIL.indexOf(a.fieldId) - BOUNDARY_TAIL.indexOf(b.fieldId));
      const head = plain.filter((d) => !BOUNDARY_TAIL.includes(d.fieldId));
      const entities = kind("entity");
      const addEntity = addButton("entities");
      return (
        <>
          {genericTable(group, head)}
          {entities.length || (addEntity && !review)
            ? block(
                "Entities",
                addEntity,
                tableOf(["Name", "Included", "Equity %", "Source", `Review · ${entities.filter((d) => ["accepted", "edited"].includes(records.get(d.fieldId)?.decision?.status ?? "")).length} of ${entities.length}`], entities.map((d) => rowFor(d, "entity")), ["s1-mb-col-name", "s1-mb-col-value", "s1-mb-col-pct", "", "s1-mb-col-actions"])
              )
            : null}
          {genericTable(group, tail)}
        </>
      );
    }
    if (group === "scope2") {
      const find = (basis: string, k: string) => defs.find((d) => d.fieldId === `category:${basis}:${k}`);
      const keys = ["electricity", "steam", "heating", "cooling"].filter((k) => find("location", k) || find("market", k));
      const rest = plain.filter((d) => !d.fieldId.startsWith("category:location:") && !d.fieldId.startsWith("category:market:"));
      return (
        <>
          {keys.length
            ? tableOf(
                ["Category", "Location-based", "Market-based"],
                <tbody className="s1-mb-tbody">
                  {keys.map((k) => {
                    const loc = find("location", k);
                    const mkt = find("market", k);
                    const any = (loc ?? mkt)!;
                    return (
                      <tr key={k}>
                        <th scope="row" className="s1-mb-item">
                          {any.label.replace(/^(Location|Market)-based\s+/i, "")}
                        </th>
                        {loc ? rowFor(loc, "cell") : <td />}
                        {mkt ? rowFor(mkt, "cell") : <td />}
                      </tr>
                    );
                  })}
                </tbody>,
                ["s1-mb-col-item", "s1-mb-col-matrix", "s1-mb-col-matrix"]
              )
            : null}
          {genericTable(group, rest)}
        </>
      );
    }
    if (group === "factors") {
      const s1 = kind("factor").filter((d) => d.fieldId.startsWith("factor:scope1"));
      const s2 = kind("factor").filter((d) => !d.fieldId.startsWith("factor:scope1"));
      const factor = (title: string, rows: CatalogField[], rowGroup: string) => {
        const add = addButton(rowGroup);
        return rows.length || (add && !review)
          ? block(title, add, tableOf(["Database", "Edition", "Source", "Actions"], rows.map((d) => rowFor(d, "factor")), ["s1-mb-col-name", "s1-mb-col-value", "", "s1-mb-col-actions"]))
          : null;
      };
      return (
        <>
          {factor("Scope 1", s1, "factor:scope1")}
          {factor("Scope 2", s2, "factor:scope2")}
          {genericTable(group, plain)}
        </>
      );
    }
    if (group === "gwp") {
      return (
        <>
          {tableOf(["GWP set", "Time horizon", "Source", "Actions"], kind("gwp").map((d) => rowFor(d, "gwp")), ["s1-mb-col-name", "s1-mb-col-value", "", "s1-mb-col-actions"])}
          {genericTable(group, plain)}
        </>
      );
    }
    return genericTable(group, defs);
  }

  return (
    <section className="s1-content s1-mb">
      <header className="s1-mb-top">
        <h2 className="s1-mr-card__title">
          Methodology review
          <InfoTip label="Methodology review">
            Sustentra&apos;s AI reads the client&apos;s reports and suggests what they state, each with a quote. Nothing counts until you accept or edit it.
          </InfoTip>
        </h2>
        <span className="s1-mr-muted">{pending} suggested, waiting for review</span>
        <div className="s1-actlog__kinds" role="group" aria-label="Show">
          <span className="s1-mr-muted">Show:</span>
          {(["all", "review"] as const).map((key) => (
            <button key={key} type="button" className={`s1-actlog__kind${show === key ? " is-on" : ""}`} aria-pressed={show === key} onClick={() => setShow(key)}>
              {key === "all" ? "All" : "Needs review"}
            </button>
          ))}
        </div>
        <span className="s1-mr-actions">
          <button type="button" className="s1-button s1-button--pri" disabled={busy || prefilling || data.autoRead?.state === "reading" || aiOff !== null} onClick={() => setConfirming(true)}>
            {prefilling ? "Reading the reports…" : "Read the client's reports with Sustentra's AI"}
          </button>
          {aiOff ? <span className="s1-mb-ai">{aiOff}</span> : null}
        </span>
      </header>

      {confirming ? (
        <div className="s1-mb-confirm" role="alertdialog" aria-label="Read the client's reports">
          <p>
            Sustentra&apos;s AI will read this engagement&apos;s report documents (the GHG inventory report, boundary statement and methodology documents, up to five) and suggest values with quotes. Suggestions need your review before they count. The result will list the documents it read.
          </p>
          <span className="s1-mr-actions">
            <button type="button" className="s1-button s1-button--pri" disabled={prefilling} onClick={() => void runPrefill()}>
              Read the reports
            </button>
            <button type="button" className="s1-button" onClick={() => setConfirming(false)}>
              Cancel
            </button>
          </span>
        </div>
      ) : null}

      {autoActive && data.autoRead ? (
        <p className="s1-mb-result" role="status">
          {data.autoRead.state === "reading"
            ? `Sustentra's AI is reading ${fileList(data.autoRead.file_names)}…`
            : `Sustentra's AI will read ${fileList(data.autoRead.file_names)} shortly…`}
        </p>
      ) : null}
      {!autoActive && data.autoRead?.state === "failed" ? (
        <p className="s1-mb-notice" role="alert">
          {data.autoRead.reason ?? "Sustentra's AI could not read the documents."}{" "}
          <button type="button" className="s1-button" disabled={busy || prefilling || aiOff !== null} onClick={() => void runPrefill()}>
            Try again
          </button>
        </p>
      ) : null}
      {!autoActive && data.autoRead?.state === "skipped" && data.autoRead.reason ? (
        <p className="s1-mb-ai" role="status">
          Not read automatically: {data.autoRead.reason}
        </p>
      ) : null}
      {/* A finished read shows as the summary below (MethodologySummary), built from the stored suggestions. */}

      {notice ? (
        <p className="s1-mb-notice" role="alert">
          {notice}
        </p>
      ) : null}

      <MethodologySummary engagementId={engagementId} data={data} result={result} onOpenDocument={onOpenDocument} onJump={jump} />

      {data.rowGroups.some((g) => !ADD_ROW_HOME.includes(g)) ? (
        <span className="s1-mr-actions">
          {data.rowGroups.filter((g) => !ADD_ROW_HOME.includes(g)).map((rowGroup) => (
            <button key={rowGroup} type="button" className="s1-button s1-button--compact" disabled={busy} onClick={() => void act(() => addRow(engagementId, rowGroup))}>
              {ADD_ROW_LABEL[rowGroup] ?? "Add row"}
            </button>
          ))}
        </span>
      ) : null}

      {hiddenOptional.length ? (
        <select
          className="s1-mr-input"
          aria-label="Add an item"
          disabled={busy}
          value=""
          onChange={(event) => {
            const fieldId = event.target.value;
            if (fieldId) void act(() => revealField(engagementId, fieldId));
          }}
        >
          <option value="">Add an item</option>
          {hiddenOptional.map((d) => (
            <option key={d.fieldId} value={d.fieldId}>
              {d.label}
            </option>
          ))}
        </select>
      ) : null}

      {show === "review" && groups.length === 0 ? <p className="s1-mr-muted">Nothing is waiting for review.</p> : null}

      {CARDS.map((card) => {
        const inCard = groups.filter((g) => (METHODS_GROUPS.includes(g.group) ? "methods" : "boundary") === card.key);
        if (inCard.length === 0) return null;
        return (
          <section key={card.key} className="s1-mr-card" aria-labelledby={`s1-mb-card-${card.key}`}>
            <div className="s1-mr-card__head">
              <span className={`s1-mr-card__icon s1-mr-card__icon--${card.key}`}>{card.key === "boundary" ? <SquareDashed aria-hidden /> : <TextAlignJustify aria-hidden />}</span>
              <h2 id={`s1-mb-card-${card.key}`} className="s1-mr-card__title">
                {card.title}
              </h2>
            </div>
            <div className="s1-mr-card__body">
              {inCard.map(({ group, label, defs, toAccept }) => {
                const open = show === "review" || !folded.has(group);
                return (
                  <div key={group} className={`s1-mr-group${open ? " is-open" : ""}`}>
                    <div className="s1-mb-groupbar">
                      <h3 className="s1-mb-grouph">
                        <button className="s1-mr-group__head" type="button" aria-expanded={open} onClick={() => setFolded((f) => { const n = new Set(f); if (n.has(group)) n.delete(group); else n.add(group); return n; })}>
                          <ChevronRight className="s1-mr-chev" aria-hidden />
                          <span className="s1-mr-group__title">{label}</span>
                        </button>
                      </h3>
                      {group === "gwp" ? addButton("gwp") : null}
                      {toAccept.length ? (
                        <button type="button" className="s1-button s1-button--compact" disabled={busy} onClick={() => setAcceptingAll(group)}>
                          Accept all suggestions in this section
                        </button>
                      ) : null}
                    </div>
                    {acceptingAll === group && toAccept.length ? (
                      <div className="s1-mb-confirm s1-mb-confirm--section" role="alertdialog" aria-label={`Accept all suggestions in ${label}`}>
                        <p>
                          Accept {toAccept.length} {toAccept.length === 1 ? "suggestion" : "suggestions"} in {label}? Each is recorded as accepted by you.
                        </p>
                        <span className="s1-mr-actions">
                          <button
                            type="button"
                            className="s1-button s1-button--pri"
                            disabled={busy}
                            onClick={() => {
                              setAcceptingAll(null);
                              void act(async () => {
                                for (const d of toAccept) await acceptField(engagementId, d.fieldId);
                              });
                            }}
                          >
                            Accept {toAccept.length}
                          </button>
                          <button type="button" className="s1-button" onClick={() => setAcceptingAll(null)}>
                            Cancel
                          </button>
                        </span>
                      </div>
                    ) : null}
                    {open ? (
                      <div className="s1-mb-groupbody">{renderBody(group, defs)}</div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </section>
        );
      })}

      {added ? (
        <p className="s1-mb-result" role="status">
          {added}
        </p>
      ) : null}

      {followUp && requestFor ? (
        <AddToRequestsModal
          target={followUpTarget(requestFor, records.get(requestFor.fieldId), followUp.engagement)}
          engagement={followUp.engagement}
          serverRecordsActor={followUp.serverRecordsActor}
          onCancel={() => setRequestFor(null)}
          onAdd={(draft) =>
            andThen(followUp.onSaveAsk(draft), () => {
              setRequestFor(null);
              setAdded(`${requestFor.label}: added to requests, not sent yet.`);
            })
          }
        />
      ) : null}
    </section>
  );
}

/** The Add to requests window's target for a Methodology row: the row's label and what it holds now. */
export function followUpTarget(def: CatalogField, record: MethodologyRecord | undefined, engagement: EngagementConfig): AddToRequestsTarget {
  const decided = record?.decision && record.decision.status !== "pending" ? record.decision.value : null;
  const now = valueText((decided ?? record?.suggestion?.value) as MethodologyValue);
  const year = engagement.reportingPeriod.start.slice(0, 4);
  return {
    origin: "methodology_row",
    fieldKey: def.fieldId,
    itemLabel: def.label,
    facilityName: null,
    period: year ? `FY ${year}` : null,
    headerLine: `Methodology review · ${def.label}`,
    defaultType: "clarify",
    prefill: now ? `${def.label}: please confirm. We have "${now.slice(0, 300)}".` : `${def.label}: please tell us what applies.`,
  };
}
