"use client";

import {
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  Check,
  ChevronRight,
  CircleCheck,
  ClipboardCheck,
  Cpu,
  FileSpreadsheet,
  FileText,
  Files,
  Flag,
  Flame,
  FlaskConical,
  Info,
  Leaf,
  Receipt,
  StickyNote,
  TriangleAlert,
  X,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { Fragment, useEffect, useMemo, useRef, useState } from "react";

import type { TeamMember } from "../types/engagement";
import type { Examination } from "../types/verification";
import type {
  CalcCell,
  CalcStep,
  FacilityResult,
  GasResultRow,
  ResultBoxKey,
  ResultBoxTotal,
  ResultLine,
  ResultState,
  SourceRef,
} from "../types/verificationResults";
import {
  buildResultBoxes,
  consolidatedShare,
  differs,
  examinationKey,
  facilityRecomputed,
  facilityReported,
  formatGasTonnes,
  formatPercent,
  formatSignedGasTonnes,
  formatSignedTonnes,
  formatTonnes,
  formatWholePercent,
  lineRecomputed,
  lineReported,
  type ResultBox,
  type ResultRow,
} from "../utils/verificationTable";
import type { VerificationStore } from "../verification/verificationStore";
import { InfoTip } from "./InfoTip";
import { VerificationSource } from "./VerificationSource";

/**
 * Verification results. The four boxes (Reported vs recomputed) fill the page and fold
 * to a summary line each; a row opens a panel from the right with its Calculation by
 * facility and, beside it, the Source of an underlined input. Esc or × closes it.
 */

const BOX_ICON: Record<ResultBoxKey, LucideIcon> = {
  scope1: Flame,
  scope2_location: Zap,
  scope2_market: Receipt,
  biogenic: Leaf,
};

/** What a finding is registered against: its data point, how Output lists it, and the difference to prefill. */
export interface FindingTarget {
  dataPointId: string;
  label: string;
  /** The magnitude to start from ("+25 tCO₂e (+2.0%)"); null when nothing is compared. */
  delta: string | null;
}

const BOX_CRUMB: Record<ResultBoxKey, string> = {
  scope1: "Scope 1",
  scope2_location: "Scope 2, location-based",
  scope2_market: "Scope 2, market-based",
  biogenic: "Biogenic CO₂",
};

export function VerificationWorkspace({
  lines,
  store,
  team,
  signedInLogin,
  boxTotals,
  gasRows,
  onOpenDocument,
  onRegisterFinding,
  materiality,
}: {
  lines: ResultLine[];
  store: VerificationStore;
  /** "Examined by" options: the engagement team from Setup. */
  team: TeamMember[];
  signedInLogin?: string;
  /** Live results: each box's own reported and recalculated totals, with their state. */
  boxTotals?: Partial<Record<ResultBoxKey, ResultBoxTotal>>;
  /** Live results: the per-gas data points, in a fold of their own under the boxes. */
  gasRows?: GasResultRow[];
  /** Live results: open a reviewed record's document (in Extraction review). */
  onOpenDocument?: (documentId: string) => void;
  /** Live results: each calculation card offers Register finding for its line. */
  onRegisterFinding?: (target: FindingTarget) => void;
  /**
   * Live results: the materiality tolerance as a fraction (0.05). A % material turns red only
   * at or above it, amber below; the demo reds every difference.
   */
  materiality?: number;
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [source, setSource] = useState<SourceRef | null>(null);
  const [openBoxes, setOpenBoxes] = useState<Set<ResultBoxKey>>(() => new Set<ResultBoxKey>(["scope1"]));
  const isExamined = (lineId: string, facilityId: string) =>
    Boolean(store.examinations[examinationKey(lineId, facilityId)]?.examinedBy);
  const boxes = useMemo(
    () =>
      buildResultBoxes(
        lines,
        (lineId, facilityId) => Boolean(store.examinations[examinationKey(lineId, facilityId)]?.examinedBy),
        boxTotals
      ),
    [lines, store.examinations, boxTotals]
  );
  const selected = lines.find((line) => line.id === selectedId) ?? null;
  // Live results: the panel's difference takes the tone of the line's row in its box.
  const selectedRow = selected ? boxes.flatMap((b) => b.rows).find((r) => r.key === selected.id) : undefined;
  const selectedMaterial = selectedRow ? rowIsMaterial(selectedRow, materiality) : undefined;

  const select = (id: string) => {
    const line = lines.find((l) => l.id === id);
    if (line) setOpenBoxes((cur) => (cur.has(line.box) ? cur : new Set(cur).add(line.box)));
    if (id === selectedId) return;
    setSelectedId(id);
    setSource(null);
  };
  const close = () => {
    setSelectedId(null);
    setSource(null);
  };
  const toggleBox = (key: ResultBoxKey) =>
    setOpenBoxes((cur) => {
      const next = new Set(cur);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  useEffect(() => {
    if (!selectedId) return;
    const onKey = (event: KeyboardEvent) => {
      // A dialog over the panel takes its own Escape: Register finding stops it on the document
      // before it reaches this window listener. The check below only covers dialogs that do not.
      if (event.key === "Escape" && !document.querySelector('[aria-modal="true"]')) {
        setSelectedId(null);
        setSource(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selectedId]);

  // On narrow screens Source stacks under Calculation: bring an opened document into view.
  const sourcePane = useRef<HTMLElement | null>(null);
  useEffect(() => {
    if (source) sourcePane.current?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
  }, [source]);

  return (
    <div className={`s1-vw${selected ? " has-panel" : ""}`}>
      <section className="s1-vw-boxes" aria-label="Reported vs recomputed">
        {boxes.map((box) => (
          <BoxPanel
            key={box.key}
            box={box}
            open={openBoxes.has(box.key)}
            onToggle={() => toggleBox(box.key)}
            selectedId={selectedId}
            onSelect={select}
            materiality={materiality}
          />
        ))}
        {gasRows?.length ? <GasPanel rows={gasRows} /> : null}
      </section>
      {selected ? (
        <aside className="s1-vw-panel" aria-label={`${BOX_CRUMB[selected.box]} · ${selected.activity}`}>
          <div className="s1-vw-panel__grid">
            <section className="s1-vw-pane s1-vw-pane--calc" aria-label="Calculation">
              <CalculationPane
                key={selected.id}
                line={selected}
                store={store}
                team={team}
                signedInLogin={signedInLogin}
                isExamined={isExamined}
                source={source}
                onOpenSource={setSource}
                onClose={close}
                onRegisterFinding={onRegisterFinding}
                material={selectedMaterial}
              />
            </section>
            <section ref={sourcePane} className="s1-vw-pane s1-vw-pane--source" aria-label="Source">
              <h2 className="s1-vw-pane__title">Source</h2>
              <VerificationSource source={source} onOpenDocument={onOpenDocument} />
            </section>
          </div>
        </aside>
      ) : null}
    </div>
  );
}

/* ================================== boxes ================================== */

/** A difference as a badge: an arrow and the signed tonnes, or a quiet 0. */
function Delta({ value, suffix = "", material }: { value: number | null; suffix?: string; material?: boolean }) {
  if (value === null) return null;
  if (!differs(value)) return <span className="s1-vw-delta s1-vw-delta--zero">0{suffix}</span>;
  const Arrow = value > 0 ? ArrowUpRight : ArrowDownRight;
  // Live results: below materiality the chip is amber (to review), above it red, as the pill.
  return (
    <span className={`s1-vw-delta${material === false ? " s1-vw-delta--below" : ""}`}>
      <Arrow className="s1-vw-ico" aria-hidden />
      {formatSignedTonnes(value)}
      {suffix}
    </span>
  );
}

/**
 * The colour of a % material or a difference. The demo reds any difference; live results red
 * one only above materiality (`material`), amber at or below it, as the backend judges it
 * (strictly above the tolerance) and as Output and the page's ⓘ say.
 */
function materialTone(difference: number | null, material: boolean | undefined): string {
  if (!differs(difference)) return "";
  if (material === undefined) return " s1-vw-red";
  return material ? " s1-vw-red" : " s1-vw-amber";
}

/**
 * Live results: whether a row's difference is material, judged as the backend judges a total:
 * its % material strictly above the tolerance; a reported 0 the evidence does not match is
 * (the backend's reported_zero). undefined in the demo.
 */
function rowIsMaterial(row: ResultRow, materiality: number | undefined): boolean | undefined {
  if (materiality === undefined) return undefined;
  if (row.reported === 0) return differs(row.difference);
  return row.pctMaterial !== null && Math.abs(row.pctMaterial) > materiality;
}

/** Live results: the pill says in words what its colour says (design standard §4). */
function livePillText(pct: number, difference: number, material: boolean): string {
  if (!differs(difference)) return `${formatPercent(pct, true)} · agrees`;
  return `${formatPercent(pct, true)} · ${material ? "above" : "below"} materiality`;
}

function BoxPanel({
  box,
  open,
  onToggle,
  selectedId,
  onSelect,
  materiality,
}: {
  box: ResultBox;
  open: boolean;
  onToggle: () => void;
  selectedId: string | null;
  onSelect: (id: string) => void;
  /** Live results: the tolerance as a fraction (0.05), for each row's % material colour. */
  materiality?: number;
}) {
  const Icon = BOX_ICON[box.key];
  const { totals, live } = box;
  const reportedRows = box.rows.filter((r) => !r.notReported);
  const differing = reportedRows.filter((r) => differs(r.difference)).length;
  const bodyId = `s1-vw-box-${box.key}`;
  // Live results: the box compares only when both totals are there and nothing holds it open.
  const compared = !live || (live.reported !== null && live.recomputed !== null && !live.state);
  const recomputedRows = reportedRows.filter((r) => !r.notTested).length;
  // Live: red only where the backend finds the total beyond tolerance; a reported 0 has no %.
  const boxMaterial = live ? Boolean(live.material) : undefined;
  const pctShown = !live || totals.pctDifference !== null;
  const pillTone = !differs(totals.difference)
    ? " s1-vw-pill--agrees"
    : boxMaterial === false
      ? " s1-vw-pill--open"
      : " s1-vw-pill--differs";
  return (
    <div className={`s1-vw-box s1-vw-tone--${box.key}${open ? " is-open" : ""}`}>
      <button className="s1-vw-box__head" type="button" aria-expanded={open} aria-controls={bodyId} onClick={onToggle}>
        <ChevronRight className="s1-vw-ico s1-vw-box__chev" aria-hidden />
        <span className="s1-vw-box__icon">
          <Icon className="s1-vw-ico" aria-hidden />
        </span>
        <span className="s1-vw-box__name">
          <span className="s1-vw-box__title">{box.title}</span>
          <span className="s1-vw-box__sub">
            {box.key === "biogenic"
              ? "Outside scopes · not added to any total"
              : live
                ? `${recomputedRows} recomputed ${recomputedRows === 1 ? "line" : "lines"}${differing ? ` · ${differing} differ` : ""}`
                : `${reportedRows.length} reported ${reportedRows.length === 1 ? "line" : "lines"} · ${
                    differing ? `${differing} differ` : "all agree"
                  }`}
          </span>
        </span>
        <span className={`s1-vw-box__figures${live ? " s1-vw-box__figures--live" : ""}`}>
          <span className="s1-vw-fig">
            <span className="s1-vw-fig__label">Reported</span>
            <span className="s1-vw-fig__value">
              {live?.reported === null ? <span className="s1-muted">Not entered</span> : formatTonnes(totals.reported)}
            </span>
          </span>
          <ArrowRight className="s1-vw-ico s1-vw-fig__arrow" aria-hidden />
          <span className="s1-vw-fig">
            <span className="s1-vw-fig__label">Recomputed</span>
            <span className="s1-vw-fig__value">
              {live?.recomputed === null ? <span className="s1-muted">Not available</span> : formatTonnes(totals.recomputed)}
            </span>
          </span>
          {compared ? (
            <>
              <Delta value={totals.difference} material={boxMaterial} />
              <span className={`s1-vw-pill${pillTone}`}>
                {!live
                  ? `${formatPercent(totals.pctMaterial, true)} material`
                  : pctShown
                    ? livePillText(totals.pctMaterial, totals.difference, Boolean(boxMaterial))
                    : differs(totals.difference)
                      ? "Above materiality"
                      : "Agrees"}
              </span>
            </>
          ) : (
            // In the difference and pill columns. No ⓘ inside the header button: the reason sits under the table.
            <span className="s1-vw-box__state">
              {live?.state ? <span className={`s1-state s1-state--${live.state.tone}`}>{live.state.label}</span> : null}
            </span>
          )}
          <span className="s1-vw-box__meta">
            <ClipboardCheck className="s1-vw-ico" aria-hidden />
            {totals.examined}/{totals.facilities}
          </span>
        </span>
      </button>
      {open ? (
        <div className="s1-vw-box__body" id={bodyId}>
          <BoxTable box={box} compared={compared} selectedId={selectedId} onSelect={onSelect} materiality={materiality} />
          <div className="s1-vw-box__lines">
            {live ? (
              <>
                {live.state ? <StateChip state={live.state} /> : null}
                {live.notes?.map((note) => <span key={note}>{note}</span>)}
              </>
            ) : (
              <span>Coverage: {formatWholePercent(totals.share)}</span>
            )}
            {compared && pctShown ? (
              <span>
                Total % material:{" "}
                <span className={materialTone(totals.difference, boxMaterial).trim() || undefined}>
                  {formatPercent(totals.pctMaterial, true)}
                </span>
              </span>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

/**
 * A state the numbers cannot say (live results): its word always, its reason behind the ⓘ.
 * A click on the ⓘ stays here: it never selects the row it sits in.
 */
function StateChip({ state }: { state: ResultState }) {
  return (
    <span className="s1-vw-state" onClick={(event) => event.stopPropagation()}>
      <span className={`s1-state s1-state--${state.tone}`}>{state.label}</span>
      {state.detail ? <InfoTip label={state.label}>{state.detail}</InfoTip> : null}
    </span>
  );
}

function BoxTable({
  box,
  compared,
  selectedId,
  onSelect,
  materiality,
}: {
  box: ResultBox;
  /** Whether the totals compare (always in the demo; live, only with both totals and nothing open). */
  compared: boolean;
  selectedId: string | null;
  onSelect: (id: string) => void;
  materiality?: number;
}) {
  const scope1 = box.key === "scope1";
  const { totals, live } = box;
  const span = scope1 ? 2 : 1;
  return (
    <div className="s1-vw-scroll">
      <table className="s1-vw-table">
        <thead>
          <tr>
            {scope1 ? (
              <>
                <th>Category</th>
                <th>Activity</th>
              </>
            ) : (
              <th>Data point</th>
            )}
            <th className="s1-vw-num">
              Reported <span className="s1-vw-unit">(tCO₂e)</span>
            </th>
            <th className="s1-vw-num">
              Recomputed <span className="s1-vw-unit">(tCO₂e)</span>
            </th>
            <th className="s1-vw-num">Difference</th>
            <th className="s1-vw-num">% Difference</th>
            <th className="s1-vw-num">% Material</th>
            <th className="s1-vw-num">Share</th>
            <th className="s1-vw-num s1-vw-examined">Examined</th>
          </tr>
        </thead>
        <tbody>
          {box.rows.map((row) =>
            row.notReported ? (
              <UnreportedRow key={row.key} row={row} scope1={scope1} />
            ) : (
              <ReportedRow
                key={row.key}
                row={row}
                scope1={scope1}
                selected={row.key === selectedId}
                onSelect={onSelect}
                materiality={materiality}
              />
            )
          )}
          {live ? (
            <tr className="s1-vw-total">
              <td colSpan={span}>{box.totalLabel}</td>
              <td className="s1-vw-num">{live.reported === null ? <span className="s1-muted">Not entered</span> : formatTonnes(live.reported)}</td>
              <td className="s1-vw-num">
                {live.recomputed === null ? <span className="s1-muted">Not available</span> : formatTonnes(live.recomputed)}
              </td>
              {compared ? (
                <>
                  <td className="s1-vw-num">
                    <Delta value={totals.difference} material={Boolean(live.material)} />
                  </td>
                  <td className="s1-vw-num">{totals.pctDifference === null ? "" : formatPercent(totals.pctDifference, true)}</td>
                  {/* A reported 0 has no % material: the backend calls any difference from it material. */}
                  <td className={`s1-vw-num${materialTone(totals.difference, Boolean(live.material))}`}>
                    {totals.pctDifference !== null
                      ? formatPercent(totals.pctMaterial, true)
                      : differs(totals.difference)
                        ? "Above materiality"
                        : ""}
                  </td>
                </>
              ) : (
                <td colSpan={3} />
              )}
              {/* The live share of a row is of the reported total, so the rows need not add up to 100%. */}
              <td />
              <td className="s1-vw-num s1-vw-examined">
                {totals.examined} of {totals.facilities}
              </td>
            </tr>
          ) : (
            <tr className="s1-vw-total">
              <td colSpan={span}>{box.totalLabel}</td>
              <td className="s1-vw-num">{formatTonnes(totals.reported)}</td>
              <td className="s1-vw-num">{formatTonnes(totals.recomputed)}</td>
              <td className="s1-vw-num">
                <Delta value={totals.difference} />
              </td>
              <td className="s1-vw-num">{totals.pctDifference === null ? "" : formatPercent(totals.pctDifference, true)}</td>
              <td className={`s1-vw-num${differs(totals.difference) ? " s1-vw-red" : ""}`}>
                {formatPercent(totals.pctMaterial, true)}
              </td>
              <td className="s1-vw-num">{formatPercent(totals.share)}</td>
              <td className="s1-vw-num s1-vw-examined">
                {totals.examined} of {totals.facilities}
              </td>
            </tr>
          )}
          {box.normalizedMaterial !== null ? (
            <tr className="s1-vw-normalized">
              <td colSpan={span}>Normalized</td>
              <td colSpan={4} />
              <td className="s1-vw-num">{formatPercent(box.normalizedMaterial, true)}</td>
              <td className="s1-vw-num">100.0%</td>
              <td className="s1-vw-examined" />
            </tr>
          ) : null}
        </tbody>
      </table>
    </div>
  );
}

function ReportedRow({
  row,
  scope1,
  selected,
  onSelect,
  materiality,
}: {
  row: ResultRow;
  scope1: boolean;
  selected: boolean;
  onSelect: (id: string) => void;
  /** Live results: a row's % material is red only at or above it. */
  materiality?: number;
}) {
  const select = () => onSelect(row.key);
  const rowMaterial = rowIsMaterial(row, materiality);
  const name = (
    <button className="s1-vw-rowbtn" type="button" aria-pressed={selected} onClick={select}>
      {row.activity}
      <ChevronRight className="s1-vw-ico s1-vw-rowbtn__go" aria-hidden />
    </button>
  );
  const allExamined = row.facilities > 0 && row.examined === row.facilities;
  // Live results: the state sits beside the name, so the number columns stay numbers.
  const named = row.state ? (
    <span className="s1-vw-named">
      {name}
      <StateChip state={row.state} />
    </span>
  ) : (
    name
  );
  return (
    <tr className={`s1-vw-row${selected ? " is-selected" : ""}${differs(row.difference) ? " is-different" : ""}`} onClick={select}>
      {scope1 ? (
        <>
          <td className="s1-vw-category">
            {row.categoryLabel ? (
              <span className={`s1-vw-cat s1-vw-cat--${row.categoryLabel.split(" ")[0].toLowerCase()}`}>{row.categoryLabel}</span>
            ) : null}
          </td>
          <td className="s1-vw-name">{named}</td>
        </>
      ) : (
        <td className="s1-vw-name">{named}</td>
      )}
      <td className="s1-vw-num">
        {row.reported !== null ? formatTonnes(row.reported) : row.reportedNote ? <span className="s1-muted">{row.reportedNote}</span> : ""}
      </td>
      {row.notTested ? (
        <>
          <td className="s1-vw-num s1-muted">not tested</td>
          <td colSpan={3} />
        </>
      ) : (
        <>
          <td className="s1-vw-num">{row.recomputed === null ? "" : formatTonnes(row.recomputed)}</td>
          <td className="s1-vw-num">
            <Delta value={row.difference} material={rowMaterial} />
          </td>
          <td className="s1-vw-num">{row.pctDifference === null ? "" : formatPercent(row.pctDifference, true)}</td>
          <td className={`s1-vw-num${materialTone(row.difference, rowMaterial)}`}>
            {row.pctMaterial !== null
              ? formatPercent(row.pctMaterial, true)
              : // Live: a reported 0 the evidence does not match has no %, and is material (as Output says).
                rowMaterial && row.reported === 0
                ? "Above materiality"
                : ""}
          </td>
        </>
      )}
      <td className="s1-vw-num">
        {row.share === null ? (
          ""
        ) : (
          <span className="s1-vw-share">
            <span className="s1-vw-share__value">{formatPercent(row.share)}</span>
            <span className="s1-vw-share__bar" style={{ width: `${Math.min(100, row.share * 100)}%` }} aria-hidden />
          </span>
        )}
      </td>
      <td className={`s1-vw-num s1-vw-examined${allExamined ? " is-done" : ""}`}>
        {allExamined ? <Check className="s1-vw-ico" aria-hidden /> : null}
        {row.examined} of {row.facilities}
      </td>
    </tr>
  );
}

function UnreportedRow({ row, scope1 }: { row: ResultRow; scope1: boolean }) {
  // Live results: a row with nothing reported and nothing recalculated says why instead.
  if (row.state) {
    return (
      <tr className="s1-vw-row is-unreported is-stated">
        {scope1 ? <td className="s1-vw-category">{row.categoryLabel}</td> : <td>{row.activity}</td>}
        <td colSpan={scope1 ? 8 : 7}>
          <StateChip state={row.state} />
        </td>
      </tr>
    );
  }
  return (
    <tr className="s1-vw-row is-unreported">
      {scope1 ? (
        <>
          <td className="s1-vw-category">{row.categoryLabel}</td>
          <td className="s1-vw-name">Not reported</td>
          <td colSpan={7} />
        </>
      ) : (
        <>
          <td>{row.activity}</td>
          <td className="s1-vw-num">Not reported</td>
          <td colSpan={6} />
        </>
      )}
    </tr>
  );
}

const GAS_GROUPS = ["Scope 1", "Scope 2, location-based", "Scope 2, market-based"];

/**
 * Live results: the per-gas data points (workbook rows 23-37, Required), in tonnes of each
 * gas. The boxes are in CO₂e by activity, so these fold on their own, closed at first.
 */
function GasPanel({ rows }: { rows: GasResultRow[] }) {
  const [open, setOpen] = useState(false);
  const entered = rows.filter((r) => r.reported !== null).length;
  const differing = rows.filter((r) => r.state?.tone === "blocking").length;
  const groups = [...GAS_GROUPS, ...rows.map((r) => r.group).filter((g) => !GAS_GROUPS.includes(g))];
  return (
    <div className={`s1-vw-box s1-vw-gases${open ? " is-open" : ""}`}>
      <button className="s1-vw-box__head" type="button" aria-expanded={open} aria-controls="s1-vw-box-gases" onClick={() => setOpen(!open)}>
        <ChevronRight className="s1-vw-ico s1-vw-box__chev" aria-hidden />
        <span className="s1-vw-box__icon">
          <FlaskConical className="s1-vw-ico" aria-hidden />
        </span>
        <span className="s1-vw-box__name">
          <span className="s1-vw-box__title">By gas</span>
          <span className="s1-vw-box__sub">Required data points, in tonnes of each gas</span>
        </span>
        <span className="s1-vw-box__figures">
          <span className="s1-vw-box__meta s1-vw-box__count">
            {entered} of {rows.length} reported values entered
            {differing ? <span className="s1-state s1-state--blocking">{differing} exceed</span> : null}
          </span>
        </span>
      </button>
      {open ? (
        <div className="s1-vw-box__body" id="s1-vw-box-gases">
          <div className="s1-vw-scroll">
            <table className="s1-vw-table">
              <thead>
                <tr>
                  <th>Data point</th>
                  <th>Unit</th>
                  <th className="s1-vw-num">Reported</th>
                  <th className="s1-vw-num">Recomputed</th>
                  <th className="s1-vw-num">Difference</th>
                  <th className="s1-vw-num">% Difference</th>
                  <th>State</th>
                </tr>
              </thead>
              <tbody>
                {groups.map((group) => {
                  const own = rows.filter((r) => r.group === group);
                  if (!own.length) return null;
                  return (
                    <Fragment key={group}>
                      <tr className="s1-vw-group">
                        <td colSpan={7}>{group}</td>
                      </tr>
                      {own.map((row) => (
                        <tr key={row.key} className="s1-vw-gasrow">
                          <td>{row.gas}</td>
                          <td>{row.unit ?? <span className="s1-muted">To confirm</span>}</td>
                          <td className="s1-vw-num">
                            {row.reported === null ? <span className="s1-muted">Not entered</span> : formatGasTonnes(row.reported)}
                          </td>
                          <td className="s1-vw-num">{row.recomputed === null ? "" : formatGasTonnes(row.recomputed)}</td>
                          <td className="s1-vw-num">{row.difference === null ? "" : formatSignedGasTonnes(row.difference)}</td>
                          <td className="s1-vw-num">{row.pctDifference === null ? "" : formatPercent(row.pctDifference, true)}</td>
                          <td>{row.state ? <StateChip state={row.state} /> : null}</td>
                        </tr>
                      ))}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
    </div>
  );
}

/* ============================ calculation panel ============================ */

function nameColumn(line: ResultLine): string {
  if (line.box !== "scope1") return "Data point";
  return line.category === "Fugitive emissions" ? "Refrigerant" : "Fuel";
}

/** After the facility's consolidated share, like the line it adds up to. */
function facilityDifference(line: ResultLine, facility: FacilityResult): number | null {
  const reported = facilityReported(line, facility);
  const recomputed = facilityRecomputed(line, facility);
  return recomputed === null || reported === null ? null : recomputed - reported;
}

/** Scope 1 and 2 lines consolidate each facility by its share; biogenic CO₂ does not. */
function hasShare(line: ResultLine): boolean {
  // Live results apply no boundary share: no Consolidated share column (see consolidatedShare).
  return line.box !== "biogenic" && !line.noBoundaryShare;
}

function CalculationPane({
  line,
  store,
  team,
  signedInLogin,
  isExamined,
  source,
  onOpenSource,
  onClose,
  onRegisterFinding,
  material,
}: {
  line: ResultLine;
  store: VerificationStore;
  team: TeamMember[];
  signedInLogin?: string;
  isExamined: (lineId: string, facilityId: string) => boolean;
  source: SourceRef | null;
  onOpenSource: (source: SourceRef) => void;
  onClose: () => void;
  onRegisterFinding?: (target: FindingTarget) => void;
  /** Live results: whether the line's difference is above materiality (undefined in the demo). */
  material?: boolean;
}) {
  const facilities = line.facilities ?? [];
  // The facility that explains the difference opens first; with none, the first one.
  const [openId, setOpenId] = useState<string | null>(
    () => (facilities.find((f) => differs(facilityDifference(line, f))) ?? facilities[0])?.facilityId ?? null
  );
  // Live results: a line's reported value may be missing ("Not entered", or reported as a total only).
  const ownReported = lineReported(line);
  const reportedNote = ownReported === null && line.reported !== undefined ? line.reportedNote ?? "Not entered" : null;
  const reported = ownReported ?? 0;
  const recomputed = lineRecomputed(line);
  // A live line still partial is not compared, here as in its row.
  const difference = recomputed === null || reportedNote || line.inconclusive ? null : recomputed - reported;
  const crumbs = [BOX_CRUMB[line.box], line.category, line.activity].filter(Boolean) as string[];
  const Icon = BOX_ICON[line.box];
  const share = hasShare(line);
  const columns = share ? 6 : 5;
  // A finding is about the line (the data point), whichever facility's card it is raised from.
  const registerFinding = onRegisterFinding
    ? () =>
        onRegisterFinding({
          dataPointId: `vr:${line.id}`,
          label: crumbs.join(" · "),
          delta:
            difference === null
              ? null
              : `${formatSignedTonnes(difference)} tCO₂e${reported ? ` (${formatPercent(difference / reported, true)})` : ""}`,
        })
    : undefined;

  return (
    <div className="s1-vw-calc">
      <header className={`s1-vw-calc__head s1-vw-tone--${line.box}`}>
        <span className="s1-vw-box__icon">
          <Icon className="s1-vw-ico" aria-hidden />
        </span>
        <div className="s1-vw-calc__title">
          <h2 className="s1-vw-crumb">
            {crumbs.map((crumb, i) => (
              <Fragment key={crumb}>
                {i ? <span className="s1-vw-crumb__sep"> › </span> : null}
                {crumb}
              </Fragment>
            ))}
          </h2>
          <p className="s1-vw-summary">
            <span>
              Reported <strong>{reportedNote ?? formatTonnes(reported)}</strong>
            </span>
            <span>
              Recomputed <strong>{recomputed === null ? "not tested" : formatTonnes(recomputed)}</strong>
            </span>
            {difference === null ? null : (
              <span>
                Difference{" "}
                <strong className={materialTone(difference, material).trim() || undefined}>{formatSignedTonnes(difference)}</strong>
              </span>
            )}
          </p>
        </div>
        <button className="s1-vw-close" type="button" aria-label="Close calculation" onClick={onClose}>
          <X className="s1-vw-ico" aria-hidden />
        </button>
      </header>
      <div className="s1-vw-scroll">
        <table className="s1-vw-table s1-vw-facilities">
          <thead>
            <tr>
              <th>{nameColumn(line)}</th>
              <th>Facility</th>
              {share ? <th className="s1-vw-num">Consolidated share</th> : null}
              <th className="s1-vw-num">
                Reported <span className="s1-vw-unit">(tCO₂e)</span>
              </th>
              <th className="s1-vw-num">
                Recomputed <span className="s1-vw-unit">(tCO₂e)</span>
              </th>
              <th className="s1-vw-num">Difference</th>
            </tr>
          </thead>
          <tbody>
            {facilities.map((facility) => {
              const open = facility.facilityId === openId;
              const diff = facilityDifference(line, facility);
              const facReported = facilityReported(line, facility);
              const facRecomputed = facilityRecomputed(line, facility);
              const examined = isExamined(line.id, facility.facilityId);
              return (
                <Fragment key={facility.facilityId}>
                  <tr
                    className={`s1-vw-row${differs(diff) ? " is-different" : ""}${open ? " is-open" : ""}`}
                    onClick={() => setOpenId(open ? null : facility.facilityId)}
                  >
                    <td>{facility.activity ?? line.activity}</td>
                    <td>
                      <button
                        className="s1-vw-rowbtn s1-vw-facility"
                        type="button"
                        aria-expanded={open}
                        onClick={(event) => {
                          event.stopPropagation();
                          setOpenId(open ? null : facility.facilityId);
                        }}
                      >
                        <ChevronRight className="s1-vw-ico s1-vw-caret" aria-hidden />
                        {facility.facility}
                        {examined ? (
                          <span className="s1-vw-examined-tag" title="Examined">
                            <ClipboardCheck className="s1-vw-ico" aria-label="Examined" />
                          </span>
                        ) : null}
                      </button>
                    </td>
                    {share ? <td className="s1-vw-num">{formatWholePercent(consolidatedShare(line, facility) ?? 1)}</td> : null}
                    <td className="s1-vw-num">{facReported === null ? "" : formatTonnes(facReported)}</td>
                    <td className="s1-vw-num">{facRecomputed === null ? "not tested" : formatTonnes(facRecomputed)}</td>
                    <td className="s1-vw-num">
                      <Delta value={diff} />
                    </td>
                  </tr>
                  {open ? (
                    <tr className="s1-vw-cardrow">
                      <td colSpan={columns}>
                        <CalculationCard
                          line={line}
                          facility={facility}
                          examination={store.examinations[examinationKey(line.id, facility.facilityId)]}
                          examined={examined}
                          store={store}
                          team={team}
                          signedInLogin={signedInLogin}
                          source={source}
                          onOpenSource={onOpenSource}
                          onRegisterFinding={registerFinding}
                        />
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              );
            })}
            <tr className="s1-vw-total">
              <td>{line.activity}</td>
              <td>Total</td>
              {share ? <td /> : null}
              <td className="s1-vw-num">{reportedNote ? <span className="s1-muted">{reportedNote}</span> : formatTonnes(reported)}</td>
              <td className="s1-vw-num">{recomputed === null ? "" : formatTonnes(recomputed)}</td>
              <td className="s1-vw-num">
                <Delta value={difference} material={material} />
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}

const SOURCE_ICON: Record<SourceRef["kind"], LucideIcon> = {
  workbook: FileSpreadsheet,
  records: Files,
  document: FileText,
  reference: BookOpen,
  basis: Info,
  evidence: Files,
};

function Cell({
  cell,
  source,
  onOpenSource,
}: {
  cell: CalcCell;
  source: SourceRef | null;
  onOpenSource: (source: SourceRef) => void;
}) {
  if (!cell.source) return <>{cell.text}</>;
  const target = cell.source;
  const Icon = SOURCE_ICON[target.kind];
  return (
    <button
      className={`s1-vw-input${target === source ? " is-active" : ""}`}
      type="button"
      aria-pressed={target === source}
      onClick={() => onOpenSource(target)}
    >
      <Icon className="s1-vw-ico" aria-hidden />
      {cell.text}
    </button>
  );
}

function StepRow({
  step,
  difference,
  className,
  source,
  onOpenSource,
}: {
  step: CalcStep;
  /** Shown beside Recomputed on the row the panel's total is taken from. */
  difference: number | null;
  className?: string;
  source: SourceRef | null;
  onOpenSource: (source: SourceRef) => void;
}) {
  return (
    <tr className={className ?? (step.total ? "s1-vw-steps__total" : undefined)}>
      <td>{step.step}</td>
      <td>
        {step.how.map((cell, i) => (
          <Cell key={i} cell={cell} source={source} onOpenSource={onOpenSource} />
        ))}
      </td>
      <td className="s1-vw-num">{step.reported ? <Cell cell={step.reported} source={source} onOpenSource={onOpenSource} /> : null}</td>
      <td className="s1-vw-num">
        {step.recomputed ? <Cell cell={step.recomputed} source={source} onOpenSource={onOpenSource} /> : null}
        {differs(difference) ? <span className="s1-vw-red"> ({formatSignedTonnes(difference ?? 0)})</span> : null}
      </td>
    </tr>
  );
}

/**
 * The card's last row, after Total: the facility's total times its consolidated share.
 * The facility's row in the panel, and so the panel's Total, take their values from it.
 */
function consolidatedStep(line: ResultLine, facility: FacilityResult): CalcStep | null {
  const share = consolidatedShare(line, facility);
  if (share === null) return null;
  const reported = facilityReported(line, facility);
  const recomputed = facilityRecomputed(line, facility);
  return {
    step: "Consolidated",
    how: [{ text: `Total × ${formatWholePercent(share)} consolidated share` }],
    reported: reported === null ? null : { text: `${formatTonnes(reported)} tCO₂e` },
    recomputed: recomputed === null ? null : { text: `${formatTonnes(recomputed)} tCO₂e` },
    total: true,
  };
}

function CalculationCard({
  line,
  facility,
  examination,
  examined,
  store,
  team,
  signedInLogin,
  source,
  onOpenSource,
  onRegisterFinding,
}: {
  line: ResultLine;
  facility: FacilityResult;
  examination: Examination | undefined;
  examined: boolean;
  store: VerificationStore;
  team: TeamMember[];
  signedInLogin?: string;
  source: SourceRef | null;
  onOpenSource: (source: SourceRef) => void;
  /** Live results: register a finding on the card's line. */
  onRegisterFinding?: () => void;
}) {
  const [box, setBox] = useState<"examination" | "note" | null>(null);
  const key = examinationKey(line.id, facility.facilityId);
  const title = `${facility.facility} · ${line.activity}`;
  const difference = facilityDifference(line, facility);
  const different = differs(difference);
  const consolidated = consolidatedStep(line, facility);
  // Live results: with no reported value to differ from, the cause is a note or something to review.
  const CauseIcon = facility.causeTone
    ? facility.causeTone === "review"
      ? TriangleAlert
      : Info
    : different
      ? TriangleAlert
      : CircleCheck;

  return (
    <div className="s1-vw-card">
      <h3 className="s1-vw-card__title">{title}</h3>
      {facility.steps.length ? (
        <div className="s1-vw-scroll">
          <table className="s1-vw-steps">
            <thead>
              <tr>
                <th>Step</th>
                <th>How</th>
                <th className="s1-vw-num">Reported</th>
                <th className="s1-vw-num">Recomputed</th>
              </tr>
            </thead>
            <tbody>
              {facility.steps.map((step, i) => (
                <StepRow
                  key={i}
                  step={step}
                  difference={step.total && !consolidated ? difference : null}
                  source={source}
                  onOpenSource={onOpenSource}
                />
              ))}
              {consolidated ? (
                <StepRow
                  step={consolidated}
                  difference={difference}
                  className="s1-vw-steps__total s1-vw-steps__share"
                  source={source}
                  onOpenSource={onOpenSource}
                />
              ) : null}
            </tbody>
          </table>
        </div>
      ) : null}
      {facility.note ? (
        <p className="s1-vw-card__note">
          <Info className="s1-vw-ico" aria-hidden />
          {facility.note}
        </p>
      ) : null}
      {facility.cause ? (
        <p className={`s1-vw-cause${causeClass(facility, different)}`}>
          <CauseIcon className="s1-vw-ico s1-vw-cause__icon" aria-hidden />
          <span>
            {facility.causeBy === "system" ? (
              <>
                <span className="s1-vw-by">
                  <Cpu className="s1-vw-ico" aria-hidden />
                  Checked by system
                </span>{" "}
              </>
            ) : null}
            {facility.cause}
          </span>
        </p>
      ) : null}
      <div className="s1-vw-actions">
        <button
          className={`s1-button s1-vw-action${examined ? " is-done" : ""}`}
          type="button"
          aria-expanded={box === "examination"}
          onClick={() => setBox(box === "examination" ? null : "examination")}
        >
          <ClipboardCheck className="s1-vw-ico" aria-hidden />
          Record examination
        </button>
        <button
          className="s1-button s1-vw-action"
          type="button"
          aria-expanded={box === "note"}
          onClick={() => setBox(box === "note" ? null : "note")}
        >
          <StickyNote className="s1-vw-ico" aria-hidden />
          Add notes
        </button>
        {onRegisterFinding ? (
          <button className="s1-button s1-vw-action" type="button" onClick={onRegisterFinding}>
            <Flag className="s1-vw-ico" aria-hidden />
            Register finding
          </button>
        ) : null}
        {examined && examination?.examinedBy ? (
          <span className="s1-vw-examined-by">
            <Check className="s1-vw-ico" aria-hidden />
            Examined by {examination.examinedBy}
          </span>
        ) : null}
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
      {examination?.notes?.length ? (
        <div className="s1-vw-notes">
          <div className="s1-vw-label">Notes</div>
          <ul>
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
        </div>
      ) : null}
    </div>
  );
}

function causeClass(facility: FacilityResult, different: boolean): string {
  if (facility.causeTone === "review") return " s1-vw-cause--differs";
  if (facility.causeTone === "note") return " s1-vw-cause--note";
  return different ? " s1-vw-cause--differs" : " s1-vw-cause--agrees";
}

function initials(name: string): string {
  return name
    .split(/[\s.]+/)
    .filter(Boolean)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

function RecordExamination({
  title,
  examination,
  team,
  signedInLogin,
  onCancel,
  onSave,
  onClear,
}: {
  title: string;
  /** The stored examination, when the facility row is already examined. */
  examination: Examination | undefined;
  team: TeamMember[];
  signedInLogin?: string;
  onCancel: () => void;
  onSave: (examiner: { name: string; login?: string }, note: string) => void;
  onClear: () => void;
}) {
  const initial = examination?.examinedByLogin ?? (examination?.examinedBy ? undefined : signedInLogin);
  const [login, setLogin] = useState<string | undefined>(
    initial ?? team.find((m) => m.name === examination?.examinedBy)?.login
  );
  const [note, setNote] = useState(examination?.note ?? "");
  const examiner = team.find((m) => m.login === login);

  return (
    <div className="s1-vw-box-form" role="group" aria-label={`Record examination · ${title}`}>
      <div className="s1-vw-label">Record examination · {title}</div>
      {examination?.examinedBy ? (
        <p className="s1-vw-stored">
          <CircleCheck className="s1-vw-ico" aria-hidden />
          Examined by {examination.examinedBy}
          {examination.examinedAt ? `, ${formatWhen(examination.examinedAt)}` : ""}.
        </p>
      ) : null}
      <div className="s1-vw-field">
        <span>
          Examined by <span className="s1-muted">(required)</span>
        </span>
        <div className="s1-vw-chips">
          {team.map((member) => (
            <button
              key={member.login}
              className={`s1-vw-chip${member.login === login ? " is-on" : ""}`}
              type="button"
              aria-pressed={member.login === login}
              onClick={() => setLogin(member.login)}
            >
              <span className="s1-vw-avatar" aria-hidden>
                {initials(member.name)}
              </span>
              {member.name}
            </button>
          ))}
        </div>
        {team.length === 0 ? <p className="s1-muted">Add the engagement team in Setup to record who examined this.</p> : null}
      </div>
      <label className="s1-vw-field">
        <span>
          Note <span className="s1-muted">(optional)</span>
        </span>
        <textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
      </label>
      <div className="s1-vw-form-actions">
        {examination?.examinedBy ? (
          <button className="s1-linklike s1-vw-clear" type="button" onClick={onClear}>
            Clear examination
          </button>
        ) : null}
        <button className="s1-button" type="button" onClick={onCancel}>
          Cancel
        </button>
        <button
          className="s1-button s1-button--pri"
          type="button"
          disabled={!examiner}
          onClick={() => examiner && onSave({ name: examiner.name, login: examiner.login }, note)}
        >
          Save
        </button>
      </div>
      <p className="s1-muted s1-vw-help">Saves examiner, date and time to the facility row. The Examined count on the left updates.</p>
    </div>
  );
}

function AddNote({ title, onCancel, onSave }: { title: string; onCancel: () => void; onSave: (text: string) => void }) {
  const [text, setText] = useState("");
  return (
    <div className="s1-vw-box-form" role="group" aria-label={`Add notes · ${title}`}>
      <div className="s1-vw-label">Add notes · {title}</div>
      <label className="s1-vw-field">
        <span>
          Note <span className="s1-muted">(required)</span>
        </span>
        <textarea rows={2} value={text} onChange={(e) => setText(e.target.value)} />
      </label>
      <div className="s1-vw-form-actions">
        <button className="s1-button" type="button" onClick={onCancel}>
          Cancel
        </button>
        <button className="s1-button s1-button--pri" type="button" disabled={!text.trim()} onClick={() => onSave(text)}>
          Save
        </button>
      </div>
      <p className="s1-muted s1-vw-help">Notes do not count as examination and are not evidence.</p>
    </div>
  );
}

function formatWhen(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });
}
