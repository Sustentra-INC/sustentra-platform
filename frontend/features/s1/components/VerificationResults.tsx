"use client";

import { Fragment, useState } from "react";

import type {
  CheckOutcome,
  ExaminationState,
  NextActionWith,
  ResultLayer,
  VerificationRow,
} from "../types/verification";
import type { VerificationStore } from "../verification/verificationStore";

/**
 * Verification results (screen 6). Two tabs. The workpaper: every data point,
 * what was reported, what the system recomputed, and what the verifier decided.
 *
 * Gaps carried visibly (from the backend study):
 *  - Only the Scope 1 stationary-combustion fuel path is recomputed; other rows
 *    read "not recomputed" with a reason, never blank.
 *  - Examination state and next action are the verifier's — set here, stored in
 *    the frontend verification store.
 *  - Finding prose, magnitude and "with the client since" are frontend-authored
 *    or request-linked, flagged in the Findings tab, not left as empty columns.
 * Scope 2 is always two rows. Nothing says "complete".
 */

const LAYERS: { layer: ResultLayer; label: string }[] = [
  { layer: "general", label: "General" },
  { layer: "scope1", label: "Scope 1" },
  { layer: "scope2", label: "Scope 2" },
];

const OUTCOME_LABEL: Record<CheckOutcome, string> = {
  held: "Held",
  exception: "Exception",
  could_not_check: "Could not check",
  out_of_scope: "Out of scope",
};
const OUTCOME_ROLE: Record<CheckOutcome, string> = {
  held: "resolved",
  exception: "blocking",
  could_not_check: "unverifiable",
  out_of_scope: "na",
};
const EXAM_OPTIONS: { value: ExaminationState; label: string }[] = [
  { value: "not_examined", label: "Not examined" },
  { value: "examined_no_exceptions", label: "Examined, no exceptions" },
  { value: "finding_raised", label: "Finding raised" },
];
const NEXT_OPTIONS: { value: NextActionWith; label: string }[] = [
  { value: "none", label: "None" },
  { value: "me", label: "With me" },
  { value: "client", label: "With client" },
];

export function VerificationResults({ rows, store }: { rows: VerificationRow[]; store: VerificationStore }) {
  const [tab, setTab] = useState<"results" | "findings">("results");
  const [findingFor, setFindingFor] = useState<VerificationRow | null>(null);

  return (
    <section className="s1-content s1-vr">
      <header className="s1-ws-header">
        <div className="s1-ws-header__id">
          <h1>Verification results</h1>
          <span className="s1-muted">Every data point: reported, recomputed, and your position on each.</span>
        </div>
        <div className="s1-ws-header__counts">
          <button className={`s1-ws-count${tab === "results" ? " is-on" : ""}`} type="button" onClick={() => setTab("results")}>
            Results
          </button>
          <button className={`s1-ws-count${tab === "findings" ? " is-on" : ""}`} type="button" onClick={() => setTab("findings")}>
            <span className="s1-ws-count__n">{store.findings.length}</span> Findings
          </button>
        </div>
      </header>

      <div className="s1-cov-banner" role="note">
        <strong>Recompute is partial and rule evaluation is not implemented.</strong> Only Scope 1 stationary combustion
        is recomputed today; other rows say why they were not. Check outcomes reflect that — most read &ldquo;could not
        check&rdquo;. Examination state and next action are yours to set.
      </div>

      {tab === "results" ? (
        <ResultsTab rows={rows} store={store} onRegister={setFindingFor} />
      ) : (
        <FindingsTab store={store} />
      )}

      {findingFor ? (
        <RegisterFindingModal
          row={findingFor}
          onCancel={() => setFindingFor(null)}
          onRegister={(sentence, cause, magnitude) => {
            store.registerFinding({
              dataPointId: findingFor.dataPointId,
              dataPointLabel: rowLabel(findingFor),
              sentence,
              cause,
              magnitude,
              status: "Open",
              withClientSince: null,
            });
            setFindingFor(null);
          }}
        />
      ) : null}
    </section>
  );
}

function ResultsTab({
  rows,
  store,
  onRegister,
}: {
  rows: VerificationRow[];
  store: VerificationStore;
  onRegister: (row: VerificationRow) => void;
}) {
  return (
    <div className="s1-table-wrap">
      <table className="s1-table s1-vr-table">
        <thead>
          <tr>
            <th>Data point</th>
            <th>Reported</th>
            <th>Recomputed / expected</th>
            <th>Delta</th>
            <th>Check outcome</th>
            <th>Examination state</th>
            <th>Next action</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {LAYERS.map(({ layer, label }) => {
            const layerRows = rows.filter((r) => r.layer === layer);
            if (!layerRows.length) return null;
            return (
              <Fragment key={layer}>
                <tr className="s1-ws-group">
                  <td colSpan={8}>{label}</td>
                </tr>
                {layerRows.map((row) => {
                  const exam = store.examinations[row.dataPointId];
                  return (
                    <tr key={row.dataPointId}>
                      <td>
                        {rowLabel(row)}
                        {row.scopeBasis ? <div className="s1-muted s1-ws-src">{row.scopeBasis}-based</div> : null}
                      </td>
                      <td className="s1-mono">
                        {row.reportedValue} {row.unit}
                      </td>
                      <td>
                        {row.recomputed !== null ? (
                          <span className="s1-mono">
                            {row.recomputed} {row.unit}
                          </span>
                        ) : (
                          <span className="s1-muted">not recomputed — {row.recomputeReason}</span>
                        )}
                      </td>
                      <td className="s1-mono">{row.delta ?? <span className="s1-muted">—</span>}</td>
                      <td>
                        <span className={`s1-state s1-state--${OUTCOME_ROLE[row.checkOutcome]}`}>
                          {OUTCOME_LABEL[row.checkOutcome]}
                        </span>
                        <div className="s1-muted s1-ws-src">{row.checkReason}</div>
                      </td>
                      <td>
                        <select
                          value={exam?.examinationState ?? "not_examined"}
                          onChange={(e) => store.setExaminationState(row.dataPointId, e.target.value as ExaminationState)}
                        >
                          {EXAM_OPTIONS.map((o) => (
                            <option key={o.value} value={o.value}>
                              {o.label}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>
                        <select
                          value={exam?.nextActionWith ?? "none"}
                          onChange={(e) => store.setNextAction(row.dataPointId, e.target.value as NextActionWith)}
                        >
                          {NEXT_OPTIONS.map((o) => (
                            <option key={o.value} value={o.value}>
                              {o.label}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>
                        <button className="s1-linklike" type="button" onClick={() => onRegister(row)}>
                          Register finding
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function FindingsTab({ store }: { store: VerificationStore }) {
  if (store.findings.length === 0) {
    return (
      <div className="s1-ws-empty">
        <p>No findings yet. Register one from the Results tab.</p>
      </div>
    );
  }
  // Grouped by cause; within a cause, insertion order (magnitude is free text,
  // so a strict magnitude-descending sort is deferred — see note).
  const byCause = new Map<string, typeof store.findings>();
  store.findings.forEach((f) => byCause.set(f.cause, [...(byCause.get(f.cause) ?? []), f]));

  return (
    <>
      <p className="s1-muted s1-vr-note">
        Finding, magnitude and &ldquo;with the client since&rdquo; are the verifier&rsquo;s words or request-linked — not
        machine output. Magnitude-descending order is deferred (magnitude is free text for now).
      </p>
      <div className="s1-table-wrap">
        <table className="s1-table">
          <thead>
            <tr>
              <th>Data point</th>
              <th>Finding</th>
              <th>Cause</th>
              <th>Magnitude</th>
              <th>Status</th>
              <th>With the client since</th>
            </tr>
          </thead>
          <tbody>
            {Array.from(byCause.entries()).map(([cause, findings]) => (
              <Fragment key={cause}>
                <tr className="s1-ws-group">
                  <td colSpan={6}>{cause}</td>
                </tr>
                {findings.map((f) => (
                  <tr key={f.id}>
                    <td>{f.dataPointLabel}</td>
                    <td>{f.sentence}</td>
                    <td>{f.cause}</td>
                    <td className="s1-mono">{f.magnitude}</td>
                    <td>
                      <span className="s1-state s1-state--open">{f.status}</span>
                    </td>
                    <td className="s1-muted">{f.withClientSince ?? "— (request-linked)"}</td>
                  </tr>
                ))}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function RegisterFindingModal({
  row,
  onCancel,
  onRegister,
}: {
  row: VerificationRow;
  onCancel: () => void;
  onRegister: (sentence: string, cause: string, magnitude: string) => void;
}) {
  const [sentence, setSentence] = useState("");
  const [cause, setCause] = useState("");
  const [magnitude, setMagnitude] = useState(row.delta ?? "");
  return (
    <div className="s1-modal-scrim" role="presentation" onClick={onCancel}>
      <div className="s1-modal" role="dialog" aria-modal="true" aria-label="Register finding" onClick={(e) => e.stopPropagation()}>
        <div className="s1-modal__head">
          <strong>Register finding</strong>
          <div className="s1-muted">{rowLabel(row)}</div>
        </div>
        <label className="s1-modal__field">
          <span>Finding — in one sentence</span>
          <textarea rows={2} value={sentence} onChange={(e) => setSentence(e.target.value)} placeholder="What is wrong, in plain words" />
        </label>
        <label className="s1-modal__field">
          <span>Cause</span>
          <input value={cause} onChange={(e) => setCause(e.target.value)} placeholder="e.g. Emission factor mismatch" />
        </label>
        <label className="s1-modal__field">
          <span>Magnitude</span>
          <input value={magnitude} onChange={(e) => setMagnitude(e.target.value)} placeholder="e.g. +10.7% / 165 tCO₂e" />
        </label>
        <div className="s1-modal__actions">
          <button
            className="s1-button"
            type="button"
            disabled={!sentence.trim() || !cause.trim()}
            onClick={() => onRegister(sentence.trim(), cause.trim(), magnitude.trim() || "—")}
          >
            Register finding
          </button>
          <button className="s1-button" type="button" onClick={onCancel}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

function rowLabel(row: VerificationRow): string {
  return row.label;
}
