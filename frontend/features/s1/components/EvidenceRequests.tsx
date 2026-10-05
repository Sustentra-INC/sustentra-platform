"use client";

import { Fragment, useMemo, useState } from "react";

import type { EngagementConfig } from "../types";
import type { Ask, AskState, RequestType } from "../types/requests";
import { REQUEST_TYPES } from "../types/requests";

/**
 * Evidence Requests (screen 4). Every ask raised across the engagement, sent to
 * the client in one email and resolved by hand. Three holds, load-bearing:
 *   1. Nothing sends from the product — copy message / open in mail only, from
 *      the verifier's own address; "mark as sent" is a click; no internal id
 *      appears in the assembled message.
 *   2. Nothing resolves on its own — resolve is a click with an optional link;
 *      a problem that comes back is a new ask linked to the old, which stays
 *      resolved; an ask is in one request only.
 *   3. Row tints never carry meaning alone — the state label is always present.
 * This page never creates a request from nothing: asks are raised on the
 * Workspace and Extraction Review. Every write routes through the store.
 */

const STATE_ORDER: Record<AskState, number> = { not_yet_sent: 0, requested: 1, resolved: 2, withdrawn: 3 };
const STATE_LABEL: Record<AskState, string> = {
  not_yet_sent: "Not yet sent",
  requested: "Requested",
  resolved: "Resolved",
  withdrawn: "Withdrawn",
};
const DOCUMENT_TYPES: RequestType[] = ["missing_document", "replace_document"];

export function EvidenceRequests({
  engagement,
  asks,
  onSend,
  onResolve,
  onWithdraw,
  onEdit,
  onRaiseFollowUp,
  onOpenSource,
  onOpenSetup,
}: {
  engagement: EngagementConfig;
  asks: Ask[];
  onSend: (askIds: string[], lineNumbers: Record<string, number>) => number;
  onResolve: (askId: string, resolution: { link?: string | null; note?: string | null }) => void;
  onWithdraw: (askId: string, reason: string) => void;
  onEdit: (askId: string, whatIsNeeded: string) => void;
  onRaiseFollowUp: (fromAsk: Ask) => void;
  onOpenSource: (ask: Ask) => void;
  onOpenSetup: () => void;
}) {
  const [selected, setSelected] = useState<string[]>([]);
  const [facilityFilter, setFacilityFilter] = useState<string | null>(null);
  const [stateFilter, setStateFilter] = useState<AskState | null>(null);
  const [typeFilter, setTypeFilter] = useState<RequestType | null>(null);
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<string[]>([]);
  const [panelOpen, setPanelOpen] = useState(false);
  const [resolveFor, setResolveFor] = useState<string | null>(null);
  const [withdrawFor, setWithdrawFor] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const flash = (m: string) => {
    setToast(m);
    window.setTimeout(() => setToast(null), 2400);
  };

  const counts = useMemo(() => {
    const c = { not_yet_sent: 0, requested: 0, resolved: 0, withdrawn: 0 };
    asks.forEach((a) => (c[a.state] += 1));
    return c;
  }, [asks]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return asks
      .filter((a) => (facilityFilter ? a.source.facilityName === facilityFilter : true))
      .filter((a) => (stateFilter ? a.state === stateFilter : true))
      .filter((a) => (typeFilter ? a.type === typeFilter : true))
      .filter((a) => (q ? a.whatIsNeeded.toLowerCase().includes(q) || a.source.itemLabel.toLowerCase().includes(q) : true))
      .sort((a, b) => STATE_ORDER[a.state] - STATE_ORDER[b.state] || a.raisedAt.localeCompare(b.raisedAt));
  }, [asks, facilityFilter, stateFilter, typeFilter, search]);

  const selectableIds = filtered.filter((a) => a.state === "not_yet_sent").map((a) => a.id);
  const selectedSendable = selected.filter((id) => selectableIds.includes(id));
  const allSelectableChecked = selectableIds.length > 0 && selectableIds.every((id) => selected.includes(id));

  function toggle(id: string) {
    setSelected((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]));
  }

  const typeCounts = useMemo(() => {
    const c: Partial<Record<RequestType, number>> = {};
    asks.forEach((a) => (c[a.type] = (c[a.type] ?? 0) + 1));
    return c;
  }, [asks]);

  const hasFilter = facilityFilter || stateFilter || typeFilter || search.trim();

  function clearFilters() {
    setFacilityFilter(null);
    setStateFilter(null);
    setTypeFilter(null);
    setSearch("");
  }

  if (asks.length === 0) {
    return (
      <section className="s1-content s1-req">
        <RequestsHeader engagement={engagement} counts={counts} stateFilter={stateFilter} onStateFilter={setStateFilter} onOpenSetup={onOpenSetup} sendable={0} onSend={() => {}} />
        <div className="s1-ws-empty">
          <p>No requests yet. Requests are raised from the Evidence Workspace and Extraction Review.</p>
        </div>
      </section>
    );
  }

  const selectedAsks = selectedSendable
    .map((id) => asks.find((a) => a.id === id))
    .filter((a): a is Ask => Boolean(a));

  return (
    <section className="s1-content s1-req">
      <RequestsHeader
        engagement={engagement}
        counts={counts}
        stateFilter={stateFilter}
        onStateFilter={setStateFilter}
        onOpenSetup={onOpenSetup}
        sendable={selectedSendable.length}
        onSend={() => setPanelOpen(true)}
      />

      <div className="s1-req-body">
        <aside className="s1-req-types" aria-label="Filter by type">
          {REQUEST_TYPES.map((t) => (
            <button
              key={t.value}
              className={`s1-req-typechip${typeFilter === t.value ? " is-on" : ""}`}
              type="button"
              onClick={() => setTypeFilter((cur) => (cur === t.value ? null : t.value))}
            >
              {t.label} <span className="s1-muted">{typeCounts[t.value] ?? 0}</span>
            </button>
          ))}
        </aside>

        <div className="s1-req-main">
          <div className="s1-toolbar">
            <label>
              Facility{" "}
              <select value={facilityFilter ?? ""} onChange={(e) => setFacilityFilter(e.target.value || null)}>
                <option value="">All</option>
                {engagement.facilities.map((f) => (
                  <option key={f.facilityId} value={f.name}>
                    {f.name}
                  </option>
                ))}
                <option value="Entity-level">Entity-level</option>
              </select>
            </label>
            <label>
              State{" "}
              <select value={stateFilter ?? ""} onChange={(e) => setStateFilter((e.target.value || null) as AskState | null)}>
                <option value="">All</option>
                <option value="not_yet_sent">Not yet sent</option>
                <option value="requested">Requested</option>
                <option value="resolved">Resolved</option>
                <option value="withdrawn">Withdrawn</option>
              </select>
            </label>
            <label>
              Search{" "}
              <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="ask text" />
            </label>
            {hasFilter ? (
              <button className="s1-button" type="button" onClick={clearFilters}>
                Clear filter
              </button>
            ) : null}
          </div>

          {filtered.length === 0 ? (
            <div className="s1-ws-empty">
              <p>No requests match this filter.</p>
              <button className="s1-button" type="button" onClick={clearFilters}>
                Clear filter
              </button>
            </div>
          ) : (
            <div className="s1-table-wrap">
              <table className="s1-table s1-req-table">
                <thead>
                  <tr>
                    <th>
                      <input
                        type="checkbox"
                        checked={allSelectableChecked}
                        aria-label="Select all sendable"
                        onChange={() => setSelected(allSelectableChecked ? [] : selectableIds)}
                      />
                    </th>
                    <th>Item</th>
                    <th>Type</th>
                    <th>Facility · period</th>
                    <th>What is needed</th>
                    <th>Raised from</th>
                    <th>Raised by</th>
                    <th>State</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((ask) => (
                    <Fragment key={ask.id}>
                      <tr className={`s1-req-row s1-req-row--${ask.state}`}>
                        <td>
                          <input
                            type="checkbox"
                            checked={selected.includes(ask.id)}
                            disabled={ask.state !== "not_yet_sent"}
                            aria-label={`Select ${ask.source.itemLabel}`}
                            onChange={() => toggle(ask.id)}
                          />
                        </td>
                        <td>
                          <div>{ask.source.itemLabel}</div>
                          {ask.linkedFromAskId ? <div className="s1-muted s1-ws-src">follow-up</div> : null}
                        </td>
                        <td>{REQUEST_TYPES.find((t) => t.value === ask.type)?.label}</td>
                        <td>
                          {ask.source.facilityName ?? "Entity-level"}
                          <div className="s1-muted s1-ws-src">{ask.source.period ?? "Not set"}</div>
                        </td>
                        <td>
                          {ask.state === "not_yet_sent" ? (
                            <input
                              className="s1-inline-input"
                              defaultValue={ask.whatIsNeeded}
                              onBlur={(e) => e.target.value !== ask.whatIsNeeded && onEdit(ask.id, e.target.value)}
                              aria-label="What is needed"
                            />
                          ) : (
                            <span>{ask.whatIsNeeded}</span>
                          )}
                        </td>
                        <td>
                          <button className="s1-linklike" type="button" onClick={() => onOpenSource(ask)}>
                            {ask.source.origin === "review_value" ? "value" : "document"}
                            {ask.source.sourcePage ? ` · p.${ask.source.sourcePage}` : ""}
                          </button>
                        </td>
                        <td>
                          {ask.raisedByName}
                          <div className="s1-mono s1-muted">{formatDate(ask.raisedAt)}</div>
                        </td>
                        <td>
                          <StateCell
                            ask={ask}
                            onResolveOpen={() => {
                              setResolveFor(ask.id);
                              setWithdrawFor(null);
                            }}
                            onWithdrawOpen={() => {
                              setWithdrawFor(ask.id);
                              setResolveFor(null);
                            }}
                            onFollowUp={() => onRaiseFollowUp(ask)}
                            onExpand={() =>
                              setExpanded((cur) => (cur.includes(ask.id) ? cur.filter((x) => x !== ask.id) : [...cur, ask.id]))
                            }
                          />
                        </td>
                      </tr>

                      {resolveFor === ask.id ? (
                        <tr className="s1-req-subrow">
                          <td colSpan={8}>
                            <ResolveBox
                              onCancel={() => setResolveFor(null)}
                              onResolve={(link, note) => {
                                onResolve(ask.id, { link, note });
                                setResolveFor(null);
                                flash(`Resolved — ${ask.source.itemLabel}`);
                              }}
                            />
                          </td>
                        </tr>
                      ) : null}

                      {withdrawFor === ask.id ? (
                        <tr className="s1-req-subrow">
                          <td colSpan={8}>
                            <WithdrawBox
                              onCancel={() => setWithdrawFor(null)}
                              onWithdraw={(reason) => {
                                onWithdraw(ask.id, reason);
                                setWithdrawFor(null);
                                flash("Withdrawn");
                              }}
                            />
                          </td>
                        </tr>
                      ) : null}

                      {expanded.includes(ask.id) ? (
                        <tr className="s1-history-row">
                          <td colSpan={8}>
                            <AskRecord ask={ask} />
                          </td>
                        </tr>
                      ) : null}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <DeferredPanel />
        </div>
      </div>

      {panelOpen ? (
        <RequestByEmailPanel
          engagement={engagement}
          asks={selectedAsks}
          onClose={() => setPanelOpen(false)}
          onMarkSent={(orderedIds, lineNumbers) => {
            const n = onSend(orderedIds, lineNumbers);
            setSelected([]);
            setPanelOpen(false);
            flash(`Marked as sent — request ${n}`);
          }}
          onCopied={() => flash("Message copied")}
        />
      ) : null}

      {toast ? <div className="s1-ws-toast">{toast}</div> : null}
    </section>
  );
}

/* =============================== header =============================== */

function RequestsHeader({
  engagement,
  counts,
  stateFilter,
  onStateFilter,
  onOpenSetup,
  sendable,
  onSend,
}: {
  engagement: EngagementConfig;
  counts: Record<AskState, number>;
  stateFilter: AskState | null;
  onStateFilter: (s: AskState | null) => void;
  onOpenSetup: () => void;
  sendable: number;
  onSend: () => void;
}) {
  return (
    <header className="s1-ws-header">
      <div className="s1-ws-header__id">
        <h1>{engagement.clientName}</h1>
        <button className="s1-linklike" type="button" onClick={onOpenSetup}>
          Setup
        </button>
        <span className="s1-muted">
          Since your last visit: {counts.resolved} resolved · {counts.not_yet_sent} raised
        </span>
      </div>
      <div className="s1-ws-header__counts">
        <button className={`s1-ws-count${stateFilter === "not_yet_sent" ? " is-on" : ""}`} type="button" onClick={() => onStateFilter(stateFilter === "not_yet_sent" ? null : "not_yet_sent")}>
          <span className="s1-ws-count__n">{counts.not_yet_sent}</span> Not yet sent
        </button>
        <button className={`s1-ws-count${stateFilter === "requested" ? " is-on" : ""}`} type="button" onClick={() => onStateFilter(stateFilter === "requested" ? null : "requested")}>
          <span className="s1-ws-count__n">{counts.requested}</span> Requested
        </button>
        <button className={`s1-ws-count${stateFilter === "resolved" ? " is-on" : ""}`} type="button" onClick={() => onStateFilter(stateFilter === "resolved" ? null : "resolved")}>
          <span className="s1-ws-count__n">{counts.resolved}</span> Resolved
        </button>
        <button className="s1-button s1-button--pri s1-req-sendbtn" type="button" disabled={sendable === 0} onClick={onSend}>
          <EnvelopeIcon />
          Request by email{sendable ? ` (${sendable})` : ""}
        </button>
      </div>
    </header>
  );
}

/* =============================== state cell =============================== */

function StateCell({
  ask,
  onResolveOpen,
  onWithdrawOpen,
  onFollowUp,
  onExpand,
}: {
  ask: Ask;
  onResolveOpen: () => void;
  onWithdrawOpen: () => void;
  onFollowUp: () => void;
  onExpand: () => void;
}) {
  return (
    <div className="s1-req-state">
      <span className="s1-req-state__label">
        {STATE_LABEL[ask.state]}
        {ask.state === "requested" && ask.requestNumber ? ` · request ${ask.requestNumber}` : ""}
      </span>
      {ask.state === "resolved" && ask.resolution?.link ? (
        <div className="s1-muted s1-ws-src">answered by {ask.resolution.link}</div>
      ) : null}
      {ask.state === "withdrawn" && ask.withdrawReason ? (
        <div className="s1-muted s1-ws-src">{ask.withdrawReason}</div>
      ) : null}
      <div className="s1-req-state__actions">
        {ask.state === "not_yet_sent" ? (
          <button className="s1-linklike" type="button" onClick={onWithdrawOpen}>
            Withdraw
          </button>
        ) : null}
        {ask.state === "requested" ? (
          <>
            <button className="s1-linklike" type="button" onClick={onResolveOpen}>
              Resolve
            </button>
            <button className="s1-linklike" type="button" onClick={onWithdrawOpen}>
              Withdraw
            </button>
          </>
        ) : null}
        {ask.state === "resolved" ? (
          <button className="s1-linklike" type="button" onClick={onFollowUp}>
            Raise follow-up
          </button>
        ) : null}
        <button className="s1-linklike" type="button" onClick={onExpand}>
          Record
        </button>
      </div>
    </div>
  );
}

function ResolveBox({ onCancel, onResolve }: { onCancel: () => void; onResolve: (link: string | null, note: string | null) => void }) {
  const [link, setLink] = useState("");
  const [note, setNote] = useState("");
  return (
    <div className="s1-req-box">
      <strong>Resolve</strong>
      <label className="s1-setup-field">
        <span>Link to the document or value that answered it (optional)</span>
        <input value={link} onChange={(e) => setLink(e.target.value)} placeholder="e.g. the re-sent file, or the client's reply" />
      </label>
      <label className="s1-setup-field">
        <span>Note (optional)</span>
        <input value={note} onChange={(e) => setNote(e.target.value)} />
      </label>
      <div className="s1-modal__actions">
        <button className="s1-button" type="button" onClick={() => onResolve(link.trim() || null, note.trim() || null)}>
          Resolve
        </button>
        <button className="s1-button" type="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}

function WithdrawBox({ onCancel, onWithdraw }: { onCancel: () => void; onWithdraw: (reason: string) => void }) {
  const [reason, setReason] = useState("");
  return (
    <div className="s1-req-box">
      <strong>Withdraw</strong>
      <label className="s1-setup-field">
        <span>Reason (required)</span>
        <input value={reason} onChange={(e) => setReason(e.target.value)} />
      </label>
      <div className="s1-modal__actions">
        <button className="s1-button" type="button" disabled={!reason.trim()} onClick={() => onWithdraw(reason.trim())}>
          Withdraw
        </button>
        <button className="s1-button" type="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}

function AskRecord({ ask }: { ask: Ask }) {
  return (
    <div className="s1-ws-record">
      <div className="s1-ws-record__log">
        <strong>Record</strong>
        {ask.history.map((h, i) => (
          <div key={i}>
            <span className="s1-mono s1-muted">
              {h.actorName} · {formatDate(h.at)}
            </span>{" "}
            {h.kind}
            {h.detail ? ` · ${h.detail}` : ""}
          </div>
        ))}
        {ask.linkedFromAskId ? <div className="s1-muted">follow-up to a resolved ask ({ask.linkedFromAskId})</div> : null}
      </div>
    </div>
  );
}

/* ========================= request by email panel ========================= */

function RequestByEmailPanel({
  engagement,
  asks,
  onClose,
  onMarkSent,
  onCopied,
}: {
  engagement: EngagementConfig;
  asks: Ask[];
  onClose: () => void;
  onMarkSent: (orderedIds: string[], lineNumbers: Record<string, number>) => void;
  onCopied: () => void;
}) {
  const year = engagement.reportingPeriod.start.slice(0, 4);
  const contactFirst = (engagement.clientContact?.name ?? "there").split(" ")[0];
  const verifierName = (engagement.engagementTeam ?? []).find((m) => m.login === engagement.signedInLogin)?.name ?? "the verification team";

  const [opening, setOpening] = useState(
    `Hi ${contactFirst},\n\nThanks for the materials so far. To finish verifying ${engagement.clientName}'s ${year} emissions, could you help with the items below?`
  );
  const [closing, setClosing] = useState(`Send these whenever you can, and tell me if anything's unclear.\n\nBest,\n${verifierName}`);
  const [subject, setSubject] = useState(`${engagement.clientName} — ${year} emissions verification`);

  const built = useMemo(() => buildLines(asks), [asks]);
  const body = useMemo(() => assembleMessage(opening, closing, built), [opening, closing, built]);

  const recipient = engagement.clientContact?.email ?? "";
  const orderedIds = built.flatMap((l) => l.askIds);
  const lineNumbers: Record<string, number> = {};
  built.forEach((line, i) => line.askIds.forEach((id) => (lineNumbers[id] = i + 1)));

  return (
    <div className="s1-modal-scrim" role="presentation" onClick={onClose}>
      <aside className="s1-req-panel" role="dialog" aria-modal="true" aria-label="Request by email" onClick={(e) => e.stopPropagation()}>
        <div className="s1-req-panel__head">
          <strong>Request by email</strong>
          <span className="s1-muted">Nothing is sent from here. Copy the message or open it in your mail, from your address ({engagement.verifierEmail ?? "set it in Setup"}).</span>
        </div>

        <label className="s1-setup-field">
          <span>To</span>
          <input value={recipient} readOnly />
        </label>
        <label className="s1-setup-field">
          <span>Subject</span>
          <input value={subject} onChange={(e) => setSubject(e.target.value)} />
        </label>
        <label className="s1-setup-field">
          <span>Opening</span>
          <textarea rows={3} value={opening} onChange={(e) => setOpening(e.target.value)} />
        </label>
        <label className="s1-setup-field">
          <span>Closing</span>
          <textarea rows={3} value={closing} onChange={(e) => setClosing(e.target.value)} />
        </label>

        <div className="s1-req-preview">
          <div className="s1-muted">As the client will read it</div>
          <pre className="s1-req-message">{body}</pre>
        </div>

        <div className="s1-modal__actions">
          <button
            className="s1-button"
            type="button"
            onClick={() => {
              void navigator.clipboard?.writeText(body).then(onCopied, onCopied);
            }}
          >
            Copy message
          </button>
          <a
            className="s1-button"
            href={`mailto:${encodeURIComponent(recipient)}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`}
          >
            Open in mail
          </a>
          <button className="s1-button s1-button--pri" type="button" onClick={() => onMarkSent(orderedIds, lineNumbers)}>
            Mark as sent
          </button>
          <button className="s1-button" type="button" onClick={onClose}>
            Cancel
          </button>
        </div>
      </aside>
    </div>
  );
}

function DeferredPanel() {
  const items = [
    "Due dates and overdue",
    "Chase",
    "The “new document arrived” hint",
    "Client login and shared upload",
    "Real email sending from the product",
    "The needed-items grid (waits on the in-scope field list)",
  ];
  return (
    <section className="s1-panel s1-req-deferred">
      <strong>Deferred (per the spec) · not built</strong>
      <ul>
        {items.map((i) => (
          <li key={i} className="s1-muted">
            {i}
          </li>
        ))}
      </ul>
    </section>
  );
}

/* ============================ message assembly ============================ */

interface AssembledLine {
  askIds: string[];
  facility: string;
  isDocument: boolean;
  text: string;
}

/** Group by facility, collapse asks one document would satisfy, documents first. */
function buildLines(asks: Ask[]): AssembledLine[] {
  const byFacility = new Map<string, Ask[]>();
  for (const a of asks) {
    const key = a.source.facilityName ?? "Entity-level";
    byFacility.set(key, [...(byFacility.get(key) ?? []), a]);
  }
  const lines: AssembledLine[] = [];
  for (const [facility, group] of byFacility) {
    // collapse asks that share a document into one line
    const byDoc = new Map<string, Ask[]>();
    const standalone: Ask[] = [];
    for (const a of group) {
      if (a.source.documentId) byDoc.set(a.source.documentId, [...(byDoc.get(a.source.documentId) ?? []), a]);
      else standalone.push(a);
    }
    const facilityLines: AssembledLine[] = [];
    for (const [, groupAsks] of byDoc) {
      facilityLines.push(lineFromAsks(groupAsks, facility));
    }
    for (const a of standalone) facilityLines.push(lineFromAsks([a], facility));
    // documents before questions
    facilityLines.sort((a, b) => Number(b.isDocument) - Number(a.isDocument));
    lines.push(...facilityLines);
  }
  return lines;
}

function lineFromAsks(asks: Ask[], facility: string): AssembledLine {
  const isDocument = asks.some((a) => DOCUMENT_TYPES.includes(a.type));
  const reasons = asks.map(reasonSentence).filter(Boolean);
  const text = dedupe(reasons).join(" ");
  return { askIds: asks.map((a) => a.id), facility, isDocument, text };
}

/** Plain-language sentence for a client — reason text, or a type fallback. No ids. */
function reasonSentence(ask: Ask): string {
  const idx = ask.whatIsNeeded.indexOf(": ");
  const tail = idx >= 0 ? ask.whatIsNeeded.slice(idx + 2).trim() : ask.whatIsNeeded.trim();
  const reason = tail || fallbackByType(ask);
  const period = ask.source.period && ask.source.period !== "period not yet known" ? ` (${ask.source.period})` : "";
  return capitalize(reason.endsWith(".") ? reason.slice(0, -1) : reason) + period + ".";
}

function fallbackByType(ask: Ask): string {
  switch (ask.type) {
    case "missing_document":
      return `please send the ${ask.source.itemLabel}`;
    case "replace_document":
      return `please re-send the ${ask.source.itemLabel}`;
    case "missing_data":
      return `we could not find ${ask.source.itemLabel} — please confirm it`;
    case "clarify":
      return `please clarify ${ask.source.itemLabel}`;
    case "confirm_or_restate":
      return `please confirm ${ask.source.itemLabel}`;
    default:
      return `please review ${ask.source.itemLabel}`;
  }
}

function assembleMessage(opening: string, closing: string, lines: AssembledLine[]): string {
  const parts: string[] = [opening.trim(), ""];
  let n = 0;
  let currentFacility = "";
  for (const line of lines) {
    if (line.facility !== currentFacility) {
      if (currentFacility) parts.push("");
      parts.push(`For ${line.facility}:`);
      currentFacility = line.facility;
    }
    n += 1;
    parts.push(`${n}. ${line.text}`);
  }
  parts.push("", closing.trim());
  return parts.join("\n");
}

function dedupe(xs: string[]): string[] {
  return Array.from(new Set(xs));
}
function capitalize(s: string): string {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}
function formatDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function EnvelopeIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="m3.5 7 8.5 6 8.5-6" />
    </svg>
  );
}
