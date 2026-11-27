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
import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

import type {
  CalcGas,
  CalcLineGas,
  CalcLineInputs,
  CalcLineResults,
  CalcLineStatus,
  CalcLineStep2,
  CalcUnplaced,
  CalcUnplacedReason,
  CalculationLine,
  RecalcComparison,
} from "../api/recalculation";
import { reportedSourceWords } from "../api/recalculation";
import type { RecalculationSettings } from "../types";
import type { TeamMember } from "../types/engagement";
import { differs, examinationKey, formatGasTonnes, formatInputQuantity, formatPercent, formatSignedGasTonnes } from "../utils/verificationTable";
import type { VerificationStore } from "../verification/verificationStore";
import { TraceSection } from "./calc-trace/TraceSection";
import { InfoTip } from "./InfoTip";
import { AddNote, RecordExamination, formatWhen } from "./VerificationWorkspace";

/**
 * Per-line calculation panels in Verification results (backend mode). One panel per category
 * (stationary, mobile, and each purchased energy type); a line opens to its steps as tabs, one at
 * a time. Every number and every status is the backend's (`calculation_lines`, `comparisons`):
 * this file only formats and lays them out.
 */

interface PanelDef {
  id: string;
  title: string;
  /** The `comparisons` key whose figures head the panel. */
  comparisonKey: string;
  category: string;
  /** For purchased energy, the level 2 name the panel holds. */
  level2?: string;
  /** What the second column of the lines table holds. */
  anchor: string;
  firstColumn: string;
}

const FIXED_PANELS: PanelDef[] = [
  { id: "stationary", title: "Scope 1 › Stationary combustion", comparisonKey: "stationary_combustion_total", category: "stationary", anchor: "Facility", firstColumn: "Fuel" },
  { id: "mobile", title: "Scope 1 › Mobile combustion", comparisonKey: "mobile_combustion_total", category: "mobile", anchor: "Vehicle group", firstColumn: "Fuel" },
];

/** One Scope 2 panel per energy type present, named from the line's level 2. */
function energyPanel(level2: string): PanelDef {
  const word = level2.trim().toLowerCase();
  return {
    id: `purchased_energy:${word}`,
    title: `Scope 2 › Purchased ${word}`,
    comparisonKey: `purchased_${word}_total`,
    category: "purchased_energy",
    level2,
    anchor: "Facility",
    firstColumn: "Energy",
  };
}

const GAS_LABEL: Record<CalcGas, string> = { CO2: "CO₂", CH4: "CH₄", N2O: "N₂O" };
const GASES: CalcGas[] = ["CO2", "CH4", "N2O"];

/** The units the backend converts, by dimension: a company's activity unit is picked from its line's. */
const UNIT_GROUPS: string[][] = [
  ["therm", "MMBtu", "Dth", "ccf", "Mcf", "scf"],
  ["gal", "L", "bbl"],
  ["kWh", "MWh"],
  ["kg", "lb", "short_ton", "metric_ton"],
];

export function unitsFor(unit: string): string[] {
  const lower = unit.toLowerCase();
  const group = UNIT_GROUPS.find((g) => g.some((u) => u.toLowerCase() === lower));
  return group ?? [unit];
}

/** Plain sentences for the flags the backend raises; a code not listed here is not shown. */
const FLAG_TEXT: Record<string, string> = {
  fuel_chosen_by_reviewer: "The EPA fuel is the one the reviewer chose.",
  fuel_auto_matched: "The EPA fuel was matched from the extracted fuel code, with no choice made.",
  diesel_matched_to_distillate_fuel_oil_no_2: "Diesel was matched to Distillate Fuel Oil No. 2.",
  prorated_to_reporting_period: "A record runs past the reporting period, so only its share inside counts.",
  no_reporting_period: "The engagement has no reporting period, so records count in full.",
  no_service_period: "A record has no service period, so it counts in full.",
  service_period_reversed: "A record's service period ends before it starts, so it counts in full.",
  unit_converted: "The quantity was converted to the factor's unit (Step 2).",
  biogenic_co2_reported_separately: "Biomass fuel: its CO₂ is biogenic and is reported separately, not in this line's CO₂e.",
  ch4_n2o_need_vehicle_groups: "No usable vehicle group, so CH₄ and N₂O are not calculated.",
  mixed_units_or_fuels: "This line mixes units or fuels: Step 2 shows the first, Step 3 lists every run.",
  company_ch4_n2o_use_vehicle_group: "On the company side, CH₄ and N₂O still come from the vehicle group.",
  no_evidence: "The company gave figures for this line, but no reviewed record is on it.",
  calculation_failed: "A calculation for this line failed. It shows what could be calculated.",
};

/** Why a record sits on no calculation line, in plain words. */
const UNPLACED_TEXT: Record<CalcUnplacedReason, string> = {
  unknown_line: "Filed on a line that no longer exists.",
  moved_to_another_place: "A reviewer filed it somewhere else.",
  fuel_shared_by_vehicle_groups: "Two or more vehicle groups use this fuel, so it can't go on one.",
  no_vehicle_group: "No vehicle group uses this fuel. Add one under Recalculation inputs.",
  no_facility_match: "No facility in Setup matches it.",
  identifier_on_two_facilities: "Its account or meter number points at more than one facility in Setup, so it is not placed.",
  no_calculation_line: "It has no calculation line.",
};

const qty = formatInputQuantity;

function factorText(value: number): string {
  return value === 1 ? "×1" : `×${qty(value)}`;
}

function period(start: string | null, end: string | null): string {
  if (!start || !end) return start ?? end ?? "No service period";
  return start === end ? start : `${start} to ${end}`;
}

/** The word that goes with a status, so colour is never the only signal. */
const STATUS_WORD: Record<CalcLineStatus, string> = {
  above: "above tolerance",
  within: "within tolerance",
  not_reported: "not reported",
};

function comparisonStatus(c: RecalcComparison | undefined): CalcLineStatus | null {
  if (!c) return null;
  if (c.status === "exceeds_tolerance") return "above";
  if (c.status === "within_tolerance") return "within";
  if (c.status === "not_reported") return "not_reported";
  return null;
}

function percentText(value: number): string {
  const text = `${Math.abs(value).toFixed(1)}%`;
  return value === 0 ? text : `${value > 0 ? "+" : "−"}${text}`;
}

/** A difference with its status word: red above tolerance, amber within, always with the word. */
function DiffChip({
  value,
  status,
  pct,
  incomplete,
}: {
  value: number | null;
  status: CalcLineStatus | null;
  pct?: number | null;
  incomplete?: boolean;
}) {
  const open = incomplete ? "inputs incomplete" : "";
  if (value === null) {
    return (
      <span className="s1-muted">
        {status ? STATUS_WORD[status] : "Not compared"}
        {open ? ` · ${open}` : ""}
      </span>
    );
  }
  const Arrow = value > 0 ? ArrowUpRight : ArrowDownRight;
  // The tolerance word and the open-inputs note go under the number, small and muted.
  const note = [status ? STATUS_WORD[status] : "", open].filter(Boolean).join(" · ");
  const quiet = !differs(value);
  return (
    <span className="s1-cp-diffcell">
      <span className={`s1-vw-delta${quiet ? " s1-vw-delta--zero" : status === "above" ? "" : " s1-vw-delta--below"}`}>
        {quiet ? null : <Arrow className="s1-vw-ico" aria-hidden />}
        {quiet ? "0" : formatSignedGasTonnes(value)}
        {pct !== null && pct !== undefined && !quiet ? ` (${percentText(pct)})` : ""}
      </span>
      {note ? <span className="s1-cp-sr"> · </span> : null}
      {note ? <span className="s1-muted s1-cp-diffnote">{note}</span> : null}
    </span>
  );
}

/** Where a figure comes from, as the backend states it. Only what the response carries is named. */
type SourceRef =
  | { kind: "document"; file: string; documentId: string; candidateId?: string }
  | { kind: "reference"; entry: string }
  | { kind: "entered"; by: string }
  | { kind: "company" };

/** The kind of reference a citation names, read from its own words. */
function referenceKind(entry: string): string {
  if (/egrid/i.test(entry)) return "eGRID";
  if (/ipcc|\bAR[4-6]\b/i.test(entry)) return "IPCC assessment report";
  if (/\bEPA\b.*\bHub\b|\bHub\b/i.test(entry)) return "EPA Hub table";
  return "Reference entry";
}

/**
 * A dotted-underlined input that opens its source beside it: a document (file and page), a reference
 * entry, or the company's own figures. The popover ends with "Open in Evidence →" when Evidence can be
 * opened. Closes on Escape or a click elsewhere.
 */
function SourceNote({
  label,
  source,
  onOpen,
}: {
  label: string;
  source: SourceRef;
  /** Opens the source in Evidence; the link is left out when this is absent. */
  onOpen?: () => void;
}) {
  const [at, setAt] = useState<{ top: number; left: number } | null>(null);
  const button = useRef<HTMLButtonElement>(null);
  const pop = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!at) return;
    const close = () => setAt(null);
    const onDown = (e: PointerEvent) => {
      const target = e.target as Node;
      if (!button.current?.contains(target) && !pop.current?.contains(target)) close();
    };
    const onKey = (e: globalThis.KeyboardEvent) => e.key === "Escape" && close();
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    window.addEventListener("scroll", close, true);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", close, true);
    };
  }, [at]);

  function toggle() {
    if (at) return setAt(null);
    const rect = button.current?.getBoundingClientRect();
    setAt({ top: rect ? rect.bottom + window.scrollY : 0, left: rect ? rect.left + window.scrollX : 0 });
  }

  return (
    <>
      <button ref={button} className="s1-cp-src" type="button" aria-expanded={Boolean(at)} onClick={toggle}>
        {label}
      </button>
      {at
        ? createPortal(
            <div ref={pop} className="s1-cp-pop" role="dialog" aria-label={`Source of ${label}`} style={{ top: at.top, left: at.left }}>
              {source.kind === "document" ? (
                <>
                  <p className="s1-cp-pop__kind">Document</p>
                  <p>{source.file}</p>
                  <p className="s1-muted">Page: Not available</p>
                </>
              ) : source.kind === "reference" ? (
                <>
                  <p className="s1-cp-pop__kind">{referenceKind(source.entry)}</p>
                  <p>Citation: {source.entry}</p>
                </>
              ) : source.kind === "entered" ? (
                <>
                  <p className="s1-cp-pop__kind">Entered input</p>
                  <p>Entered by {source.by}</p>
                </>
              ) : (
                <>
                  <p className="s1-cp-pop__kind">Company-reported</p>
                  <p className="s1-muted">Source: Not available</p>
                </>
              )}
              {onOpen ? (
                <button
                  className="s1-cp-pop__open"
                  type="button"
                  onClick={() => {
                    setAt(null);
                    onOpen();
                  }}
                >
                  Open in Evidence →
                </button>
              ) : null}
            </div>,
            document.body
          )
        : null}
    </>
  );
}

const NOT_AVAILABLE = <span className="s1-muted">Not available</span>;

/** "(+344.9)": the backend's own difference, shown beside the recomputed figure. Nothing when it gives none. */
function Paren({ value }: { value: number | null | undefined }) {
  if (value === null || value === undefined || !differs(value)) return null;
  return <span className="s1-cp-paren"> ({formatSignedGasTonnes(value)})</span>;
}

/** One titled block of a line's calculation. */
function StepBlock({ title, note, children }: { title: string; note?: string; children: ReactNode }) {
  return (
    <section className="s1-cp-step" aria-label={title}>
      <header className="s1-cp-step__head">
        <h5>{title}</h5>
        {note ? <span className="s1-muted">{note}</span> : null}
      </header>
      {children}
    </section>
  );
}

/** The company side of a block that has none: said once, in words. */
function NoCompany({ cols, text = "not reported" }: { cols: number; text?: string }) {
  return (
    <tr className="s1-cp-co">
      <td>Company</td>
      <td colSpan={cols}>
        <em className="s1-muted">{text}</em>
      </td>
    </tr>
  );
}

function MethodBlock({ line }: { line: CalculationLine }) {
  const equations = GASES.filter((g) => line.method.equations[g]);
  const references = [...new Set(line.step3.gases.map((g) => g.ef.source))];
  const gwpSources = [...new Set(line.step3.gases.map((g) => g.gwp.source))];
  return (
    <StepBlock title="Calculation method" note={line.method.route}>
      <ul className="s1-cp-eqs">
        {equations.map((g) => (
          <li key={g}>
            {GAS_LABEL[g]} <span className="s1-muted">·</span> {line.method.equations[g]}
          </li>
        ))}
      </ul>
      {references.length ? (
        <p className="s1-cp-ref">
          <span className="s1-muted">Reference </span>
          {references.map((r, i) => (
            <Fragment key={r}>
              {i ? ", " : null}
              <SourceNote label={r} source={{ kind: "reference", entry: r }} />
            </Fragment>
          ))}
        </p>
      ) : null}
      {gwpSources.length ? (
        <p className="s1-cp-ref">
          <span className="s1-muted">GWP </span>
          {gwpSources.join(", ")}
        </p>
      ) : null}
    </StepBlock>
  );
}

function Step1Block({
  line,
  onOpenDocument,
}: {
  line: CalculationLine;
  onOpenDocument?: (documentId: string, valueId?: string) => void;
}) {
  const total = line.step1.total;
  // Months counted in another unit than the total show their amount in the total's unit too.
  const mixed = line.step1.rows.some((r) => r.unit !== total.unit);
  return (
    <StepBlock title="Step 1 · Activity data" note="Sum of accepted evidence values for this line">
      <div className="s1-vw-scroll">
        <table className="s1-vw-steps s1-cp-grid">
          <thead>
            <tr>
              <th>Period</th>
              <th>Evidence</th>
              <th>Review</th>
              <th className="s1-vw-num">Company-reported</th>
              <th className="s1-vw-num s1-cp-rec">Recomputed (accepted values)</th>
              {mixed ? <th className="s1-vw-num">In {total.unit}</th> : null}
            </tr>
          </thead>
          <tbody>
            {line.step1.rows.map((r, index) => {
              const name = r.file_name ?? r.document_id;
              return (
                <tr key={`${r.document_id}:${index}`}>
                  <td>{period(r.period_start, r.period_end)}</td>
                  <td>
                    <SourceNote
                      label={name}
                      source={{ kind: "document", file: name, documentId: r.document_id, candidateId: r.candidate_id ?? undefined }}
                      onOpen={onOpenDocument ? () => onOpenDocument(r.document_id, r.candidate_id ?? undefined) : undefined}
                    />
                  </td>
                  <td>{r.review === "edited" ? "Edited by reviewer" : "Accepted"}</td>
                  <td className="s1-vw-num">{NOT_AVAILABLE}</td>
                  <td className="s1-vw-num s1-cp-rec">
                    {r.quantity === null ? (
                      <span className="s1-muted">No quantity</span>
                    ) : (
                      <>
                        {qty(r.counted_quantity)} {r.unit}
                        {r.share_in_period === 1 ? null : <span className="s1-muted"> · {formatPercent(r.share_in_period)} of {qty(r.quantity)} in period</span>}
                      </>
                    )}
                  </td>
                  {mixed ? (
                    <td className="s1-vw-num">
                      {r.counted_in_base === null ? <span className="s1-muted">Not convertible</span> : `${qty(r.counted_in_base)} ${total.unit}`}
                    </td>
                  ) : null}
                </tr>
              );
            })}
            <tr className="s1-vw-steps__total">
              <td colSpan={3}>Annual activity data</td>
              <td className="s1-vw-num">
                {line.company ? (
                  <SourceNote label={`${qty(line.company.activity.quantity)} ${line.company.activity.unit}`} source={{ kind: "company" }} />
                ) : (
                  <em className="s1-muted">not reported</em>
                )}
              </td>
              <td className="s1-vw-num s1-cp-rec">
                {qty(total.quantity)} {total.unit}
              </td>
              {mixed ? <td /> : null}
            </tr>
          </tbody>
        </table>
      </div>
    </StepBlock>
  );
}

function Step2Block({ line }: { line: CalculationLine }) {
  const row = (side: "Company" | "Recomputed", activity: { quantity: number; unit: string }, s: CalcLineStep2) => (
    <tr key={side} className={side === "Recomputed" ? "s1-cp-rec" : "s1-cp-co"}>
      <td>{side}</td>
      <td className="s1-vw-num">
        {qty(activity.quantity)} {activity.unit}
      </td>
      <td className="s1-cp-op">×</td>
      <td className="s1-vw-num">
        {s.from_unit} → {s.to_unit}{" "}
        {s.factor === 1 ? "×1" : <SourceNote label={factorText(s.factor)} source={{ kind: "reference", entry: s.source ?? "Unit conversion table." }} />}
      </td>
      <td className="s1-cp-op">=</td>
      <td className="s1-vw-num s1-cp-out">
        {qty(s.result.quantity)} {s.result.unit}
      </td>
    </tr>
  );
  const distance = line.step2.distance;
  const implied = line.step2.implied_fuel_economy;
  return (
    <StepBlock title="Step 2 · Unit conversion" note="Shared by all three gases">
      <div className="s1-vw-scroll">
        <table className="s1-vw-steps s1-cp-grid">
          <thead>
            <tr>
              <th />
              <th className="s1-vw-num">Activity data</th>
              <th />
              <th className="s1-vw-num">Unit conversion</th>
              <th />
              <th className="s1-vw-num">Converted quantity</th>
            </tr>
          </thead>
          <tbody>
            {line.company ? row("Company", line.company.activity, line.company.step2) : <NoCompany cols={5} />}
            {row("Recomputed", line.step1.total, line.step2)}
            {distance ? (
              <tr>
                <td>Distance (input)</td>
                <td className="s1-vw-num" colSpan={3}>
                  {qty(distance.quantity)} {distance.unit}{" "}
                  <SourceNote label="Entered" source={{ kind: "entered", by: distance.source }} />
                </td>
                <td />
                <td />
              </tr>
            ) : null}
            {implied ? (
              <tr>
                <td>Implied fuel economy (reasonableness check)</td>
                <td className="s1-vw-num" colSpan={3}>
                  {qty(implied.value)} {implied.unit}
                </td>
                <td />
                <td />
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </StepBlock>
  );
}

function Step3Block({
  line,
  gwpLabel,
}: {
  line: CalculationLine;
  gwpLabel: string;
}) {
  const equations = line.method.equations;
  const company = line.company?.step3.gases;
  const row = (g: CalcLineGas, side: "Company" | "Recomputed") => (
    <tr key={side} className={side === "Recomputed" ? "s1-cp-rec" : "s1-cp-co"}>
      <td>{side}</td>
      <td className="s1-vw-num">
        {qty(g.activity.value)} {g.activity.unit}
      </td>
      <td className="s1-cp-op">×</td>
      <td className="s1-vw-num">
        <SourceNote label={`${qty(g.ef.value)} ${g.ef.unit}`} source={{ kind: "reference", entry: g.ef.source }} />
      </td>
      <td className="s1-cp-op">×</td>
      <td className="s1-vw-num">{factorText(g.unit_conversion)}</td>
      <td className="s1-cp-op">=</td>
      <td className="s1-vw-num s1-cp-out">
        {formatGasTonnes(g.mass_t)}
        {g.biogenic ? <span className="s1-muted"> biogenic CO₂ (reported separately)</span> : null}
      </td>
      <td className="s1-cp-op">×</td>
      <td className="s1-vw-num">
        <SourceNote label={qty(g.gwp.value)} source={{ kind: "reference", entry: g.gwp.source }} />
      </td>
      <td className="s1-cp-op">=</td>
      <td className="s1-vw-num s1-cp-out">
        {formatGasTonnes(g.co2e_t)}
        {side === "Recomputed" ? <Paren value={g.difference_to_company_t} /> : null}
      </td>
    </tr>
  );
  return (
    <StepBlock title="Step 3 · Emissions by gas" note="One equation per gas">
      <div className="s1-cp-gwp">
        <span>GWP</span>
        <strong>{gwpLabel}</strong>
        <InfoTip label="GWP set">
          One set applies to the whole engagement: the one chosen in Methodology review. Change it there and Results recalculates every line.
        </InfoTip>
      </div>
      {line.step3.gases.map((g, index) => {
        // Pair by occurrence: the nth run of a gas on our side with the nth on theirs. A different count can't be paired.
        const ours = line.step3.gases.filter((x) => x.gas === g.gas);
        const same = company?.filter((c) => c.gas === g.gas) ?? [];
        const nth = ours.indexOf(g);
        const theirs = same.length === ours.length ? same[nth] : undefined;
        const unpaired = Boolean(company) && same.length !== ours.length;
        return (
          <div className="s1-vw-scroll" key={`${g.gas}:${index}`}>
            <table className="s1-vw-steps s1-cp-grid" aria-label={`${GAS_LABEL[g.gas]} emissions`}>
              <thead>
                <tr>
                  <th>
                    {GAS_LABEL[g.gas]}
                    {equations[g.gas] ? <span className="s1-muted"> · {equations[g.gas]}</span> : null}
                  </th>
                  <th className="s1-vw-num">Activity</th>
                  <th />
                  <th className="s1-vw-num">Emission factor</th>
                  <th />
                  <th className="s1-vw-num">Unit conversion</th>
                  <th />
                  <th className="s1-vw-num">Mass (t)</th>
                  <th />
                  <th className="s1-vw-num">GWP</th>
                  <th />
                  <th className="s1-vw-num">{GAS_LABEL[g.gas]} (t CO₂e)</th>
                </tr>
              </thead>
              <tbody>
                {theirs ? row(theirs, "Company") : unpaired ? <NoCompany cols={11} text="Not available" /> : <NoCompany cols={11} />}
                {row(g, "Recomputed")}
              </tbody>
            </table>
          </div>
        );
      })}
    </StepBlock>
  );
}

function ResultsBlock({ line }: { line: CalculationLine }) {
  const company = line.company?.results;
  const row = (label: string, pick: (r: CalcLineResults) => number, extra?: ReactNode, strong = false) => (
    <tr key={label} className={strong ? "s1-vw-steps__total" : undefined}>
      <td>{label}</td>
      <td className="s1-vw-num">{company ? formatGasTonnes(pick(company)) : <em className="s1-muted">not reported</em>}</td>
      <td className="s1-vw-num s1-cp-rec">
        {formatGasTonnes(pick(line.results))}
        {extra}
      </td>
    </tr>
  );
  return (
    <StepBlock title="Results" note="Sum of gases × consolidated share">
      <div className="s1-vw-scroll">
        <table className="s1-vw-steps s1-cp-grid">
          <thead>
            <tr>
              <th>Mass and CO₂e</th>
              <th className="s1-vw-num">Company-reported</th>
              <th className="s1-vw-num s1-cp-rec">Recomputed</th>
            </tr>
          </thead>
          <tbody>
            {GASES.map((gas) => row(`${GAS_LABEL[gas]} mass (t)`, (r) => r.mass_t[gas]))}
            {line.results.biogenic_co2_t !== 0 ? row("Biogenic CO₂ (t), reported separately", (r) => r.biogenic_co2_t) : null}
            {GASES.map((gas) => row(`${GAS_LABEL[gas]} as CO₂e (t)`, (r) => r.gas_co2e_t[gas]))}
            {row("CO₂e, sum of gases (t)", (r) => r.sum_co2e_t)}
            <tr>
              <td>× Consolidated share</td>
              <td className="s1-vw-num s1-cp-rec" colSpan={2}>
                {line.consolidated_share_pct}%
              </td>
            </tr>
            {row("Total CO₂e (t)", (r) => r.total_co2e_t, <Paren value={line.results.difference_to_company_t} />, true)}
          </tbody>
        </table>
      </div>
    </StepBlock>
  );
}

/** An unplaced item's flag sentences. A fuel shared by vehicle groups says so already, so the no-group flag is left out. */
function unplacedFlags(u: CalcUnplaced): string[] {
  return u.flags
    .filter((f) => !(f === "ch4_n2o_need_vehicle_groups" && u.reason === "fuel_shared_by_vehicle_groups"))
    .map((f) => FLAG_TEXT[f])
    .filter(Boolean);
}

/** Plain warnings for company figures and shares that match nothing in this engagement. */
function warnings(inputs: CalcLineInputs | undefined): string[] {
  if (!inputs) return [];
  const what: Record<string, string> = { reported_lines: "company total", reported_activity: "company activity" };
  return [
    ...inputs.unknown_line_keys.map((u) => `A ${what[u.setting] ?? "company figure"} is entered for "${u.key}", which matches no calculation line, so it is not used.`),
    ...inputs.unknown_facility_ids.map((id) => `A consolidated share is set for facility "${id}", which is not in Setup, so it is not used.`),
  ];
}

/** "Edit company figures": the company's total and annual activity for one line. Stays open until the save resolves. */
function CompanyForm({
  line,
  inputs,
  settings,
  onSave,
  onCancel,
}: {
  line: CalculationLine;
  inputs?: CalcLineInputs;
  settings: RecalculationSettings;
  /** Resolves to an error message, or null when saved. */
  onSave: (next: RecalculationSettings) => Promise<string | null>;
  onCancel: () => void;
}) {
  const current = settings.reported_activity?.[line.key];
  const [total, setTotal] = useState(settings.reported_lines?.[line.key]?.toString() ?? "");
  const [activity, setActivity] = useState(current?.quantity.toString() ?? "");
  const [unit, setUnit] = useState(current?.unit ?? line.step1.total.unit);
  const [errors, setErrors] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const units = unitsFor(line.step1.total.unit);
  const options = units.includes(unit) ? units : [unit, ...units];

  const number = (text: string) => (text.trim() === "" ? null : Number(text.replace(/,/g, "")));
  async function submit() {
    const found: string[] = [];
    const t = number(total);
    const a = number(activity);
    if (t !== null && (!Number.isFinite(t) || t < 0)) found.push("Enter the company's total as a number, 0 or more, in tonnes CO₂e.");
    if (a !== null && (!Number.isFinite(a) || a < 0)) found.push("Enter the company's activity as a number, 0 or more.");
    setErrors(found);
    if (found.length) return;
    const lines = { ...(settings.reported_lines ?? {}) };
    const acts = { ...(settings.reported_activity ?? {}) };
    if (t === null) delete lines[line.key];
    else lines[line.key] = t;
    if (a === null) delete acts[line.key];
    else acts[line.key] = { quantity: a, unit };
    setSaving(true);
    const failure = await onSave({ ...settings, reported_lines: lines, reported_activity: acts });
    setSaving(false);
    if (failure) setErrors([failure]);
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
          <select value={unit} onChange={(e) => setUnit(e.target.value)}>
            {options.map((u) => (
              <option key={u} value={u}>
                {u}
              </option>
            ))}
          </select>
        </label>
      </div>
      {warnings(inputs).map((message) => (
        <p key={message} className="s1-muted" role="note">
          {message}
        </p>
      ))}
      {errors.map((message) => (
        <p key={message} className="s1-vw-red" role="alert">
          {message}
        </p>
      ))}
      <div className="s1-vw-form-actions">
        <button className="s1-button" type="button" onClick={onCancel}>
          Cancel
        </button>
        <button className="s1-button s1-button--pri" type="button" disabled={saving} onClick={() => void submit()}>
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
  onSave,
  store,
  team,
  signedInLogin,
  onOpenDocument,
  onOpenEvidence,
  inputs,
  engagementId,
  onDecided,
}: {
  engagementId?: string;
  /** A reviewer decision was saved: fetch the recalculation again so the totals move. */
  onDecided?: () => void;
  line: CalculationLine;
  inputs?: CalcLineInputs;
  settings: RecalculationSettings;
  /** The backend's GWP wording (Methodology review's choice), shown as given. */
  gwpSet: string;
  onSave: (next: RecalculationSettings) => Promise<string | null>;
  store: VerificationStore;
  team: TeamMember[];
  signedInLogin?: string;
  onOpenDocument?: (documentId: string, valueId?: string) => void;
  onOpenEvidence?: (lineKey: string) => void;
}) {
  const [box, setBox] = useState<"examination" | "note" | "company" | null>(null);
  const key = examinationKey("calc", line.key);
  const examination = store.examinations[key];
  const examined = Boolean(examination?.examinedBy);
  const title = `${line.label} · ${line.level2}`;
  const flags = line.flags.map((f) => FLAG_TEXT[f]).filter(Boolean);

  return (
    <div className="s1-cp-detail">
      <h4 className="s1-cp-line-title">{title}</h4>
      {flags.length ? <p className="s1-muted s1-cp-flags">{flags.join(" ")}</p> : null}
      <TraceSection
        engagementId={engagementId}
        lineKey={line.key}
        version={`${line.results.total_co2e_t}|${line.reported_total_co2e_t}|${line.step1.total.quantity}|${gwpSet}`}
        onOpenDocument={onOpenDocument}
        onDecided={onDecided}
        fallback={
          <>
            <MethodBlock line={line} />
            <Step1Block line={line} onOpenDocument={onOpenDocument} />
            <Step2Block line={line} />
            <Step3Block line={line} gwpLabel={gwpSet} />
            <ResultsBlock line={line} />
          </>
        }
      />
      <div className="s1-vw-actions">
        {examined ? (
          <>
            <span className="s1-vw-examined-by">
              <Check className="s1-vw-ico" aria-hidden />
              Examined by {examination?.examinedBy}
            </span>
            <button className="s1-button s1-vw-action" type="button" onClick={() => store.clearExamination(key)}>
              Undo
            </button>
          </>
        ) : (
          <button className="s1-button s1-vw-action" type="button" aria-expanded={box === "examination"} onClick={() => setBox(box === "examination" ? null : "examination")}>
            <ClipboardCheck className="s1-vw-ico" aria-hidden />
            Record examination
          </button>
        )}
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
        <span className="s1-muted s1-cp-hint">Dotted-underlined inputs open their source. Document-backed inputs link to Evidence; reference entries show their citation.</span>
      </div>
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
          inputs={inputs}
          settings={settings}
          onCancel={() => setBox(null)}
          onSave={async (next) => {
            const failure = await onSave(next);
            if (!failure) setBox(null);
            return failure;
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

/** The panel ids the lines (and unplaced records) fill, in display order. */
export function panelIds(lines: CalculationLine[], unplaced: CalcUnplaced[] = []): string[] {
  const all = [...lines, ...unplaced];
  const energy = [...new Set(all.filter((l) => l.counts_toward === "purchased_energy").map((l) => l.level2))];
  return [...FIXED_PANELS, ...energy.map(energyPanel)].filter((p) => all.some((l) => belongs(l, p))).map((p) => p.id);
}

export function CalculationPanels({
  lines,
  comparisons,
  gwpSet,
  settings,
  onSave,
  store,
  team,
  signedInLogin,
  onOpenDocument,
  focusLineKey,
  onOpenEvidence,
  unplaced = [],
  inputs,
  engagementId,
  only,
  totals,
  onDecided,
}: {
  /** Fetches each opened line's step-by-step trace; without it the summary panel is shown. */
  engagementId?: string;
  /** Called after a reviewer decision on a line's working is saved, so the recalculation is fetched again. */
  onDecided?: () => void;
  /**
   * Draws just this panel's lines table, open and without its heading (the drawer a Results row opens).
   * A panel id: "stationary", "mobile" or "purchased_energy:electricity".
   */
  only?: string;
  /** With `only`: the Total row's figures, so the drawer's Total is the row's own (the scope table's). */
  totals?: { reported: number | null; recomputed: number | null; difference: number | null };
  lines: CalculationLine[];
  /** Records on no line, per panel as "Not on a calculation line". */
  unplaced?: CalcUnplaced[];
  /** Company figures and shares that match nothing, shown as warnings by the company form. */
  inputs?: CalcLineInputs;
  /** The recalculation's comparisons: each panel's Reported, Recomputed, Difference and status. */
  comparisons: RecalcComparison[];
  gwpSet: string;
  settings: RecalculationSettings;
  /** Saves settings.recalculation through the existing save path (which refetches); resolves to an error message or null. */
  onSave: (next: RecalculationSettings) => Promise<string | null>;
  store: VerificationStore;
  team: TeamMember[];
  signedInLogin?: string;
  onOpenDocument?: (documentId: string, valueId?: string) => void;
  /** Opens the panel holding this line, with the line expanded. */
  focusLineKey?: string;
  /** Shows "Open in Evidence" on each line when given. */
  onOpenEvidence?: (lineKey: string) => void;
}) {
  const energyTypes = [...new Set([...lines, ...unplaced].filter((l) => l.counts_toward === "purchased_energy").map((l) => l.level2))];
  const panels = [...FIXED_PANELS, ...energyTypes.map(energyPanel)].filter((p) => [...lines, ...unplaced].some((l) => belongs(l, p)));
  const [unplacedOpen, setUnplacedOpen] = useState<string | null>(null);
  const focused = lines.find((l) => l.key === focusLineKey);
  const panelOf = (line: CalculationLine | undefined) => panels.find((p) => line && belongs(line, p))?.id ?? null;
  const [openPanel, setOpenPanel] = useState<string | null>(panelOf(focused) ?? panels[0]?.id ?? null);
  // The drawer opens its first line that differs (or the first), as the reviewer's next click anyway.
  const [openLine, setOpenLine] = useState<string | null>(() => {
    if (focused) return focused.key;
    if (!only) return null;
    const own = lines.filter((l) => panels.some((p) => p.id === only && belongs(l, p)) && l.category !== "biogenic");
    return (own.find((l) => l.status === "above") ?? own[0])?.key ?? null;
  });
  const focusRef = useRef<HTMLTableRowElement | null>(null);

  // A new focus key (Evidence's link) opens its panel and line: adjusted while rendering, not in an effect.
  const [seenFocus, setSeenFocus] = useState(focusLineKey);
  if (focusLineKey !== seenFocus) {
    setSeenFocus(focusLineKey);
    if (focused) {
      setOpenPanel(panelOf(focused));
      setOpenLine(focused.key);
    }
  }
  useEffect(() => {
    if (openLine && openLine === focusLineKey) focusRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [openLine, focusLineKey]);

  if (!panels.length) return null;
  const shown = only ? panels.filter((p) => p.id === only) : panels;
  if (!shown.length) return null;
  const bare = Boolean(only);

  return (
    <section className={`s1-cp${bare ? " s1-cp--bare" : ""}`} aria-label={bare ? `${shown[0].title} by line` : "Calculation by line"}>
      {shown.map((panel) => {
        // Biogenic lines sit in the panel they count toward, after the others, under their own heading.
        const own = lines.filter((l) => belongs(l, panel));
        const panelLines = [...own.filter((l) => l.category !== "biogenic"), ...own.filter((l) => l.category === "biogenic")];
        const panelUnplaced = unplaced.filter((u) => belongs(u, panel));
        const head = comparisons.find((c) => c.key === panel.comparisonKey);
        const status = comparisonStatus(head);
        const reported = bare && totals ? totals.reported : (head?.reported ?? null);
        const recomputed = bare && totals ? totals.recomputed : (head?.recalculated ?? null);
        const difference = bare && totals ? totals.difference : (head?.difference ?? null);
        const open = bare || openPanel === panel.id;
        return (
          <div key={panel.id} className={`${bare ? "" : "s1-vw-box "}s1-cp-cat${open ? " is-open" : ""}`}>
            {bare ? null : <button
              className="s1-cp-head"
              type="button"
              aria-expanded={open}
              aria-controls={`s1-cp-cat-${panel.id}`}
              onClick={() => setOpenPanel(open ? null : panel.id)}
            >
              <ChevronRight className="s1-vw-ico s1-vw-box__chev" aria-hidden />
              <span className="s1-vw-box__title">{panel.title}</span>
              <span className="s1-cp-figures">
                <span>
                  <span className="s1-muted">Reported </span>
                  {reported === null ? <span className="s1-muted">Not entered</span> : formatGasTonnes(reported)}
                  {head?.reported_source?.document ? (
                    <span className="s1-muted s1-cp-source">
                      {" "}· {reportedSourceWords(head.reported_source.document)}
                      {head.reported_source.excluded
                        ? ` \u00b7 ${head.reported_source.excluded}`
                        : head.reported_source.used === "manual" && head.reported_source.differs
                          ? " (the figure entered differs)"
                          : ""}
                    </span>
                  ) : null}
                </span>
                <span>
                  <span className="s1-muted">Recomputed </span>
                  {recomputed === null ? <span className="s1-muted">Not calculated</span> : formatGasTonnes(recomputed)}
                </span>
                <span>
                  <span className="s1-muted">Difference </span>
                  <DiffChip value={difference} status={status} incomplete={head?.inputs_incomplete} />
                </span>
              </span>
            </button>}
            {open ? (
              <div className={bare ? undefined : "s1-vw-box__body"} id={`s1-cp-cat-${panel.id}`}>
                <div className={`s1-vw-scroll s1-cp-scroll${panelLines.some((l) => l.key === openLine) ? " is-expanded" : ""}`}>
                  <table className="s1-vw-table s1-cp-lines">
                    <thead>
                      <tr>
                        <th>{panel.firstColumn}</th>
                        <th>{panel.anchor} · unit</th>
                        <th className="s1-vw-num">Consolidated share</th>
                        <th className="s1-vw-num">Reported (t CO₂e)</th>
                        <th className="s1-vw-num">Recomputed (t CO₂e)</th>
                        <th className="s1-vw-num">Difference</th>
                        <th>Examined</th>
                      </tr>
                    </thead>
                    <tbody>
                      {panelLines.map((line, index) => {
                        const firstBiogenic = line.category === "biogenic" && panelLines.findIndex((l) => l.category === "biogenic") === index;
                        const isOpen = openLine === line.key;
                        const examined = Boolean(store.examinations[examinationKey("calc", line.key)]?.examinedBy);
                        return (
                          <Fragment key={line.key}>
                            {firstBiogenic ? (
                              <tr className="s1-vw-group">
                                <td colSpan={7}>Biogenic CO₂, reported separately</td>
                              </tr>
                            ) : null}
                            <tr className={`s1-vw-row${isOpen ? " is-selected" : ""}`} ref={line.key === focusLineKey ? focusRef : undefined}>
                              <td>{line.level2}</td>
                              <td>
                                <button className="s1-vw-rowbtn" type="button" aria-expanded={isOpen} onClick={() => setOpenLine(isOpen ? null : line.key)}>
                                  {line.label} · {line.step1.total.unit}
                                </button>
                              </td>
                              <td className="s1-vw-num">{line.consolidated_share_pct}%</td>
                              <td className="s1-vw-num">
                                {line.reported_total_co2e_t === null ? <span className="s1-muted">Not entered</span> : formatGasTonnes(line.reported_total_co2e_t)}
                              </td>
                              <td className="s1-vw-num">{formatGasTonnes(line.results.total_co2e_t)}</td>
                              <td className="s1-vw-num">
                                <DiffChip value={line.difference_t} status={line.status} pct={line.difference_pct_of_base} incomplete={line.inputs_incomplete} />
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
                                    onSave={onSave}
                                    store={store}
                                    team={team}
                                    signedInLogin={signedInLogin}
                                    onOpenDocument={onOpenDocument}
                                    onOpenEvidence={onOpenEvidence}
                                    inputs={inputs}
                                    engagementId={engagementId}
                                    onDecided={onDecided}
                                  />
                                </td>
                              </tr>
                            ) : null}
                          </Fragment>
                        );
                      })}
                      {panelUnplaced.length ? (
                        <>
                          <tr className="s1-vw-group">
                            <td colSpan={7}>
                              <button
                                className="s1-vw-rowbtn"
                                type="button"
                                aria-expanded={unplacedOpen === panel.id}
                                onClick={() => setUnplacedOpen(unplacedOpen === panel.id ? null : panel.id)}
                              >
                                Not on a calculation line · {panelUnplaced.length}
                              </button>
                            </td>
                          </tr>
                          {unplacedOpen === panel.id
                            ? panelUnplaced.map((u, i) => (
                                <tr key={`${u.reason}:${u.level2}:${u.label}:${i}`}>
                                  <td>{u.level2}</td>
                                  <td>
                                    {u.label} <span className="s1-muted">· {[UNPLACED_TEXT[u.reason], ...unplacedFlags(u)].join(" ")}</span>
                                  </td>
                                  <td />
                                  <td />
                                  <td className="s1-vw-num">
                                    {formatGasTonnes(u.results.total_co2e_t)}
                                    {u.results.biogenic_co2_t ? (
                                      <span className="s1-muted"> + {formatGasTonnes(u.results.biogenic_co2_t)} t biogenic CO₂, reported separately</span>
                                    ) : null}
                                  </td>
                                  <td />
                                  <td />
                                </tr>
                              ))
                            : null}
                        </>
                      ) : null}
                      <tr className="s1-vw-total">
                        <td colSpan={3}>Total</td>
                        <td className="s1-vw-num">{reported === null ? "" : formatGasTonnes(reported)}</td>
                        <td className="s1-vw-num">{recomputed === null ? "" : formatGasTonnes(recomputed)}</td>
                        <td className="s1-vw-num">
                          <DiffChip value={difference} status={status} incomplete={head?.inputs_incomplete} />
                        </td>
                        <td />
                      </tr>
                      {panelLines.some((l) => l.consolidated_share_pct < 100) ? (
                        <tr>
                          <td colSpan={7} className="s1-muted">
                            Totals shown after consolidated share; the category total reconciles before share.
                          </td>
                        </tr>
                      ) : null}
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

function belongs(line: { counts_toward: string; level2: string }, panel: PanelDef): boolean {
  return line.counts_toward === panel.category && (panel.level2 === undefined || line.level2 === panel.level2);
}
