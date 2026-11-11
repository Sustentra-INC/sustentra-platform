"use client";

import {
  ArrowDownRight,
  ArrowUpRight,
  Check,
  ChevronRight,
  ClipboardCheck,
  ExternalLink,
  Pencil,
  StickyNote,
} from "lucide-react";
import { Fragment, useEffect, useRef, useState, type KeyboardEvent } from "react";

import type { CalcGas, CalcLineGas, CalcLineResults, CalcLineStep2, CalculationLine } from "../api/recalculation";
import type { RecalculationSettings } from "../types";
import type { TeamMember } from "../types/engagement";
import type { ResultLine } from "../types/verificationResults";
import {
  differs,
  examinationKey,
  formatGasTonnes,
  formatInputQuantity,
  formatSignedGasTonnes,
  lineRecomputed,
  lineReported,
} from "../utils/verificationTable";
import type { VerificationStore } from "../verification/verificationStore";
import { InfoTip } from "./InfoTip";
import { AddNote, RecordExamination, formatWhen } from "./VerificationWorkspace";

/**
 * Per-line calculation panels in Verification results (backend mode). One panel per category
 * (stationary, mobile, purchased electricity); a line opens to its steps as tabs, one at a time.
 * Every number is the backend's (`calculation_lines`): this file only formats and lays them out.
 */

interface CategoryDef {
  id: string;
  /** The live results line whose totals head the panel. */
  resultLineId: string;
  title: string;
  /** What the second column of the lines table holds. */
  anchor: string;
}

const CATEGORIES: CategoryDef[] = [
  { id: "stationary", resultLineId: "s1-stationary", title: "Scope 1 › Stationary combustion", anchor: "Facility" },
  { id: "mobile", resultLineId: "s1-mobile", title: "Scope 1 › Mobile combustion", anchor: "Vehicle group" },
  { id: "purchased_energy", resultLineId: "s2l-electricity", title: "Scope 2 › Purchased electricity", anchor: "Facility" },
];

const GAS_LABEL: Record<CalcGas, string> = { CO2: "CO₂", CH4: "CH₄", N2O: "N₂O" };
const GASES: CalcGas[] = ["CO2", "CH4", "N2O"];
const GWP_SETS = ["AR4", "AR5", "AR6"];
const STEPS = ["Step 1 · Activity", "Step 2 · Unit", "Step 3 · Gases", "Results"] as const;

const qty = formatInputQuantity;

function factorText(value: number): string {
  return value === 1 ? "×1" : `×${qty(value)}`;
}

function period(start: string, end: string): string {
  return start === end ? start : `${start} to ${end}`;
}

/** The tone of a difference: material is red, below tolerance amber, none quiet. */
function tone(difference: number | null, reported: number | null, tolerancePct: number): "zero" | "material" | "below" {
  if (difference === null || !differs(difference)) return "zero";
  if (!reported) return "material";
  return Math.abs(difference) > (Math.abs(reported) * tolerancePct) / 100 ? "material" : "below";
}

function DiffChip({ value, reported, tolerancePct }: { value: number | null; reported: number | null; tolerancePct: number }) {
  if (value === null) return <span className="s1-muted">Not compared</span>;
  const t = tone(value, reported, tolerancePct);
  if (t === "zero") return <span className="s1-vw-delta s1-vw-delta--zero">0</span>;
  const Arrow = value > 0 ? ArrowUpRight : ArrowDownRight;
  return (
    <span className={`s1-vw-delta${t === "below" ? " s1-vw-delta--below" : ""}`}>
      <Arrow className="s1-vw-ico" aria-hidden />
      {formatSignedGasTonnes(value)}
    </span>
  );
}

function SourceNote({ label, source }: { label: string; source: string }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="s1-cp-src-wrap" onKeyDown={(e) => e.key === "Escape" && setOpen(false)}>
      <button className="s1-cp-src" type="button" aria-expanded={open} onClick={() => setOpen(!open)}>
        {label}
      </button>
      {open ? (
        <span className="s1-cp-pop" role="note">
          Source: {source}
        </span>
      ) : null}
    </span>
  );
}

function GasTable({ gases, equations }: { gases: CalcLineGas[]; equations: CalculationLine["method"]["equations"] }) {
  return (
    <div className="s1-vw-scroll">
      <table className="s1-vw-steps s1-cp-gas">
        <thead>
          <tr>
            <th>Gas</th>
            <th className="s1-vw-num">Activity</th>
            <th className="s1-vw-num">× Emission factor</th>
            <th className="s1-vw-num">× Unit conversion</th>
            <th className="s1-vw-num">= Mass (t)</th>
            <th className="s1-vw-num">× GWP</th>
            <th className="s1-vw-num">= CO₂e (t)</th>
          </tr>
        </thead>
        <tbody>
          {gases.map((g) => (
            <tr key={g.gas}>
              <td>
                {GAS_LABEL[g.gas]}
                {equations[g.gas] ? <span className="s1-muted"> · {equations[g.gas]}</span> : null}
              </td>
              <td className="s1-vw-num">
                {qty(g.activity.value)} {g.activity.unit}
              </td>
              <td className="s1-vw-num">
                <SourceNote label={`${qty(g.ef.value)} ${g.ef.unit}`} source={g.ef.source} />
              </td>
              <td className="s1-vw-num">{factorText(g.unit_conversion)}</td>
              <td className="s1-vw-num">{formatGasTonnes(g.mass_t)}</td>
              <td className="s1-vw-num">
                <SourceNote label={`×${qty(g.gwp.value)}`} source={g.gwp.source} />
              </td>
              <td className="s1-vw-num">{formatGasTonnes(g.co2e_t)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ResultsTable({ line }: { line: CalculationLine }) {
  const company = line.company?.results;
  const row = (label: string, pick: (r: CalcLineResults) => number, strong = false) => (
    <tr className={strong ? "s1-vw-steps__total" : undefined}>
      <td>{label}</td>
      <td className="s1-vw-num">{formatGasTonnes(pick(line.results))}</td>
      <td className="s1-vw-num">{company ? formatGasTonnes(pick(company)) : <span className="s1-muted">Not entered</span>}</td>
    </tr>
  );
  return (
    <div className="s1-vw-scroll">
      <table className="s1-vw-steps">
        <thead>
          <tr>
            <th>Mass and CO₂e</th>
            <th className="s1-vw-num">Recomputed</th>
            <th className="s1-vw-num">Company</th>
          </tr>
        </thead>
        <tbody>
          {GASES.map((gas) => row(`${GAS_LABEL[gas]} (t)`, (r) => r.mass_t[gas]))}
          {row("CO₂e, sum of gases (t)", (r) => r.sum_co2e_t)}
          <tr>
            <td>× Consolidated share</td>
            <td className="s1-vw-num" colSpan={2}>
              {line.consolidated_share_pct}%
            </td>
          </tr>
          {row("Total CO₂e (t)", (r) => r.total_co2e_t, true)}
        </tbody>
      </table>
    </div>
  );
}

function Step2Table({ line }: { line: CalculationLine }) {
  const row = (label: string, s: CalcLineStep2) => (
    <tr>
      <td>{label}</td>
      <td>
        {s.from_unit} → {s.to_unit}
      </td>
      <td className="s1-vw-num">{factorText(s.factor)}</td>
      <td className="s1-vw-num">
        {qty(s.result.quantity)} {s.result.unit}
      </td>
    </tr>
  );
  return (
    <div className="s1-vw-scroll">
      <table className="s1-vw-steps">
        <thead>
          <tr>
            <th>Side</th>
            <th>Unit</th>
            <th className="s1-vw-num">Conversion</th>
            <th className="s1-vw-num">Result</th>
          </tr>
        </thead>
        <tbody>
          {line.company ? row("Company", line.company.step2) : null}
          {row("Recomputed", line.step2)}
        </tbody>
      </table>
    </div>
  );
}

function Step1Table({ line, onOpenDocument }: { line: CalculationLine; onOpenDocument?: (documentId: string, valueId?: string) => void }) {
  const total = line.step1.total;
  return (
    <div className="s1-vw-scroll">
      <table className="s1-vw-steps">
        <thead>
          <tr>
            <th>Period</th>
            <th>Evidence</th>
            <th>Review</th>
            <th className="s1-vw-num">Quantity</th>
            <th className="s1-vw-num">Share in period</th>
            <th className="s1-vw-num">Counted</th>
          </tr>
        </thead>
        <tbody>
          {line.step1.rows.map((r) => (
            <tr key={`${r.document_id}:${r.candidate_id}`}>
              <td>{period(r.period_start, r.period_end)}</td>
              <td>
                {onOpenDocument ? (
                  <button className="s1-cp-src" type="button" onClick={() => onOpenDocument(r.document_id, r.candidate_id)}>
                    {r.file_name}
                  </button>
                ) : (
                  r.file_name
                )}
              </td>
              <td>{r.review === "edited" ? "Edited by reviewer" : "Accepted"}</td>
              <td className="s1-vw-num">
                {qty(r.quantity)} {r.unit}
              </td>
              <td className="s1-vw-num">{r.share_in_period === 1 ? "All" : `${qty(r.share_in_period * 100)}%`}</td>
              <td className="s1-vw-num">
                {qty(r.counted_quantity)} {r.unit}
              </td>
            </tr>
          ))}
          <tr className="s1-vw-steps__total">
            <td colSpan={5}>Recomputed total</td>
            <td className="s1-vw-num">
              {qty(total.quantity)} {total.unit}
            </td>
          </tr>
          <tr>
            <td colSpan={5}>Company reported</td>
            <td className="s1-vw-num">
              {line.company ? `${qty(line.company.activity.quantity)} ${line.company.activity.unit}` : <span className="s1-muted">Not entered</span>}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

/** "Edit company figures": the company's total and annual activity for one line. */
function CompanyForm({
  line,
  settings,
  saving,
  onSave,
  onCancel,
}: {
  line: CalculationLine;
  settings: RecalculationSettings;
  saving: boolean;
  onSave: (next: RecalculationSettings) => void;
  onCancel: () => void;
}) {
  const current = settings.reported_activity?.[line.key];
  const [total, setTotal] = useState(settings.reported_lines?.[line.key]?.toString() ?? "");
  const [activity, setActivity] = useState(current?.quantity.toString() ?? "");
  const [unit, setUnit] = useState(current?.unit ?? line.step1.total.unit);
  const [errors, setErrors] = useState<string[]>([]);

  const number = (text: string) => (text.trim() === "" ? null : Number(text.replace(/,/g, "")));
  function submit() {
    const found: string[] = [];
    const t = number(total);
    const a = number(activity);
    if (t !== null && (!Number.isFinite(t) || t < 0)) found.push("Enter the company's total as a number, 0 or more, in tonnes CO₂e.");
    if (a !== null && (!Number.isFinite(a) || a < 0)) found.push("Enter the company's activity as a number, 0 or more.");
    if (a !== null && !unit.trim()) found.push("Enter the unit the company reported its activity in, for example therms.");
    setErrors(found);
    if (found.length) return;
    const lines = { ...(settings.reported_lines ?? {}) };
    const acts = { ...(settings.reported_activity ?? {}) };
    if (t === null) delete lines[line.key];
    else lines[line.key] = t;
    if (a === null) delete acts[line.key];
    else acts[line.key] = { quantity: a, unit: unit.trim() };
    onSave({ ...settings, reported_lines: lines, reported_activity: acts });
  }

  return (
    <div className="s1-vw-box-form" role="group" aria-label={`Company figures · ${line.label}`}>
      <div className="s1-vw-label">Company figures · {line.label}</div>
      <div className="s1-cp-fields">
        <label className="s1-vw-field">
          <span>Company total (t CO₂e)</span>
          <input inputMode="decimal" value={total} onChange={(e) => setTotal(e.target.value)} />
        </label>
        <label className="s1-vw-field">
          <span>Company annual activity</span>
          <input inputMode="decimal" value={activity} onChange={(e) => setActivity(e.target.value)} />
        </label>
        <label className="s1-vw-field">
          <span>Activity unit</span>
          <input value={unit} onChange={(e) => setUnit(e.target.value)} />
        </label>
      </div>
      {errors.map((message) => (
        <p key={message} className="s1-vw-red" role="alert">
          {message}
        </p>
      ))}
      <div className="s1-vw-form-actions">
        <button className="s1-button" type="button" onClick={onCancel}>
          Cancel
        </button>
        <button className="s1-button s1-button--pri" type="button" disabled={saving} onClick={submit}>
          {saving ? "Saving…" : "Save company figures"}
        </button>
      </div>
      <p className="s1-muted s1-vw-help">The activity runs through the same steps and factors as the evidence, so the two sides compare like for like.</p>
    </div>
  );
}

function LineDetail({
  line,
  settings,
  gwpSet,
  saving,
  saveError,
  onSave,
  store,
  team,
  signedInLogin,
  onOpenDocument,
  onOpenEvidence,
}: {
  line: CalculationLine;
  settings: RecalculationSettings;
  gwpSet: string;
  saving: boolean;
  saveError: string | null;
  onSave: (next: RecalculationSettings) => void;
  store: VerificationStore;
  team: TeamMember[];
  signedInLogin?: string;
  onOpenDocument?: (documentId: string, valueId?: string) => void;
  onOpenEvidence?: (lineKey: string) => void;
}) {
  const [step, setStep] = useState(0);
  const [box, setBox] = useState<"examination" | "note" | "company" | null>(null);
  const key = examinationKey("calc", line.key);
  const examination = store.examinations[key];
  const examined = Boolean(examination?.examinedBy);
  const title = `${line.label} · ${line.level2}`;
  const ids = `s1-cp-${line.key}`;

  function onTabKey(event: KeyboardEvent<HTMLButtonElement>) {
    const move = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (!move) return;
    event.preventDefault();
    setStep((step + move + STEPS.length) % STEPS.length);
  }

  return (
    <div className="s1-cp-detail">
      <p className="s1-cp-route">
        {line.method.route}
        {line.flags.length ? <span className="s1-muted"> · {line.flags.join(", ")}</span> : null}
      </p>
      <div className="s1-cp-tabs" role="tablist" aria-label={`Steps · ${line.label}`}>
        {STEPS.map((name, i) => (
          <button
            key={name}
            id={`${ids}-tab-${i}`}
            className={`s1-cp-tab${step === i ? " is-on" : ""}`}
            type="button"
            role="tab"
            aria-selected={step === i}
            aria-controls={`${ids}-panel`}
            tabIndex={step === i ? 0 : -1}
            onClick={() => setStep(i)}
            onKeyDown={onTabKey}
          >
            {name}
          </button>
        ))}
      </div>
      <div className="s1-cp-tabpanel" role="tabpanel" id={`${ids}-panel`} aria-labelledby={`${ids}-tab-${step}`}>
        {step === 0 ? <Step1Table line={line} onOpenDocument={onOpenDocument} /> : null}
        {step === 1 ? <Step2Table line={line} /> : null}
        {step === 2 ? (
          <>
            <div className="s1-cp-gwp">
              <label htmlFor={`${ids}-gwp`}>GWP set</label>
              <select id={`${ids}-gwp`} value={gwpSet} disabled={saving} onChange={(e) => onSave({ ...settings, gwp_set: e.target.value })}>
                {GWP_SETS.map((g) => (
                  <option key={g} value={g}>
                    {g}
                  </option>
                ))}
              </select>
              <InfoTip label="GWP set">One set applies to the whole engagement. Changing it recalculates every line.</InfoTip>
            </div>
            <GasTable gases={line.step3.gases} equations={line.method.equations} />
            {line.company ? (
              <>
                <div className="s1-vw-label">Company side</div>
                <GasTable gases={line.company.step3.gases} equations={line.method.equations} />
              </>
            ) : null}
          </>
        ) : null}
        {step === 3 ? <ResultsTable line={line} /> : null}
      </div>
      <div className="s1-vw-actions">
        <button className={`s1-button s1-vw-action${examined ? " is-done" : ""}`} type="button" aria-expanded={box === "examination"} onClick={() => setBox(box === "examination" ? null : "examination")}>
          <ClipboardCheck className="s1-vw-ico" aria-hidden />
          Record examination
        </button>
        <button className="s1-button s1-vw-action" type="button" aria-expanded={box === "note"} onClick={() => setBox(box === "note" ? null : "note")}>
          <StickyNote className="s1-vw-ico" aria-hidden />
          Add notes
        </button>
        <button className="s1-button s1-vw-action" type="button" aria-expanded={box === "company"} onClick={() => setBox(box === "company" ? null : "company")}>
          <Pencil className="s1-vw-ico" aria-hidden />
          Edit company figures
        </button>
        {onOpenEvidence ? (
          <button className="s1-button s1-vw-action" type="button" onClick={() => onOpenEvidence(line.key)}>
            <ExternalLink className="s1-vw-ico" aria-hidden />
            Open in Evidence
          </button>
        ) : null}
        {examined ? (
          <span className="s1-vw-examined-by">
            <Check className="s1-vw-ico" aria-hidden />
            Examined by {examination?.examinedBy}
          </span>
        ) : null}
      </div>
      {saveError ? (
        <p className="s1-vw-red" role="alert">
          {saveError}
        </p>
      ) : null}
      {box === "examination" ? (
        <RecordExamination
          title={title}
          examination={examined ? examination : undefined}
          team={team}
          signedInLogin={signedInLogin}
          onCancel={() => setBox(null)}
          onSave={(examiner, note) => {
            store.recordExamination(key, examiner, note);
            setBox(null);
          }}
          onClear={() => {
            store.clearExamination(key);
            setBox(null);
          }}
        />
      ) : null}
      {box === "note" ? (
        <AddNote
          title={title}
          onCancel={() => setBox(null)}
          onSave={(text) => {
            store.addNote(key, text);
            setBox(null);
          }}
        />
      ) : null}
      {box === "company" ? (
        <CompanyForm
          line={line}
          settings={settings}
          saving={saving}
          onCancel={() => setBox(null)}
          onSave={(next) => {
            onSave(next);
            setBox(null);
          }}
        />
      ) : null}
      {examination?.notes?.length ? (
        <ul className="s1-vw-notes">
          {examination.notes.map((note, i) => (
            <li key={i}>
              {note.text}
              <span className="s1-muted">
                {" "}
                · {note.by ? `${note.by}, ` : ""}
                {formatWhen(note.at)}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export function CalculationPanels({
  lines,
  resultLines,
  tolerancePct,
  gwpSet,
  settings,
  saving,
  saveError,
  onSave,
  store,
  team,
  signedInLogin,
  onOpenDocument,
  focusLineKey,
  onOpenEvidence,
}: {
  lines: CalculationLine[];
  /** The live results lines: their totals head each panel, so no total is summed here. */
  resultLines: ResultLine[];
  tolerancePct: number;
  gwpSet: string;
  settings: RecalculationSettings;
  saving: boolean;
  saveError: string | null;
  /** Saves settings.recalculation through the existing save path (which refetches). */
  onSave: (next: RecalculationSettings) => void;
  store: VerificationStore;
  team: TeamMember[];
  signedInLogin?: string;
  onOpenDocument?: (documentId: string, valueId?: string) => void;
  /** Opens the panel holding this line, with the line expanded. */
  focusLineKey?: string;
  /** Shows "Open in Evidence" on each line when given. */
  onOpenEvidence?: (lineKey: string) => void;
}) {
  const present = CATEGORIES.filter((c) => lines.some((l) => l.category === c.id));
  const focused = lines.find((l) => l.key === focusLineKey);
  const [openCategory, setOpenCategory] = useState<string | null>(focused?.category ?? present[0]?.id ?? null);
  const [openLine, setOpenLine] = useState<string | null>(focused?.key ?? null);
  const focusRef = useRef<HTMLTableRowElement | null>(null);

  // A new focus key (Evidence's link) opens its panel and line: adjusted while rendering, not in an effect.
  const [seenFocus, setSeenFocus] = useState(focusLineKey);
  if (focusLineKey !== seenFocus) {
    setSeenFocus(focusLineKey);
    if (focused) {
      setOpenCategory(focused.category);
      setOpenLine(focused.key);
    }
  }
  useEffect(() => {
    if (openLine && openLine === focusLineKey) focusRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [openLine, focusLineKey]);

  if (!present.length) return null;

  return (
    <section className="s1-cp" aria-label="Calculation by line">
      {present.map((cat) => {
        const catLines = lines.filter((l) => l.category === cat.id);
        const head = resultLines.find((r) => r.id === cat.resultLineId);
        const reported = head ? lineReported(head) : null;
        const recomputed = head ? lineRecomputed(head) : null;
        const difference = reported !== null && recomputed !== null ? recomputed - reported : null;
        const open = openCategory === cat.id;
        return (
          <div key={cat.id} className={`s1-vw-box s1-cp-cat${open ? " is-open" : ""}`}>
            <button
              className="s1-cp-head"
              type="button"
              aria-expanded={open}
              aria-controls={`s1-cp-cat-${cat.id}`}
              onClick={() => setOpenCategory(open ? null : cat.id)}
            >
              <ChevronRight className="s1-vw-ico s1-vw-box__chev" aria-hidden />
              <span className="s1-vw-box__title">{cat.title}</span>
              <span className="s1-cp-figures">
                <span>
                  <span className="s1-muted">Reported </span>
                  {reported === null ? <span className="s1-muted">Not entered</span> : formatGasTonnes(reported)}
                </span>
                <span>
                  <span className="s1-muted">Recomputed </span>
                  {recomputed === null ? <span className="s1-muted">Not calculated</span> : formatGasTonnes(recomputed)}
                </span>
                <span>
                  <span className="s1-muted">Difference </span>
                  <DiffChip value={difference} reported={reported} tolerancePct={tolerancePct} />
                </span>
              </span>
            </button>
            {open ? (
              <div className="s1-vw-box__body" id={`s1-cp-cat-${cat.id}`}>
                <div className="s1-vw-scroll s1-cp-scroll">
                  <table className="s1-vw-table s1-cp-lines">
                    <thead>
                      <tr>
                        <th>{cat.id === "purchased_energy" ? "Energy" : "Fuel"}</th>
                        <th>{cat.anchor} · unit</th>
                        <th className="s1-vw-num">Share</th>
                        <th className="s1-vw-num">Reported (t CO₂e)</th>
                        <th className="s1-vw-num">Recomputed (t CO₂e)</th>
                        <th className="s1-vw-num">Difference</th>
                        <th>Examined</th>
                      </tr>
                    </thead>
                    <tbody>
                      {catLines.map((line) => {
                        const isOpen = openLine === line.key;
                        const examined = Boolean(store.examinations[examinationKey("calc", line.key)]?.examinedBy);
                        return (
                          <Fragment key={line.key}>
                            <tr className={`s1-vw-row${isOpen ? " is-selected" : ""}`} ref={line.key === focusLineKey ? focusRef : undefined}>
                              <td>{line.level2}</td>
                              <td>
                                <button
                                  className="s1-vw-rowbtn"
                                  type="button"
                                  aria-expanded={isOpen}
                                  onClick={() => setOpenLine(isOpen ? null : line.key)}
                                >
                                  {line.label} · {line.step1.total.unit}
                                </button>
                              </td>
                              <td className="s1-vw-num">{line.consolidated_share_pct}%</td>
                              <td className="s1-vw-num">
                                {line.reported_total_co2e_t === null ? <span className="s1-muted">Not entered</span> : formatGasTonnes(line.reported_total_co2e_t)}
                              </td>
                              <td className="s1-vw-num">{formatGasTonnes(line.results.total_co2e_t)}</td>
                              <td className="s1-vw-num">
                                <DiffChip value={line.difference_t} reported={line.reported_total_co2e_t} tolerancePct={tolerancePct} />
                              </td>
                              <td className={`s1-vw-examined${examined ? " is-done" : ""}`}>
                                {examined ? (
                                  <>
                                    <Check className="s1-vw-ico" aria-hidden />
                                    Examined
                                  </>
                                ) : (
                                  "Not examined"
                                )}
                              </td>
                            </tr>
                            {isOpen ? (
                              <tr className="s1-cp-expanded">
                                <td colSpan={7}>
                                  <LineDetail
                                    line={line}
                                    settings={settings}
                                    gwpSet={gwpSet}
                                    saving={saving}
                                    saveError={saveError}
                                    onSave={onSave}
                                    store={store}
                                    team={team}
                                    signedInLogin={signedInLogin}
                                    onOpenDocument={onOpenDocument}
                                    onOpenEvidence={onOpenEvidence}
                                  />
                                </td>
                              </tr>
                            ) : null}
                          </Fragment>
                        );
                      })}
                      <tr className="s1-vw-total">
                        <td colSpan={3}>Total</td>
                        <td className="s1-vw-num">{reported === null ? "" : formatGasTonnes(reported)}</td>
                        <td className="s1-vw-num">{recomputed === null ? "" : formatGasTonnes(recomputed)}</td>
                        <td className="s1-vw-num">
                          <DiffChip value={difference} reported={reported} tolerancePct={tolerancePct} />
                        </td>
                        <td />
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            ) : null}
          </div>
        );
      })}
    </section>
  );
}
