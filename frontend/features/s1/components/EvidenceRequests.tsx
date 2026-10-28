"use client";

import { ArrowRight, ListChecks, Send } from "lucide-react";
import { Fragment, useMemo, useState } from "react";

import { andThen, NOT_SAVED_TITLE, problemText, settle, type MaybePromise } from "../requests/maybePromise";
import type { AskDraft } from "../requests/requestsStore";
import { whoActed } from "../requests/whoActed";
import type { EngagementConfig } from "../types";
import type { Ask, AskState, RequestType } from "../types/requests";
import { REQUEST_TYPES } from "../types/requests";
import { readablePeriod } from "../utils/formatPeriod";
import type { CoverageRule } from "../types/verification";
import { ActionMenu, type ActionMenuEntry } from "./ActionMenu";
import { AddToRequestsModal, type AddToRequestsTarget } from "./AddToRequestsModal";
import { CoveragePanel, type CoverageState } from "./CoveragePanel";
import { InfoTip } from "./InfoTip";

/**
 * Coverage & requests: what the evidence held lets the verifier check, and what to ask
 * the client for, on one page (the 20 Oct review merged Check coverage and Requests).
 * The holds, load-bearing:
 *   1. Nothing sends from the product yet: Send assembles one message to copy or open in
 *      mail; "mark as sent" is a click; no internal id appears in the message.
 *   2. Nothing resolves on its own: resolve is a click with an optional link; a problem
 *      that comes back is a new ask linked to the old, which stays resolved.
 *   3. Row tints never carry meaning alone: the state label is always present.
 * Asks are raised on Evidence, Extraction review, or here from a check missing its
 * inputs. Every write routes through the store.
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
  coverage,
  valuesToReview = 0,
  onReview,
  onSaveAsk,
  onSend,
  onResolve,
  onWithdraw,
  onEdit,
  onRaiseFollowUp,
  onOpenSource,
  serverRecordsActor = false,
}: {
  engagement: EngagementConfig;
  asks: Ask[];
  /** What can and cannot be checked; the page leads with it. */
  coverage: CoverageState;
  /** Values read but not yet accepted or corrected: coverage counts only reviewed ones. */
  valuesToReview?: number;
  onReview?: () => void;
  /** Raise a request from a check that is missing its inputs. The changes below may answer at
   *  once (the demo) or after the server has: the screen waits, and says so if one fails. */
  onSaveAsk: (draft: AskDraft) => MaybePromise<unknown>;
  onSend: (askIds: string[], lineNumbers: Record<string, number>) => MaybePromise<number>;
  onResolve: (askId: string, resolution: { link?: string | null; note?: string | null }) => MaybePromise<void>;
  onWithdraw: (askId: string, reason: string) => MaybePromise<void>;
  onEdit: (askId: string, whatIsNeeded: string) => MaybePromise<void>;
  onRaiseFollowUp: (fromAsk: Ask) => MaybePromise<unknown>;
  onOpenSource: (ask: Ask) => void;
  /** The server records who raised, sent, resolved or withdrew a request: the window does not ask,
   *  and each row says who took its latest step. */
  serverRecordsActor?: boolean;
}) {
  const [selected, setSelected] = useState<string[]>([]);
  const [stateFilter, setStateFilter] = useState<AskState | null>(null);
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<string[]>([]);
  const [panelOpen, setPanelOpen] = useState(false);
  const [resolveFor, setResolveFor] = useState<string | null>(null);
  const [withdrawFor, setWithdrawFor] = useState<string | null>(null);
  // One row menu open at a time.
  const [menuFor, setMenuFor] = useState<string | null>(null);
  const [requestRule, setRequestRule] = useState<CoverageRule | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  // A change that did not go through, and the requests with a change on its way.
  const [problem, setProblem] = useState<string | null>(null);
  const [pendingIds, setPendingIds] = useState<string[]>([]);
  // The send window keeps its own, because it covers the page.
  const [sendProblem, setSendProblem] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  const flash = (m: string) => {
    setToast(m);
    window.setTimeout(() => setToast(null), 2400);
  };
  const showProblem = (error: unknown) => setProblem(problemText(error));

  /** Runs a change on one request: it is pending until the server answers, and a failure goes to the banner. */
  function changeRequest<T>(id: string, run: () => MaybePromise<T>, onDone: (value: T) => void) {
    const release = () => setPendingIds((cur) => cur.filter((x) => x !== id));
    setProblem(null);
    setPendingIds((cur) => [...cur, id]);
    settle(
      run,
      (value) => {
        release();
        onDone(value);
      },
      (error) => {
        release();
        showProblem(error);
      }
    );
  }

  const counts = useMemo(() => {
    const c = { not_yet_sent: 0, requested: 0, resolved: 0, withdrawn: 0 };
    asks.forEach((a) => (c[a.state] += 1));
    return c;
  }, [asks]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return asks
      .filter((a) => (stateFilter ? a.state === stateFilter : a.state !== "withdrawn"))
      .filter((a) => (q ? a.whatIsNeeded.toLowerCase().includes(q) || a.source.itemLabel.toLowerCase().includes(q) : true))
      .sort((a, b) => STATE_ORDER[a.state] - STATE_ORDER[b.state] || a.raisedAt.localeCompare(b.raisedAt));
  }, [asks, stateFilter, search]);

  const selectableIds = filtered.filter((a) => a.state === "not_yet_sent").map((a) => a.id);
  const selectedSendable = selected.filter((id) => selectableIds.includes(id));
  const allSelectableChecked = selectableIds.length > 0 && selectableIds.every((id) => selected.includes(id));

  function toggle(id: string) {
    setSelected((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]));
  }

  const selectedAsks = selectedSendable
    .map((id) => asks.find((a) => a.id === id))
    .filter((a): a is Ask => Boolean(a));

  const isRequested = (rule: CoverageRule) =>
    asks.some((a) => a.source.origin === "data_point" && a.source.fieldKey === rule.ruleId && a.state !== "withdrawn");

  return (
    <section className="s1-content s1-req s1-cr">
      <header className="s1-ws-header">
        <div className="s1-ws-header__id">
          <h1>Coverage &amp; requests</h1>
          <InfoTip label="Coverage and requests">
            What the evidence held lets you check, and what to ask the client for. A check is ready once its values are
            reviewed; anything missing becomes a request.
          </InfoTip>
        </div>
      </header>

      {problem ? (
        <div className="s1-system-banner" role="alert">
          <strong>{NOT_SAVED_TITLE}</strong>
          <span>{problem}</span>
        </div>
      ) : null}

      {valuesToReview > 0 ? (
        <button className="s1-cr-review" type="button" onClick={onReview}>
          <span className="s1-cr-review__icon" aria-hidden>
            <ListChecks />
          </span>
          <span className="s1-cr-review__text">
            <strong>
              {valuesToReview} {valuesToReview === 1 ? "value" : "values"} waiting for review
            </strong>
            <span>Checks count a value once it is accepted or corrected.</span>
          </span>
          <span className="s1-cr-review__go">
            Review now <ArrowRight aria-hidden />
          </span>
        </button>
      ) : null}

      <CoveragePanel coverage={coverage} isRequested={isRequested} onRequest={setRequestRule} />

      <section className="s1-cr-reqs" aria-labelledby="s1-cr-reqs-title">
        <div className="s1-cr-sectionhead">
          <h2 id="s1-cr-reqs-title">Requests</h2>
          <div className="s1-cr-filters" role="group" aria-label="Show requests">
            {(["not_yet_sent", "requested", "resolved"] as AskState[]).map((state) => (
              <button
                key={state}
                className={`s1-cr-filter s1-cr-filter--${state}${stateFilter === state ? " is-on" : ""}`}
                type="button"
                aria-pressed={stateFilter === state}
                onClick={() => setStateFilter((cur) => (cur === state ? null : state))}
              >
                <span className="s1-cr-filter__n">{counts[state]}</span>
                {STATE_LABEL[state]}
              </button>
            ))}
          </div>
          <input
            className="s1-cr-search"
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search requests"
            aria-label="Search requests"
          />
          <button
            className="s1-button s1-button--pri s1-cr-send"
            type="button"
            disabled={selectedSendable.length === 0}
            onClick={() => {
              setSendProblem(null);
              setPanelOpen(true);
            }}
          >
            <Send aria-hidden />
            Send{selectedSendable.length ? ` (${selectedSendable.length})` : ""}
          </button>
        </div>

        {asks.length === 0 ? (
          <p className="s1-cr-note">No requests yet. Raise one from a missing check above, or from a document on Evidence.</p>
        ) : filtered.length === 0 ? (
          <p className="s1-cr-note">No requests match.</p>
        ) : (
          <div className="s1-table-wrap">
            <table className="s1-table s1-req-table">
              <colgroup>
                <col style={{ width: "3rem" }} />
                <col style={{ width: "30%" }} />
                <col />
                <col style={{ width: "22%" }} />
              </colgroup>
              <thead>
                <tr>
                  <th>
                    <input
                      type="checkbox"
                      checked={allSelectableChecked}
                      disabled={selectableIds.length === 0}
                      aria-label="Select all not yet sent"
                      onChange={() => setSelected(allSelectableChecked ? [] : selectableIds)}
                    />
                  </th>
                  <th>Item</th>
                  <th>What is needed</th>
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
                        <button className="s1-doc-link" type="button" onClick={() => onOpenSource(ask)}>
                          {ask.source.itemLabel}
                        </button>
                        <div className="s1-ws-docmeta">
                          <span>{REQUEST_TYPES.find((t) => t.value === ask.type)?.label}</span>
                          <span>
                            {ask.source.facilityName ?? (ask.source.documentId ? "Facility not yet known" : "Entity-level")}
                            {ask.source.period ? ` · ${readablePeriod(ask.source.period)}` : ""}
                          </span>
                          {ask.linkedFromAskId ? <span>Follow-up</span> : null}
                        </div>
                      </td>
                      <td>
                        {ask.state === "not_yet_sent" ? (
                          <input
                            className="s1-inline-input"
                            defaultValue={ask.whatIsNeeded}
                            onBlur={(e) => {
                              const input = e.currentTarget;
                              if (input.value === ask.whatIsNeeded) return;
                              setProblem(null);
                              settle(
                                () => onEdit(ask.id, input.value),
                                () => {},
                                (error) => {
                                  input.value = ask.whatIsNeeded;
                                  showProblem(error);
                                }
                              );
                            }}
                            aria-label="What is needed"
                          />
                        ) : (
                          <span>{ask.whatIsNeeded}</span>
                        )}
                      </td>
                      <td>
                        <StateCell
                          ask={ask}
                          menuOpen={menuFor === ask.id}
                          onMenuChange={(open) => setMenuFor(open ? ask.id : null)}
                          recordOpen={expanded.includes(ask.id)}
                          serverRecordsActor={serverRecordsActor}
                          onResolveOpen={() => {
                            setResolveFor(ask.id);
                            setWithdrawFor(null);
                          }}
                          onWithdrawOpen={() => {
                            setWithdrawFor(ask.id);
                            setResolveFor(null);
                          }}
                          onFollowUp={() => {
                            setProblem(null);
                            settle(() => onRaiseFollowUp(ask), () => {}, showProblem);
                          }}
                          onExpand={() =>
                            setExpanded((cur) => (cur.includes(ask.id) ? cur.filter((x) => x !== ask.id) : [...cur, ask.id]))
                          }
                        />
                      </td>
                    </tr>

                    {resolveFor === ask.id ? (
                      <tr className="s1-req-subrow">
                        <td colSpan={4}>
                          <ResolveBox
                            pending={pendingIds.includes(ask.id)}
                            onCancel={() => setResolveFor(null)}
                            onResolve={(link, note) =>
                              changeRequest(
                                ask.id,
                                () => onResolve(ask.id, { link, note }),
                                () => {
                                  setResolveFor((cur) => (cur === ask.id ? null : cur));
                                  flash(`Resolved: ${ask.source.itemLabel}`);
                                }
                              )
                            }
                          />
                        </td>
                      </tr>
                    ) : null}

                    {withdrawFor === ask.id ? (
                      <tr className="s1-req-subrow">
                        <td colSpan={4}>
                          <WithdrawBox
                            pending={pendingIds.includes(ask.id)}
                            onCancel={() => setWithdrawFor(null)}
                            onWithdraw={(reason) =>
                              changeRequest(
                                ask.id,
                                () => onWithdraw(ask.id, reason),
                                () => {
                                  setWithdrawFor((cur) => (cur === ask.id ? null : cur));
                                  flash("Withdrawn");
                                }
                              )
                            }
                          />
                        </td>
                      </tr>
                    ) : null}

                    {expanded.includes(ask.id) ? (
                      <tr className="s1-history-row">
                        <td colSpan={4}>
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
      </section>

      {requestRule ? (
        <AddToRequestsModal
          target={coverageTarget(requestRule, engagement)}
          engagement={engagement}
          onCancel={() => setRequestRule(null)}
          serverRecordsActor={serverRecordsActor}
          onAdd={(draft) => {
            setProblem(null);
            return andThen(onSaveAsk(draft), () => {
              setRequestRule(null);
              flash("Added to requests, not sent yet");
            });
          }}
        />
      ) : null}

      {panelOpen ? (
        <SendPanel
          engagement={engagement}
          asks={selectedAsks}
          problem={sendProblem}
          pending={sending}
          onClose={() => {
            setSendProblem(null);
            setPanelOpen(false);
          }}
          onMarkSent={(orderedIds, lineNumbers) => {
            setSendProblem(null);
            setSending(true);
            settle(
              () => onSend(orderedIds, lineNumbers),
              (n) => {
                setSending(false);
                setSelected([]);
                setPanelOpen(false);
                flash(`Sent as request ${n}`);
              },
              (error) => {
                setSending(false);
                setSendProblem(problemText(error));
              }
            );
          }}
          onCopied={() => flash("Message copied")}
        />
      ) : null}

      {toast ? <div className="s1-ws-toast">{toast}</div> : null}
    </section>
  );
}

/** A check that is missing its inputs, as the Add to requests window's target. */
function coverageTarget(rule: CoverageRule, engagement: EngagementConfig): AddToRequestsTarget {
  const points = rule.appliesTo.join(", ");
  const year = engagement.reportingPeriod.start.slice(0, 4);
  return {
    origin: "data_point",
    fieldKey: rule.ruleId,
    itemLabel: points,
    facilityName: null,
    period: year ? `FY ${year}` : null,
    headerLine: `${rule.assertion} · ${rule.reason}`,
    defaultType: "missing_document",
    prefill: `${points}: ${rule.reason}`,
  };
}

/* =============================== state cell =============================== */

/**
 * A request's state: a chip that fits its words, the one next step (Resolve) when there
 * is one, and the rest in the row's menu, all on one line.
 */
function StateCell({
  ask,
  menuOpen,
  onMenuChange,
  recordOpen,
  serverRecordsActor,
  onResolveOpen,
  onWithdrawOpen,
  onFollowUp,
  onExpand,
}: {
  ask: Ask;
  menuOpen: boolean;
  onMenuChange: (open: boolean) => void;
  recordOpen: boolean;
  serverRecordsActor: boolean;
  onResolveOpen: () => void;
  onWithdrawOpen: () => void;
  onFollowUp: () => void;
  onExpand: () => void;
}) {
  const entries: ActionMenuEntry[] = [
    ...(ask.state === "not_yet_sent" || ask.state === "requested" ? [{ label: "Withdraw", action: onWithdrawOpen }] : []),
    ...(ask.state === "resolved" ? [{ label: "Raise follow-up", action: onFollowUp }] : []),
    { label: recordOpen ? "Hide history" : "History", action: onExpand },
  ];
  const acted = serverRecordsActor ? whoActed(ask) : null;
  return (
    <div className="s1-req-state">
      <div className="s1-req-state__row">
        <span className="s1-req-state__label" title={ask.requestNumber ? `Request ${ask.requestNumber}` : undefined}>
          {STATE_LABEL[ask.state]}
          {ask.state === "requested" && ask.requestNumber ? ` · #${ask.requestNumber}` : ""}
        </span>
        <span className="s1-req-state__actions">
          {ask.state === "requested" ? (
            <button className="s1-req-state__go" type="button" onClick={onResolveOpen}>
              Resolve
            </button>
          ) : null}
          <ActionMenu label={`Actions for ${ask.source.itemLabel}`} entries={entries} isOpen={menuOpen} onOpenChange={onMenuChange} />
        </span>
      </div>
      {acted ? (
        <div className="s1-muted s1-req-state__note">
          {acted.label}
          {acted.at ? ` · ${formatActedAt(acted.at)}` : ""}
        </div>
      ) : null}
      {ask.state === "resolved" && ask.resolution?.link ? (
        <div className="s1-muted s1-req-state__note">answered by {ask.resolution.link}</div>
      ) : null}
      {ask.state === "withdrawn" && ask.withdrawReason ? <div className="s1-muted s1-req-state__note">{ask.withdrawReason}</div> : null}
    </div>
  );
}

function ResolveBox({
  pending,
  onCancel,
  onResolve,
}: {
  pending: boolean;
  onCancel: () => void;
  onResolve: (link: string | null, note: string | null) => void;
}) {
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
        <button className="s1-button" type="button" disabled={pending} onClick={() => onResolve(link.trim() || null, note.trim() || null)}>
          Resolve
        </button>
        <button className="s1-button" type="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}

function WithdrawBox({
  pending,
  onCancel,
  onWithdraw,
}: {
  pending: boolean;
  onCancel: () => void;
  onWithdraw: (reason: string) => void;
}) {
  const [reason, setReason] = useState("");
  return (
    <div className="s1-req-box">
      <strong>Withdraw</strong>
      <label className="s1-setup-field">
        <span>Reason (required)</span>
        <input value={reason} onChange={(e) => setReason(e.target.value)} />
      </label>
      <div className="s1-modal__actions">
        <button className="s1-button" type="button" disabled={!reason.trim() || pending} onClick={() => onWithdraw(reason.trim())}>
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
            <span className="s1-num s1-muted">
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

/* ================================ send panel ================================ */

/** The message for the selected requests. Sustentra does not email the client yet: the
 *  verifier copies it or opens it in their mail, then marks it sent. */
function SendPanel({
  engagement,
  asks,
  problem,
  pending,
  onClose,
  onMarkSent,
  onCopied,
}: {
  engagement: EngagementConfig;
  asks: Ask[];
  /** Why the last try at marking these sent did not go through. */
  problem: string | null;
  pending: boolean;
  onClose: () => void;
  onMarkSent: (orderedIds: string[], lineNumbers: Record<string, number>) => void;
  onCopied: () => void;
}) {
  const year = engagement.reportingPeriod.start.slice(0, 4);
  // "2025 emissions", or just "emissions" while the reporting period has no start date.
  const emissions = year ? `${year} emissions` : "emissions";
  const contactFirst = (engagement.clientContact?.name ?? "there").split(" ")[0];
  const verifierName =
    (engagement.engagementTeam ?? []).find((m) => m.login === engagement.signedInLogin)?.name ??
    engagement.signedInName ??
    "the verification team";
  const built = useMemo(() => buildLines(asks), [asks]);
  const [subject, setSubject] = useState(`${engagement.clientName}: ${emissions} verification`);
  const [body, setBody] = useState(() =>
    assembleMessage(
      `Hi ${contactFirst},\n\nThanks for the materials so far. To finish verifying ${engagement.clientName}'s ${emissions}, could you help with the items below?`,
      `Send these whenever you can, and tell me if anything's unclear.\n\nBest,\n${verifierName}`,
      built
    )
  );
  const recipient = engagement.clientContact?.email ?? "";
  const orderedIds = built.flatMap((l) => l.askIds);
  const lineNumbers: Record<string, number> = {};
  built.forEach((line, i) => line.askIds.forEach((id) => (lineNumbers[id] = i + 1)));

  return (
    <div className="s1-modal-scrim" role="presentation" onClick={onClose}>
      <aside className="s1-req-panel" role="dialog" aria-modal="true" aria-label="Send requests" onClick={(e) => e.stopPropagation()}>
        <div className="s1-req-panel__head">
          <strong>
            Send {asks.length} {asks.length === 1 ? "request" : "requests"} to {engagement.clientContact?.name ?? "the client"}
          </strong>
          <span className="s1-muted">Copy the message or open it in your mail, then mark it sent.</span>
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
          <span>Message</span>
          <textarea className="s1-req-message" rows={12} value={body} onChange={(e) => setBody(e.target.value)} />
        </label>
        {problem ? (
          <div className="s1-system-banner" role="alert">
            <strong>{NOT_SAVED_TITLE}</strong>
            <span>{problem}</span>
          </div>
        ) : null}
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
          <button className="s1-button s1-button--pri" type="button" disabled={pending} onClick={() => onMarkSent(orderedIds, lineNumbers)}>
            Mark as sent
          </button>
        </div>
      </aside>
    </div>
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
  const period = ask.source.period && ask.source.period !== "period not yet known" ? ` (${readablePeriod(ask.source.period)})` : "";
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
/** When a request's latest step happened, for the line saying who took it: the year only when it is not this one. */
function formatActedAt(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const thisYear = d.getFullYear() === new Date().getFullYear();
  return d.toLocaleString(undefined, {
    ...(thisYear ? {} : { year: "numeric" }),
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}
function formatDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}
