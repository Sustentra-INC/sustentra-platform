"use client";

import {
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  Check,
  ChevronDown,
  ChevronRight,
  CircleCheck,
  ClipboardCheck,
  FileSpreadsheet,
  FileText,
  Files,
  Flame,
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
import type { CalcCell, CalcStep, FacilityResult, ResultBoxKey, ResultLine, SourceRef } from "../types/verificationResults";
import {
  buildResultBoxes,
  differs,
  examinationKey,
  formatPercent,
  formatSignedTonnes,
  formatTonnes,
  formatWholePercent,
  lineRecomputed,
  lineReported,
  type ResultBox,
  type ResultRow,
} from "../utils/verificationTable";
import type { VerificationStore } from "../verification/verificationStore";
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
}: {
  lines: ResultLine[];
  store: VerificationStore;
  /** "Examined by" options: the engagement team from Setup. */
  team: TeamMember[];
  signedInLogin?: string;
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [source, setSource] = useState<SourceRef | null>(null);
  const [openBoxes, setOpenBoxes] = useState<Set<ResultBoxKey>>(() => new Set<ResultBoxKey>(["scope1"]));
  const isExamined = (lineId: string, facilityId: string) =>
    Boolean(store.examinations[examinationKey(lineId, facilityId)]?.examinedBy);
  const boxes = useMemo(
    () =>
      buildResultBoxes(lines, (lineId, facilityId) =>
        Boolean(store.examinations[examinationKey(lineId, facilityId)]?.examinedBy)
      ),
    [lines, store.examinations]
  );
  const selected = lines.find((line) => line.id === selectedId) ?? null;

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
      if (event.key === "Escape") {
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
      <Differences boxes={boxes} selectedId={selectedId} onSelect={select} />
      <section className="s1-vw-boxes" aria-label="Reported vs recomputed">
        {boxes.map((box) => (
          <BoxPanel
            key={box.key}
            box={box}
            open={openBoxes.has(box.key)}
            onToggle={() => toggleBox(box.key)}
            selectedId={selectedId}
            onSelect={select}
          />
        ))}
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
              />
            </section>
            <section ref={sourcePane} className="s1-vw-pane s1-vw-pane--source" aria-label="Source">
              <h2 className="s1-vw-pane__title">Source</h2>
              <VerificationSource source={source} />
            </section>
          </div>
        </aside>
      ) : null}
    </div>
  );
}

/* ============================ differences strip ============================ */

/** Every line where reported and recomputed differ, largest % material first. */
function Differences({
  boxes,
  selectedId,
  onSelect,
}: {
  boxes: ResultBox[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const differing = boxes
    .flatMap((box) => box.rows.filter((row) => differs(row.difference)).map((row) => ({ box, row })))
    .sort((a, b) => Math.abs(b.row.pctMaterial ?? 0) - Math.abs(a.row.pctMaterial ?? 0));
  if (!differing.length) {
    return (
      <p className="s1-vw-strip s1-vw-strip--clear">
        <CircleCheck className="s1-vw-ico" aria-hidden /> Every recomputed line agrees with what was reported.
      </p>
    );
  }
  return (
    <section className="s1-vw-strip" aria-label="Where reported and recomputed differ">
      <div className="s1-vw-strip__head">
        <TriangleAlert className="s1-vw-ico" aria-hidden />
        <span>
          <strong>{differing.length}</strong> {differing.length === 1 ? "line differs" : "lines differ"} from what was reported.
          Open one to trace the cause.
        </span>
      </div>
      <ul className="s1-vw-strip__list">
        {differing.map(({ box, row }) => {
          const Icon = BOX_ICON[box.key];
          return (
            <li key={row.key}>
              <button
                className={`s1-vw-chipbtn s1-vw-tone--${box.key}${row.key === selectedId ? " is-on" : ""}`}
                type="button"
                aria-pressed={row.key === selectedId}
                onClick={() => onSelect(row.key)}
              >
                <span className="s1-vw-chipbtn__icon">
                  <Icon className="s1-vw-ico" aria-hidden />
                </span>
                <span className="s1-vw-chipbtn__text">
                  <span className="s1-vw-chipbtn__name">{row.activity}</span>
                  <span className="s1-vw-chipbtn__where">{box.title}</span>
                </span>
                <Delta value={row.difference} />
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/* ================================== boxes ================================== */

/** A difference as a badge: an arrow and the signed tonnes, or a quiet 0. */
function Delta({ value, suffix = "" }: { value: number | null; suffix?: string }) {
  if (value === null) return null;
  if (!differs(value)) return <span className="s1-vw-delta s1-vw-delta--zero">0{suffix}</span>;
  const Arrow = value > 0 ? ArrowUpRight : ArrowDownRight;
  return (
    <span className="s1-vw-delta">
      <Arrow className="s1-vw-ico" aria-hidden />
      {formatSignedTonnes(value)}
      {suffix}
    </span>
  );
}

function BoxPanel({
  box,
  open,
  onToggle,
  selectedId,
  onSelect,
}: {
  box: ResultBox;
  open: boolean;
  onToggle: () => void;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const Icon = BOX_ICON[box.key];
  const { totals } = box;
  const reportedRows = box.rows.filter((r) => !r.notReported);
  const differing = reportedRows.filter((r) => differs(r.difference)).length;
  const bodyId = `s1-vw-box-${box.key}`;
  return (
    <div className={`s1-vw-box s1-vw-tone--${box.key}${open ? " is-open" : ""}`}>
      <button className="s1-vw-box__head" type="button" aria-expanded={open} aria-controls={bodyId} onClick={onToggle}>
        <span className="s1-vw-box__icon">
          <Icon className="s1-vw-ico" aria-hidden />
        </span>
        <span className="s1-vw-box__name">
          <span className="s1-vw-box__title">{box.title}</span>
          <span className="s1-vw-box__sub">
            {box.key === "biogenic"
              ? "Outside scopes · not added to any total"
              : `${reportedRows.length} reported ${reportedRows.length === 1 ? "line" : "lines"} · ${
                  differing ? `${differing} differ` : "all agree"
                }`}
          </span>
        </span>
        <span className="s1-vw-box__figures">
          <span className="s1-vw-fig">
            <span className="s1-vw-fig__label">Reported</span>
            <span className="s1-vw-fig__value">{formatTonnes(totals.reported)}</span>
          </span>
          <ArrowRight className="s1-vw-ico s1-vw-fig__arrow" aria-hidden />
          <span className="s1-vw-fig">
            <span className="s1-vw-fig__label">Recomputed</span>
            <span className="s1-vw-fig__value">{formatTonnes(totals.recomputed)}</span>
          </span>
          <Delta value={totals.difference} />
          <span className={`s1-vw-pill${differs(totals.difference) ? " s1-vw-pill--differs" : " s1-vw-pill--agrees"}`}>
            {formatPercent(totals.pctMaterial, true)} material
          </span>
          <span className="s1-vw-box__meta">
            <ClipboardCheck className="s1-vw-ico" aria-hidden />
            {totals.examined}/{totals.facilities}
          </span>
        </span>
        <ChevronDown className="s1-vw-ico s1-vw-box__chev" aria-hidden />
      </button>
      {open ? (
        <div className="s1-vw-box__body" id={bodyId}>
          <BoxTable box={box} selectedId={selectedId} onSelect={onSelect} />
          <div className="s1-vw-box__lines">
            <span>Coverage: {formatWholePercent(totals.share)}</span>
            <span>
              Total % material:{" "}
              <span className={differs(totals.difference) ? "s1-vw-red" : undefined}>
                {formatPercent(totals.pctMaterial, true)}
              </span>
            </span>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function BoxTable({ box, selectedId, onSelect }: { box: ResultBox; selectedId: string | null; onSelect: (id: string) => void }) {
  const scope1 = box.key === "scope1";
  const { totals } = box;
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
              <ReportedRow key={row.key} row={row} scope1={scope1} selected={row.key === selectedId} onSelect={onSelect} />
            )
          )}
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
}: {
  row: ResultRow;
  scope1: boolean;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  const select = () => onSelect(row.key);
  const name = (
    <button className="s1-vw-rowbtn" type="button" aria-pressed={selected} onClick={select}>
      {row.activity}
      <ChevronRight className="s1-vw-ico s1-vw-rowbtn__go" aria-hidden />
    </button>
  );
  const allExamined = row.facilities > 0 && row.examined === row.facilities;
  return (
    <tr className={`s1-vw-row${selected ? " is-selected" : ""}${differs(row.difference) ? " is-different" : ""}`} onClick={select}>
      {scope1 ? (
        <>
          <td className="s1-vw-category">
            {row.categoryLabel ? (
              <span className={`s1-vw-cat s1-vw-cat--${row.categoryLabel.split(" ")[0].toLowerCase()}`}>{row.categoryLabel}</span>
            ) : null}
          </td>
          <td className="s1-vw-name">{name}</td>
        </>
      ) : (
        <td className="s1-vw-name">{name}</td>
      )}
      <td className="s1-vw-num">{row.reported === null ? "" : formatTonnes(row.reported)}</td>
      {row.notTested ? (
        <>
          <td className="s1-vw-num s1-muted">not tested</td>
          <td colSpan={3} />
        </>
      ) : (
        <>
          <td className="s1-vw-num">{row.recomputed === null ? "" : formatTonnes(row.recomputed)}</td>
          <td className="s1-vw-num">
            <Delta value={row.difference} />
          </td>
          <td className="s1-vw-num">{row.pctDifference === null ? "" : formatPercent(row.pctDifference, true)}</td>
          <td className={`s1-vw-num${differs(row.difference) ? " s1-vw-red" : ""}`}>
            {row.pctMaterial === null ? "" : formatPercent(row.pctMaterial, true)}
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

/* ============================ calculation panel ============================ */

function nameColumn(line: ResultLine): string {
  if (line.box !== "scope1") return "Data point";
  return line.category === "Fugitive emissions" ? "Refrigerant" : "Fuel";
}

function facilityDifference(facility: FacilityResult): number | null {
  return facility.recomputed === null || facility.reported === null ? null : facility.recomputed - facility.reported;
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
}: {
  line: ResultLine;
  store: VerificationStore;
  team: TeamMember[];
  signedInLogin?: string;
  isExamined: (lineId: string, facilityId: string) => boolean;
  source: SourceRef | null;
  onOpenSource: (source: SourceRef) => void;
  onClose: () => void;
}) {
  const facilities = line.facilities ?? [];
  // The facility that explains the difference opens first; with none, the first one.
  const [openId, setOpenId] = useState<string | null>(
    () => (facilities.find((f) => differs(facilityDifference(f))) ?? facilities[0])?.facilityId ?? null
  );
  const reported = lineReported(line) ?? 0;
  const recomputed = lineRecomputed(line);
  const difference = recomputed === null ? null : recomputed - reported;
  const crumbs = [BOX_CRUMB[line.box], line.category, line.activity].filter(Boolean) as string[];
  const Icon = BOX_ICON[line.box];

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
              Reported <strong>{formatTonnes(reported)}</strong>
            </span>
            <span>
              Recomputed <strong>{recomputed === null ? "not tested" : formatTonnes(recomputed)}</strong>
            </span>
            {difference === null ? null : (
              <span>
                Difference <strong className={differs(difference) ? "s1-vw-red" : undefined}>{formatSignedTonnes(difference)}</strong>
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
              const diff = facilityDifference(facility);
              const examined = isExamined(line.id, facility.facilityId);
              return (
                <Fragment key={facility.facilityId}>
                  <tr
                    className={`s1-vw-row${differs(diff) ? " is-different" : ""}${open ? " is-open" : ""}`}
                    onClick={() => setOpenId(open ? null : facility.facilityId)}
                  >
                    <td>{line.activity}</td>
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
                    <td className="s1-vw-num">{facility.reported === null ? "" : formatTonnes(facility.reported)}</td>
                    <td className="s1-vw-num">{facility.recomputed === null ? "not tested" : formatTonnes(facility.recomputed)}</td>
                    <td className="s1-vw-num">
                      <Delta value={diff} />
                    </td>
                  </tr>
                  {open ? (
                    <tr className="s1-vw-cardrow">
                      <td colSpan={5}>
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
              <td className="s1-vw-num">{formatTonnes(reported)}</td>
              <td className="s1-vw-num">{recomputed === null ? "" : formatTonnes(recomputed)}</td>
              <td className="s1-vw-num">
                <Delta value={difference} />
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
  facility,
  source,
  onOpenSource,
}: {
  step: CalcStep;
  facility: FacilityResult;
  source: SourceRef | null;
  onOpenSource: (source: SourceRef) => void;
}) {
  const diff = facilityDifference(facility);
  return (
    <tr className={step.total ? "s1-vw-steps__total" : undefined}>
      <td>{step.step}</td>
      <td>
        {step.how.map((cell, i) => (
          <Cell key={i} cell={cell} source={source} onOpenSource={onOpenSource} />
        ))}
      </td>
      <td className="s1-vw-num">{step.reported ? <Cell cell={step.reported} source={source} onOpenSource={onOpenSource} /> : null}</td>
      <td className="s1-vw-num">
        {step.recomputed ? <Cell cell={step.recomputed} source={source} onOpenSource={onOpenSource} /> : null}
        {step.total && differs(diff) ? <span className="s1-vw-red"> ({formatSignedTonnes(diff ?? 0)})</span> : null}
      </td>
    </tr>
  );
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
}) {
  const [box, setBox] = useState<"examination" | "note" | null>(null);
  const key = examinationKey(line.id, facility.facilityId);
  const title = `${facility.facility} · ${line.activity}`;
  const different = differs(facilityDifference(facility));
  const CauseIcon = different ? TriangleAlert : CircleCheck;

  return (
    <div className="s1-vw-card">
      <h3 className="s1-vw-card__title">{title}</h3>
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
              <StepRow key={i} step={step} facility={facility} source={source} onOpenSource={onOpenSource} />
            ))}
          </tbody>
        </table>
      </div>
      <p className={`s1-vw-cause${different ? " s1-vw-cause--differs" : " s1-vw-cause--agrees"}`}>
        <CauseIcon className="s1-vw-ico s1-vw-cause__icon" aria-hidden />
        <span>{facility.cause}</span>
      </p>
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
