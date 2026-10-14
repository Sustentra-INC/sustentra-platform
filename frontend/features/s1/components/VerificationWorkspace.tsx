"use client";

import { Fragment, useEffect, useMemo, useRef, useState } from "react";

import type { TeamMember } from "../types/engagement";
import type { Examination } from "../types/verification";
import type { CalcCell, CalcStep, FacilityResult, ResultLine, SourceRef } from "../types/verificationResults";
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
 * Verification results: Reported vs recomputed (left), the Calculation behind the
 * selected line by facility (middle), and the Source of an underlined input (right).
 * Click a row on the left to load its calculation; click an underlined input to open
 * its document.
 */
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
  const isExamined = (lineId: string, facilityId: string) =>
    Boolean(store.examinations[examinationKey(lineId, facilityId)]?.examinedBy);
  const boxes = useMemo(
    () => buildResultBoxes(lines, (lineId, facilityId) => Boolean(store.examinations[examinationKey(lineId, facilityId)]?.examinedBy)),
    [lines, store.examinations]
  );
  const selected = lines.find((line) => line.id === selectedId) ?? null;
  // Where the Source pane stacks under Calculation (laptop widths), bring an opened document into view.
  const sourcePane = useRef<HTMLElement | null>(null);
  useEffect(() => {
    if (source) sourcePane.current?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
  }, [source]);

  return (
    <div className="s1-vw">
      <section className="s1-vw-pane s1-vw-pane--table" aria-label="Reported vs recomputed">
        <h2 className="s1-vw-pane__title">Reported vs recomputed</h2>
        {boxes.map((box) => (
          <BoxTable
            key={box.key}
            box={box}
            selectedId={selectedId}
            onSelect={(id) => {
              if (id === selectedId) return;
              setSelectedId(id);
              setSource(null);
            }}
          />
        ))}
      </section>
      <section className="s1-vw-pane s1-vw-pane--calc" aria-label="Calculation">
        {selected ? (
          <CalculationPane
            key={selected.id}
            line={selected}
            store={store}
            team={team}
            signedInLogin={signedInLogin}
            isExamined={isExamined}
            onOpenSource={setSource}
          />
        ) : (
          <div className="s1-vw-empty">
            <h2 className="s1-vw-pane__title">Calculation</h2>
            <p className="s1-muted">Select a row in Reported vs recomputed to see its calculation by facility.</p>
          </div>
        )}
      </section>
      <section ref={sourcePane} className="s1-vw-pane s1-vw-pane--source" aria-label="Source">
        <h2 className="s1-vw-pane__title">Source</h2>
        <VerificationSource source={source} />
      </section>
    </div>
  );
}

/* ================================ left pane ================================ */

function BoxTable({ box, selectedId, onSelect }: { box: ResultBox; selectedId: string | null; onSelect: (id: string) => void }) {
  const scope1 = box.key === "scope1";
  const { totals } = box;
  const span = scope1 ? 2 : 1;
  return (
    <div className="s1-vw-box">
      <h3 className="s1-vw-box__title">
        {box.title}
        {box.key === "biogenic" ? <span className="s1-muted"> outside scopes · not added to any total</span> : null}
      </h3>
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
              <DiffCell value={totals.difference} text={formatSignedTonnes(totals.difference)} />
              <td className="s1-vw-num">{totals.pctDifference === null ? "" : formatPercent(totals.pctDifference, true)}</td>
              <DiffCell value={totals.difference} text={formatPercent(totals.pctMaterial, true)} />
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
      <div className="s1-vw-box__lines">
        <span>Coverage: {formatWholePercent(totals.share)}</span>
        <span>
          Total % material:{" "}
          <span className={differs(totals.difference) ? "s1-vw-red" : undefined}>{formatPercent(totals.pctMaterial, true)}</span>
        </span>
      </div>
    </div>
  );
}

function DiffCell({ value, text }: { value: number | null; text: string }) {
  return <td className={`s1-vw-num${differs(value) ? " s1-vw-diff" : ""}`}>{text}</td>;
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
    </button>
  );
  return (
    <tr className={`s1-vw-row${selected ? " is-selected" : ""}`} onClick={select}>
      {scope1 ? (
        <>
          <td className="s1-vw-category">{row.categoryLabel ?? ""}</td>
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
          <DiffCell value={row.difference} text={row.difference === null ? "" : formatSignedTonnes(row.difference)} />
          <td className="s1-vw-num">{row.pctDifference === null ? "" : formatPercent(row.pctDifference, true)}</td>
          <DiffCell value={row.difference} text={row.pctMaterial === null ? "" : formatPercent(row.pctMaterial, true)} />
        </>
      )}
      <td className="s1-vw-num">{row.share === null ? "" : formatPercent(row.share)}</td>
      <td className="s1-vw-num s1-vw-examined">
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

/* =============================== middle pane =============================== */

const BOX_CRUMB: Record<ResultLine["box"], string> = {
  scope1: "Scope 1",
  scope2_location: "Scope 2, location-based",
  scope2_market: "Scope 2, market-based",
  biogenic: "Biogenic CO₂",
};

function nameColumn(line: ResultLine): string {
  if (line.box !== "scope1") return "Data point";
  return line.category === "Fugitive emissions" ? "Refrigerant" : "Fuel";
}

function CalculationPane({
  line,
  store,
  team,
  signedInLogin,
  isExamined,
  onOpenSource,
}: {
  line: ResultLine;
  store: VerificationStore;
  team: TeamMember[];
  signedInLogin?: string;
  isExamined: (lineId: string, facilityId: string) => boolean;
  onOpenSource: (source: SourceRef) => void;
}) {
  const [openId, setOpenId] = useState<string | null>(null);
  const facilities = line.facilities ?? [];
  const reported = lineReported(line) ?? 0;
  const recomputed = lineRecomputed(line);
  const difference = recomputed === null ? null : recomputed - reported;
  const crumbs = [BOX_CRUMB[line.box], line.category, line.activity].filter(Boolean) as string[];

  return (
    <div className="s1-vw-calc">
      <header className="s1-vw-calc__head">
        <h2 className="s1-vw-crumb">
          {crumbs.map((crumb, i) => (
            <Fragment key={crumb}>
              {i ? <span className="s1-vw-crumb__sep"> › </span> : null}
              {crumb}
            </Fragment>
          ))}
        </h2>
        <p className="s1-vw-summary">
          Reported {formatTonnes(reported)} · Recomputed {recomputed === null ? "not tested" : formatTonnes(recomputed)}
          {difference === null ? null : (
            <>
              {" "}
              · Difference <span className={differs(difference) ? "s1-vw-red" : undefined}>{formatSignedTonnes(difference)}</span>
            </>
          )}
        </p>
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
              const diff = facility.recomputed === null || facility.reported === null ? null : facility.recomputed - facility.reported;
              return (
                <Fragment key={facility.facilityId}>
                  <tr className={`s1-vw-row${differs(diff) ? " is-different" : ""}${open ? " is-open" : ""}`}>
                    <td>{line.activity}</td>
                    <td>
                      <button
                        className="s1-vw-rowbtn s1-vw-facility"
                        type="button"
                        aria-expanded={open}
                        onClick={() => setOpenId(open ? null : facility.facilityId)}
                      >
                        <span className="s1-vw-caret" aria-hidden>
                          {open ? "▾" : "▸"}
                        </span>
                        {facility.facility}
                      </button>
                    </td>
                    <td className="s1-vw-num">{facility.reported === null ? "" : formatTonnes(facility.reported)}</td>
                    <td className="s1-vw-num">{facility.recomputed === null ? "not tested" : formatTonnes(facility.recomputed)}</td>
                    <td className={`s1-vw-num${differs(diff) ? " s1-vw-red" : ""}`}>{diff === null ? "" : formatSignedTonnes(diff)}</td>
                  </tr>
                  {open ? (
                    <tr className="s1-vw-cardrow">
                      <td colSpan={5}>
                        <CalculationCard
                          line={line}
                          facility={facility}
                          examination={store.examinations[examinationKey(line.id, facility.facilityId)]}
                          examined={isExamined(line.id, facility.facilityId)}
                          store={store}
                          team={team}
                          signedInLogin={signedInLogin}
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
              <td className={`s1-vw-num${differs(difference) ? " s1-vw-red" : ""}`}>
                {difference === null ? "" : formatSignedTonnes(difference)}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Cell({ cell, onOpenSource }: { cell: CalcCell; onOpenSource: (source: SourceRef) => void }) {
  if (!cell.source) return <>{cell.text}</>;
  const source = cell.source;
  return (
    <button className="s1-vw-input" type="button" onClick={() => onOpenSource(source)}>
      {cell.text}
    </button>
  );
}

function StepRow({ step, facility, onOpenSource }: { step: CalcStep; facility: FacilityResult; onOpenSource: (source: SourceRef) => void }) {
  const diff = facility.recomputed === null || facility.reported === null ? null : facility.recomputed - facility.reported;
  return (
    <tr className={step.total ? "s1-vw-steps__total" : undefined}>
      <td>{step.step}</td>
      <td>
        {step.how.map((cell, i) => (
          <Cell key={i} cell={cell} onOpenSource={onOpenSource} />
        ))}
      </td>
      <td className="s1-vw-num">{step.reported ? <Cell cell={step.reported} onOpenSource={onOpenSource} /> : null}</td>
      <td className="s1-vw-num">
        {step.recomputed ? <Cell cell={step.recomputed} onOpenSource={onOpenSource} /> : null}
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
  onOpenSource,
}: {
  line: ResultLine;
  facility: FacilityResult;
  examination: Examination | undefined;
  examined: boolean;
  store: VerificationStore;
  team: TeamMember[];
  signedInLogin?: string;
  onOpenSource: (source: SourceRef) => void;
}) {
  const [box, setBox] = useState<"examination" | "note" | null>(null);
  const key = examinationKey(line.id, facility.facilityId);
  const title = `${facility.facility} · ${line.activity}`;

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
              <StepRow key={i} step={step} facility={facility} onOpenSource={onOpenSource} />
            ))}
          </tbody>
        </table>
      </div>
      <p className="s1-vw-cause">{facility.cause}</p>
      <div className="s1-vw-actions">
        <button className="s1-button" type="button" aria-expanded={box === "examination"} onClick={() => setBox(box === "examination" ? null : "examination")}>
          Record examination
        </button>
        <button className="s1-button" type="button" aria-expanded={box === "note"} onClick={() => setBox(box === "note" ? null : "note")}>
          Add notes
        </button>
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
