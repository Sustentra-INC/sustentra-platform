"use client";

import { InfoTip } from "./InfoTip";
import { Fragment, useState, type ReactNode } from "react";

import type {
  CheckOutcome,
  ExaminationState,
  MaterialityFigures,
  NextActionWith,
  ResultLayer,
  VerificationRow,
  WorkingSpec,
} from "../types/verification";
import type { TeamMember } from "../types/engagement";
import type { ResultLine } from "../types/verificationResults";
import type { VerificationStore } from "../verification/verificationStore";
import { VerificationWorkspace } from "./VerificationWorkspace";

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

export function VerificationResults({
  rows,
  store,
  materiality,
  inputs,
  lines,
  team = [],
  signedInLogin,
}: {
  rows: VerificationRow[];
  store: VerificationStore;
  /** Backend figures; without them the tiles are summed from the rows at 5%. */
  materiality?: MaterialityFigures;
  /** Shown above the results table, e.g. the recalculation inputs. */
  inputs?: ReactNode;
  /** The client's inventory lines, by facility: Results shows reported vs recomputed in three panes. */
  lines?: ResultLine[];
  team?: TeamMember[];
  signedInLogin?: string;
}) {
  const [tab, setTab] = useState<"results" | "findings">("results");
  const [findingFor, setFindingFor] = useState<VerificationRow | null>(null);

  return (
    <section className="s1-content s1-vr">
      <header className="s1-ws-header">
        <div className="s1-ws-header__id">
          <h1>Verification results</h1>
          <InfoTip label="Verification results">
            {lines
              ? "What the client reported against what the evidence recomputes, down to the input that explains each difference."
              : "Every data point: reported, recomputed, and your position on each."}
          </InfoTip>
        </div>
        {/* The three-pane page has no Results / Findings switch for now (product, 2026-10-15). */}
        {lines ? null : (
          <div className="s1-ws-header__counts">
            <button className={`s1-ws-count${tab === "results" ? " is-on" : ""}`} type="button" onClick={() => setTab("results")}>
              Results
            </button>
            <button className={`s1-ws-count${tab === "findings" ? " is-on" : ""}`} type="button" onClick={() => setTab("findings")}>
              <span className="s1-ws-count__n">{store.findings.length}</span> Findings
            </button>
          </div>
        )}
      </header>

      {tab === "results" ? (
        <>
          {inputs}
          {lines ? (
            <VerificationWorkspace lines={lines} store={store} team={team} signedInLogin={signedInLogin} />
          ) : (
            <ResultsTab
              rows={rows}
              store={store}
              materiality={materiality ?? materialityFromRows(rows)}
              onRegister={setFindingFor}
            />
          )}
        </>
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
  materiality,
  onRegister,
}: {
  rows: VerificationRow[];
  store: VerificationStore;
  materiality: MaterialityFigures;
  onRegister: (row: VerificationRow) => void;
}) {
  const [open, setOpen] = useState<Set<string>>(new Set());
  const toggle = (id: string) =>
    setOpen((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  return (
    <>
      <MaterialitySummary figures={materiality} />
      <div className="s1-table-wrap">
        <table className="s1-table s1-vr-table">
          <colgroup>
            <col style={{ width: "15%" }} /* Data point */ />
            <col style={{ width: "9%" }} /* Reported */ />
            <col style={{ width: "14%" }} /* Recomputed / expected */ />
            <col style={{ width: "7%" }} /* Delta */ />
            <col style={{ width: "15%" }} /* Check outcome */ />
            <col style={{ width: "17%" }} /* Examination state */ />
            <col style={{ width: "13%" }} /* Next action */ />
            <col style={{ width: "10%" }} /* actions */ />
          </colgroup>
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
                    const isOpen = open.has(row.dataPointId);
                    return (
                      <Fragment key={row.dataPointId}>
                        <tr>
                          <td>
                            {rowLabel(row)}
                            {row.scopeBasis ? <div className="s1-muted s1-ws-src">{row.scopeBasis}-based</div> : null}
                          </td>
                          <td className="s1-mono">
                            {row.reportedValue ? (
                              `${row.reportedValue} ${row.unit}`
                            ) : (
                              <span className="s1-muted">Not entered</span>
                            )}
                          </td>
                          <td>
                            {row.recomputed !== null ? (
                              <span className="s1-mono">
                                {row.recomputed} {row.unit}
                              </span>
                            ) : (
                              <span className="s1-muted">not recomputed · {row.recomputeReason}</span>
                            )}
                          </td>
                          <td className="s1-mono">{row.delta ?? <span className="s1-muted">None</span>}</td>
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
                            <div className="s1-vr-rowactions">
                              {workingOf(row) ? (
                                <button
                                  className={`s1-vr-working-btn${isOpen ? " is-on" : ""}`}
                                  type="button"
                                  aria-expanded={isOpen}
                                  onClick={() => toggle(row.dataPointId)}
                                >
                                  {isOpen ? "Hide working" : "Show working"}
                                </button>
                              ) : null}
                              <button className="s1-linklike" type="button" onClick={() => onRegister(row)}>
                                Register finding
                              </button>
                            </div>
                          </td>
                        </tr>
                        {isOpen && workingOf(row) ? (
                          <tr className="s1-vr-workingrow">
                            <td colSpan={8}>
                              <WorkingPanel spec={workingOf(row) as WorkingSpec} />
                            </td>
                          </tr>
                        ) : null}
                      </Fragment>
                    );
                  })}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}

/* ===================== materiality & the audit trail ===================== */

function parseNum(s: string | null): number {
  if (!s) return 0;
  const n = Number(s.replace(/[^0-9.-]/g, ""));
  return Number.isFinite(n) ? n : 0;
}

function materialityFromRows(rows: VerificationRow[]): MaterialityFigures {
  // Location-based total = Scope 1 + Scope 2 (location). Identified misstatement
  // = sum of |recomputed − reported| for the rows that were recomputed.
  const locationRows = rows.filter((r) => r.layer === "scope1" || (r.layer === "scope2" && r.scopeBasis === "location"));
  const total = locationRows.reduce((s, r) => s + parseNum(r.reportedValue), 0);
  const misstatement = rows
    .filter((r) => r.recomputed !== null)
    .reduce((s, r) => s + Math.abs(parseNum(r.recomputed) - parseNum(r.reportedValue)), 0);
  const uncorrected = rows
    .filter((r) => r.recomputed !== null && r.checkOutcome === "exception")
    .reduce((s, r) => s + Math.abs(parseNum(r.recomputed) - parseNum(r.reportedValue)), 0);
  const couldNotCheck = rows.filter((r) => r.checkOutcome === "could_not_check").length;
  return {
    total,
    totalBasis: "Scope 1 + Scope 2",
    tolerancePct: 5,
    misstatement,
    uncorrected,
    note:
      `Aggregate misstatement is summed only over the ${rows.filter((r) => r.recomputed !== null).length} recomputed ` +
      `sources. ${couldNotCheck} data points could not be checked yet (no recompute path or missing documentation), so ` +
      "the register is not complete — the conclusion stays provisional until they are resolved.",
  };
}

function MaterialitySummary({ figures }: { figures: MaterialityFigures }) {
  const { total, misstatement, uncorrected, tolerancePct } = figures;
  const threshold = total * (tolerancePct / 100);
  const fmt = (n: number) => n.toLocaleString(undefined, { maximumFractionDigits: n < 100 ? 2 : 0 });
  const pct = (n: number) => (total ? `${((n / total) * 100).toFixed(1)}%` : "—");
  const over = uncorrected > threshold;

  return (
    <div className="s1-mat">
      <div className="s1-mat__tiles">
        <div className="s1-mat__tile">
          <div className="s1-mat__label">Total emissions (location-based)</div>
          <div className="s1-mat__value">{fmt(total)} <span className="s1-mat__unit">tCO₂e</span></div>
          <div className="s1-mat__sub">{figures.totalBasis}</div>
        </div>
        <div className="s1-mat__tile">
          <div className="s1-mat__label">Materiality threshold</div>
          <div className="s1-mat__value">{fmt(threshold)} <span className="s1-mat__unit">tCO₂e</span></div>
          <div className="s1-mat__sub">{tolerancePct}% of total</div>
        </div>
        <div className="s1-mat__tile">
          <div className="s1-mat__label">Identified misstatement</div>
          <div className="s1-mat__value">{fmt(misstatement)} <span className="s1-mat__unit">tCO₂e</span></div>
          <div className="s1-mat__sub">{pct(misstatement)} of total · across recomputed sources</div>
        </div>
        <div className={`s1-mat__tile${over ? " s1-mat__tile--over" : ""}`}>
          <div className="s1-mat__label">Uncorrected (exceptions)</div>
          <div className="s1-mat__value">{fmt(uncorrected)} <span className="s1-mat__unit">tCO₂e</span></div>
          <div className="s1-mat__sub">{over ? "above" : "below"} threshold · {pct(uncorrected)}</div>
        </div>
      </div>
      <p className="s1-mat__note">{figures.note}</p>
    </div>
  );
}

/** The audit trail per data point: formula, extracted inputs with source,
 *  emission factor with reference, result, and all references. Illustrative
 *  factors/figures pending product (Claire) confirming the real reconciliation. */
const WORKING: Record<string, WorkingSpec> = {
  "DP-BOUNDARY": {
    formula: "No quantitative recompute — narrative disclosure, verified against source.",
    inputs: [{ label: "Reported approach", value: "Operational control", source: "Engagement letter · management representation" }],
    references: ["GHG Protocol Corporate Standard, Ch. 3 — Organizational boundaries", "CA SB 253 §38532"],
  },
  "DP-GAS-TUALATIN": {
    formula: "Emissions (tCO₂e) = Fuel consumed (therms) × Emission factor (kgCO₂e/therm) ÷ 1,000",
    inputs: [{ label: "Fuel consumed", value: "339,245 therms", source: "tualatin_gas_2025.xlsx · sheet ‘NG’" }],
    factor: { value: "5.30 kgCO₂e/therm", source: "EPA Emission Factors Hub (Mar 2024) · natural gas · stationary" },
    result: "Recomputed 1,798 tCO₂e vs reported 1,812 → +0.8% (within 5% tolerance).",
    references: ["GHG Protocol Corporate Standard, Ch. 6", "EPA Emission Factors Hub, Mar 2024", "CA SB 253"],
  },
  "DP-GAS-KENT": {
    formula: "Emissions (tCO₂e) = Fuel consumed (therms) × Emission factor (kgCO₂e/therm) ÷ 1,000",
    inputs: [{ label: "Fuel consumed", value: "321,698 therms", source: "kent_gas_sep_2025.pdf · p.2" }],
    factor: { value: "5.30 kgCO₂e/therm", source: "EPA Emission Factors Hub (Mar 2024) · natural gas · stationary" },
    result: "Recomputed 1,705 tCO₂e vs reported 1,540 → +10.7% (exceeds 5% tolerance).",
    note: "Exception: the client applied a lower factor than the current EPA value. Understatement of +165 tCO₂e.",
    references: ["GHG Protocol Corporate Standard, Ch. 6", "EPA Emission Factors Hub, Mar 2024", "CA SB 253"],
  },
  "DP-DIESEL-FLEET": {
    formula: "Emissions (tCO₂e) = Diesel (L) × Emission factor (kgCO₂e/L) ÷ 1,000",
    inputs: [{ label: "Diesel purchased", value: "97,100 L (claimed)", source: "fleet fuel log · not yet extracted" }],
    factor: { value: "2.68 kgCO₂e/L", source: "GHG Protocol · mobile combustion · diesel" },
    references: ["GHG Protocol Corporate Standard, Ch. 6 — mobile combustion"],
    note: "Recompute path for mobile combustion not built yet — formula and factor shown for reference.",
  },
  "DP-REFRIGERANT": {
    formula: "Emissions (tCO₂e) = Refrigerant recharged (kg) × GWP ÷ 1,000",
    inputs: [{ label: "R-404A recharged", value: "12.2 kg", source: "refrigerant service log · Kent Cannery" }],
    factor: { value: "GWP 3,922 (R-404A)", source: "IPCC AR5 · 100-year GWP" },
    references: ["GHG Protocol Corporate Standard, Ch. 6 — fugitive emissions", "IPCC AR5"],
    note: "Recompute path for fugitive emissions not built yet.",
  },
  "DP-ELEC-LOC": {
    formula: "Emissions (tCO₂e) = Electricity (kWh) × Emission factor (kgCO₂e/kWh) ÷ 1,000",
    inputs: [
      { label: "Electricity — Kent, Feb", value: "182,400 kWh", source: "kent_electricity_feb_2025.pdf · p.1" },
      { label: "Electricity — all sites, year", value: "44,304,900 kWh", source: "12 electricity bills · 3 facilities" },
    ],
    factor: { value: "0.223 kgCO₂e/kWh", source: "eGRID 2024 · WECC/NWPP subregion · location-based" },
    result: "Reported 9,880 tCO₂e. Auto-reconciliation for Scope 2 not run yet — extracted data and factor shown so the figure can be cross-checked to source.",
    references: ["GHG Protocol Scope 2 Guidance — location-based", "eGRID 2024 subregion factors", "CA SB 253"],
  },
  "DP-ELEC-MKT": {
    formula: "Emissions (tCO₂e) = Electricity (kWh) × Supplier / residual-mix EF (kgCO₂e/kWh) ÷ 1,000",
    inputs: [{ label: "Electricity — all sites, year", value: "44,304,900 kWh", source: "12 electricity bills · 3 facilities" }],
    factor: { value: "supplier-specific / residual mix", source: "contractual instruments — missing for Modesto Bottling" },
    references: ["GHG Protocol Scope 2 Guidance — market-based", "CA SB 253"],
    note: "Market-based factor documentation missing for Modesto Bottling — raised as an evidence request.",
  },
};

function workingOf(row: VerificationRow): WorkingSpec | undefined {
  return row.working ?? WORKING[row.dataPointId];
}

function WorkingPanel({ spec }: { spec: WorkingSpec }) {
  return (
    <div className="s1-working">
      <div className="s1-working__grid">
        <section className="s1-working__block s1-working__block--wide">
          <h4>Formula</h4>
          <code className="s1-working__formula">{spec.formula}</code>
        </section>

        <section className="s1-working__block">
          <h4>Extracted data (cross-check to source)</h4>
          <ul className="s1-working__list">
            {spec.inputs.map((i) => (
              <li key={`${i.label}|${i.value}`}>
                <span className="s1-working__k">{i.label}</span>
                <span className="s1-working__v s1-mono">{i.value}</span>
                {i.source ? <span className="s1-working__src">{i.source}</span> : null}
              </li>
            ))}
          </ul>
        </section>

        <section className="s1-working__block">
          <h4>Emission factor</h4>
          {spec.factors?.length ? (
            <ul className="s1-working__list">
              {spec.factors.map((f) => (
                <li key={`${f.label}|${f.value}`}>
                  <span className="s1-working__k">{f.label}</span>
                  <span className="s1-working__v s1-mono">{f.value}</span>
                  <span className="s1-working__src">{f.source}</span>
                </li>
              ))}
            </ul>
          ) : spec.factor ? (
            <ul className="s1-working__list">
              <li>
                <span className="s1-working__v s1-mono">{spec.factor.value}</span>
                <span className="s1-working__src">{spec.factor.source}</span>
              </li>
            </ul>
          ) : (
            <p className="s1-muted">Not applicable.</p>
          )}
        </section>

        {spec.result ? (
          <section className="s1-working__block s1-working__block--wide">
            <h4>Result</h4>
            <p className="s1-working__result">{spec.result}</p>
          </section>
        ) : null}

        <section className="s1-working__block s1-working__block--wide">
          <h4>Sources &amp; references</h4>
          <div className="s1-working__refs">
            {spec.references.map((r) => (
              <span key={r} className="s1-working__ref">{r}</span>
            ))}
          </div>
        </section>
      </div>
      {spec.note ? <p className="s1-working__note">{spec.note}</p> : null}
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
              <th>Registered</th>
              <th>With the client since</th>
            </tr>
          </thead>
          <tbody>
            {Array.from(byCause.entries()).map(([cause, findings]) => (
              <Fragment key={cause}>
                <tr className="s1-ws-group">
                  <td colSpan={7}>{cause}</td>
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
                    <td>
                      {f.registeredBy ?? <span className="s1-muted">Not recorded</span>}
                      {f.registeredAt ? <div className="s1-mono s1-muted">{formatWhen(f.registeredAt)}</div> : null}
                    </td>
                    <td className="s1-muted">{f.withClientSince ?? "Request-linked"}</td>
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
            onClick={() => onRegister(sentence.trim(), cause.trim(), magnitude.trim() || "n/a")}
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

function formatWhen(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString(undefined, { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });
}

function rowLabel(row: VerificationRow): string {
  return row.label;
}
