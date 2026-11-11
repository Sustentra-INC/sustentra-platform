"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { userFacingApiError } from "../api/s1Backend";
import {
  acceptField,
  addRow,
  editField,
  getMethodologyReview,
  prefillMethodology,
  rejectField,
  removeRow,
  revertField,
  type AiStatus,
  type CatalogField,
  type MethodologyRecord,
  type MethodologyReviewData,
  type MethodologyValue,
  type PrefillResult,
  type RowGroup,
} from "../api/methodologyReview";
import { InfoTip } from "./InfoTip";

/**
 * Methodology review in backend mode: what the client's reports state about the inventory
 * boundary and methods, as Claude's suggestions with their quotes, and the reviewer's
 * decision on each. Fields, groups and allowed values all come from the API's catalog.
 * Claude only suggests; nothing counts until a reviewer accepts or edits it.
 */

const STATUS_WORD: Record<string, string> = { pending: "Pending", accepted: "Accepted", edited: "Edited", rejected: "Rejected" };

/** Plain words for why a suggestion batch was dropped; an unknown code shows as its own words. */
const DROP_REASON: Record<string, string> = {
  quote_not_found: "the quote was not on the document",
  line_not_found: "the cited line did not exist",
  value_not_in_quote: "the number was not in the quote",
  not_in_catalog: "the value was not an allowed one",
  unknown_field: "the field is not one we review",
  document_not_found: "the document was not one it was given",
  kept_reviewer_decision: "a reviewer had already decided",
};

export function statusWord(status: string | undefined | null): string {
  if (!status) return "Pending";
  return STATUS_WORD[status] ?? "Status unknown";
}

export function dropReasonWords(code: string): string {
  return DROP_REASON[code] ?? code.replaceAll("_", " ");
}

/** The AI switch in words, or null when Claude can be asked. An unknown reason code gets a general sentence. */
export function aiStatusWords(ai: AiStatus, hasDocuments: boolean | null): string | null {
  if (!ai.enabled) {
    const reason = (ai.reason_if_off ?? "").toLowerCase();
    if (/cap|limit|spend/.test(reason)) return "Monthly limit reached";
    if (/document/.test(reason)) return "No report documents yet";
    if (/off|disabled|switch|admin|flag/.test(reason)) return "Off: an administrator turns it on";
    if (reason.includes(" ")) return ai.reason_if_off ?? null;
    return "AI suggestions are not available";
  }
  if (ai.cap_usd != null && ai.month_spend_usd != null && ai.month_spend_usd >= ai.cap_usd) return "Monthly limit reached";
  if (hasDocuments === false) return "No report documents yet";
  return null;
}

function valueText(value: MethodologyValue | undefined): string {
  if (value === null || value === undefined || value === "") return "";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object") {
    return Object.entries(value)
      .map(([, v]) => valueText(v))
      .filter(Boolean)
      .join(" · ");
  }
  return String(value);
}

const humanise = (text: string) => {
  const spaced = text.replaceAll(/[_:]/g, " ").trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
};

function when(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

/** The change-log lines for the activity drawer, from every field's history. */
export function methodologyActivityFrom(data: MethodologyReviewData): { at: string; who: string; what: string }[] {
  const label = new Map(data.catalog.map((f) => [f.fieldId, f.label]));
  return data.fields.flatMap((record) =>
    record.history.map((h) => ({
      at: h.at,
      who: h.by?.name ?? "Reviewer",
      what: `${h.action.replaceAll("_", " ")} on methodology: ${label.get(record.fieldId) ?? record.fieldId}`,
    }))
  );
}

function isUserAdded(def: CatalogField, record: MethodologyRecord): boolean {
  if (def.userAdded) return true;
  return !record.suggestion && /add/i.test(record.history[0]?.action ?? "");
}

const ROW_GROUPS: { prefix: string; group: RowGroup; label: string }[] = [
  { prefix: "entity:", group: "entities", label: "Add entity" },
  { prefix: "factor:scope1:", group: "factor:scope1", label: "Add Scope 1 factor row" },
  { prefix: "factor:scope2:", group: "factor:scope2", label: "Add Scope 2 factor row" },
];

/** Editor for one field: an enum select, a text field, or a field per part of a multi-part value. */
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
  const parts = start !== null && typeof start === "object" && !Array.isArray(start) ? start : null;
  const allowedMap = def.allowed && !Array.isArray(def.allowed) ? def.allowed : null;
  const keys = parts ? Array.from(new Set([...Object.keys(parts), ...Object.keys(allowedMap ?? {})])) : [];
  const [draft, setDraft] = useState<Record<string, string>>(() =>
    Object.fromEntries(keys.map((k) => [k, valueText(parts?.[k] as MethodologyValue)]))
  );
  const [single, setSingle] = useState(valueText(start));

  function save() {
    if (!parts) return onSave(single);
    const out: Record<string, MethodologyValue> = {};
    for (const k of keys) {
      const original = parts[k];
      const text = draft[k] ?? "";
      if (Array.isArray(original)) out[k] = text.split(",").map((s) => s.trim()).filter(Boolean);
      else if (typeof original === "number") out[k] = text.trim() === "" ? null : Number(text);
      else out[k] = text;
    }
    onSave(out);
  }

  const control = (label: string, value: string, set: (v: string) => void, options?: string[]) =>
    options ? (
      <select className="s1-mr-select" aria-label={label} value={value} onChange={(e) => set(e.target.value)}>
        <option value="">Choose</option>
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    ) : (
      <input className="s1-mr-input" aria-label={label} value={value} onChange={(e) => set(e.target.value)} />
    );

  return (
    <div className="s1-mb-edit">
      {parts
        ? keys.map((k) => (
            <label key={k} className="s1-mb-part">
              <span className="s1-mr-muted">{humanise(k)}</span>
              {control(`${def.label}: ${humanise(k)}`, draft[k] ?? "", (v) => setDraft((d) => ({ ...d, [k]: v })), allowedMap?.[k])}
            </label>
          ))
        : control(`Value: ${def.label}`, single, setSingle, Array.isArray(def.allowed) ? def.allowed : undefined)}
      <span className="s1-mr-actions">
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

function FieldRow({
  engagementId,
  def,
  record,
  busy,
  onAct,
  onOpenDocument,
}: {
  engagementId: string;
  def: CatalogField;
  record: MethodologyRecord;
  busy: boolean;
  onAct: (run: () => Promise<unknown>) => void;
  onOpenDocument: (documentId: string) => void;
}) {
  const [mode, setMode] = useState<"view" | "edit" | "reject">("view");
  const [reason, setReason] = useState("");
  const { suggestion, decision } = record;
  const status = decision?.status ?? "pending";
  const decided = status === "accepted" || status === "edited";
  const current = decided ? valueText(decision?.value) : "";
  const finish = (run: () => Promise<unknown>) => {
    setMode("view");
    setReason("");
    onAct(run);
  };

  return (
    <li className="s1-mb-row" data-status={status}>
      <div className="s1-mb-main">
        <span className="s1-mr-label">{def.label}</span>
        <span className="s1-mr-value">{current || <span className="s1-mr-none">{status === "rejected" ? "Rejected" : "Not set"}</span>}</span>
        <span className="s1-mb-status">{statusWord(status)}</span>
        {decision && status !== "pending" ? (
          <span className="s1-mr-muted">
            {decision.by.name} · {when(decision.at)}
          </span>
        ) : null}
        {status === "rejected" && decision?.reason ? <span className="s1-mr-muted">Reason: {decision.reason}</span> : null}
      </div>

      {suggestion ? (
        <div className="s1-mb-suggest">
          <span className="s1-chip s1-mb-chip">Suggested by Claude</span>
          <span className="s1-mr-value">{valueText(suggestion.value)}</span>
          <q className="s1-mb-quote">{suggestion.quote}</q>
          <button type="button" className="s1-mr-link" onClick={() => onOpenDocument(suggestion.document_id)}>
            {suggestion.file_name}
            {suggestion.source_reference ? `, ${suggestion.source_reference}` : ""}
          </button>
        </div>
      ) : null}

      {mode === "edit" ? (
        <ValueEditor
          def={def}
          start={(decided ? decision?.value : suggestion?.value) ?? {}}
          busy={busy}
          onCancel={() => setMode("view")}
          onSave={(value) => finish(() => editField(engagementId, def.fieldId, value))}
        />
      ) : mode === "reject" ? (
        <div className="s1-mb-edit">
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
      ) : (
        <span className="s1-mr-actions">
          <button
            type="button"
            className="s1-button s1-button--compact"
            disabled={busy || (!suggestion && !decided)}
            aria-label={`Accept: ${def.label}`}
            onClick={() => finish(() => acceptField(engagementId, def.fieldId))}
          >
            Accept
          </button>
          <button type="button" className="s1-button s1-button--compact" disabled={busy} aria-label={`Edit: ${def.label}`} onClick={() => setMode("edit")}>
            Edit
          </button>
          <button type="button" className="s1-button s1-button--compact" disabled={busy} aria-label={`Reject: ${def.label}`} onClick={() => setMode("reject")}>
            Reject
          </button>
          {decision && status !== "pending" ? (
            <button type="button" className="s1-mr-link" disabled={busy} aria-label={`Revert: ${def.label}`} onClick={() => finish(() => revertField(engagementId, def.fieldId))}>
              Revert
            </button>
          ) : null}
          {isUserAdded(def, record) ? (
            <button type="button" className="s1-mr-link" disabled={busy} aria-label={`Remove row: ${def.label}`} onClick={() => finish(() => removeRow(engagementId, def.fieldId))}>
              Remove row
            </button>
          ) : null}
        </span>
      )}
    </li>
  );
}

export function BackendMethodologyReview({
  engagementId,
  onOpenDocument,
  onError,
  onActivity,
}: {
  engagementId: string;
  onOpenDocument: (documentId: string) => void;
  onError?: (error: unknown) => boolean;
  onActivity?: (entries: { at: string; who: string; what: string }[]) => void;
}) {
  const [data, setData] = useState<MethodologyReviewData | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [result, setResult] = useState<PrefillResult | null>(null);

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
      if (!onError?.(error)) setNotice(userFacingApiError(error));
    } finally {
      setBusy(false);
    }
  }

  async function runPrefill() {
    setConfirming(false);
    setBusy(true);
    setNotice(null);
    try {
      setResult(await prefillMethodology(engagementId));
      await load();
    } catch (error) {
      if (!onError?.(error)) setNotice(userFacingApiError(error));
    } finally {
      setBusy(false);
    }
  }

  const records = useMemo(() => new Map((data?.fields ?? []).map((r) => [r.fieldId, r])), [data]);
  const groups = useMemo(() => {
    const out = new Map<string, CatalogField[]>();
    for (const def of data?.catalog ?? []) {
      if (!records.has(def.fieldId)) continue;
      out.set(def.group, [...(out.get(def.group) ?? []), def]);
    }
    return Array.from(out.entries());
  }, [data, records]);

  if (!data) {
    return (
      <section className="s1-content">
        <p role={loadError ? "alert" : "status"}>{loadError ?? "Loading the methodology review."}</p>
      </section>
    );
  }

  const suggestedDocs = result?.documents_read ?? [];
  const aiOff = aiStatusWords(data.ai, null);
  const droppedEntries = result ? Object.entries(result.dropped).filter(([, n]) => n > 0) : [];
  const pending = data.fields.filter((r) => r.suggestion && (!r.decision || r.decision.status === "pending")).length;

  return (
    <section className="s1-content s1-mb">
      <header className="s1-mb-top">
        <h2 className="s1-mr-card__title">
          Methodology review
          <InfoTip label="Methodology review">
            Claude reads the client&apos;s reports and suggests what they state, each with a quote. Nothing counts until you accept or edit it.
          </InfoTip>
        </h2>
        <span className="s1-mr-muted">{pending} suggested, waiting for review</span>
        <span className="s1-mr-actions">
          <button type="button" className="s1-button s1-button--pri" disabled={busy || aiOff !== null} onClick={() => setConfirming(true)}>
            Read the client&apos;s reports with Claude
          </button>
          {aiOff ? <span className="s1-mb-ai">{aiOff}</span> : null}
        </span>
      </header>

      {confirming ? (
        <div className="s1-mb-confirm" role="alertdialog" aria-label="Read the client's reports">
          <p>
            Claude will read this engagement&apos;s report documents (the GHG inventory report, boundary statement and methodology documents, up to five) and suggest values with quotes. Suggestions need your review before they count.
          </p>
          <span className="s1-mr-actions">
            <button type="button" className="s1-button s1-button--pri" onClick={() => void runPrefill()}>
              Read the reports
            </button>
            <button type="button" className="s1-button" onClick={() => setConfirming(false)}>
              Cancel
            </button>
          </span>
        </div>
      ) : null}

      {notice ? (
        <p className="s1-mb-notice" role="alert">
          {notice}
        </p>
      ) : null}

      {result ? (
        <p className="s1-mb-result" role="status">
          {result.suggested} suggested
          {droppedEntries.length
            ? `, ${droppedEntries.reduce((n, [, c]) => n + c, 0)} dropped (${droppedEntries.map(([code, n]) => `${n}: ${dropReasonWords(code)}`).join("; ")})`
            : ", none dropped"}
          {result.kept_reviewer_decision ? `, ${result.kept_reviewer_decision} left alone because you had decided` : ""}. Read {suggestedDocs.length}{" "}
          {suggestedDocs.length === 1 ? "document" : "documents"}: {suggestedDocs.map((d) => d.file_name + (d.truncated ? " (only the start was read)" : "")).join(", ")}. Cost ${result.cost_usd.toFixed(2)}.
        </p>
      ) : null}

      {groups.map(([group, defs]) => {
        const adders = ROW_GROUPS.filter((g) => defs.some((d) => d.fieldId.startsWith(g.prefix)));
        return (
          <section key={group} className="s1-mr-card">
            <div className="s1-mr-card__head">
              <h3 className="s1-mr-card__title">{humanise(group)}</h3>
              {adders.map((g) => (
                <button key={g.group} type="button" className="s1-button s1-button--compact" disabled={busy} onClick={() => void act(() => addRow(engagementId, g.group))}>
                  {g.label}
                </button>
              ))}
            </div>
              <ul className="s1-mb-list">
                {defs.map((def) => (
                  <FieldRow key={def.fieldId} engagementId={engagementId} def={def} record={records.get(def.fieldId)!} busy={busy} onAct={(run) => void act(run)} onOpenDocument={onOpenDocument} />
                ))}
              </ul>
          </section>
        );
      })}
    </section>
  );
}
