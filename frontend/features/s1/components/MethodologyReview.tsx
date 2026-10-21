"use client";

import { ChevronRight, TextAlignJustify, Pencil, Plus, SquareDashed } from "lucide-react";
import { Fragment, useState, type Dispatch, type ReactNode, type SetStateAction } from "react";

import {
  BOUNDARY_APPROACHES,
  INCLUSIONS,
  type BoundaryApproach,
  type FactorRow,
  type FactorScope,
  type Inclusion,
  type MethodologyStated,
  type MethodologyState,
  type StatedCategory,
  type StatedText,
} from "../types/methodology";
import {
  acceptEntity,
  addFactor,
  currentApproach,
  currentGwp,
  currentText,
  entityView,
  factorFlagCount,
  factorRows,
  gwpFlag,
  inclusionLabel,
  isYesNo,
  removeFactor,
  revertApproach,
  revertCategory,
  revertFactor,
  revertGwp,
  revertText,
  saveFactor,
  saveGwp,
  saveText,
  setApproach,
  setCategory,
  setEntityValue,
} from "../utils/methodologyReview";
import { InfoTip } from "./InfoTip";

/**
 * Methodology review: the client's stated inventory boundary and methods, for the
 * verifier to accept or correct. Every group folds from its header; a change shows one
 * line under it (who, when, Revert) and goes to the activity log.
 */

const GWP_SETS = ["IPCC Fourth Assessment Report (AR4)", "IPCC Fifth Assessment Report (AR5)", "IPCC Sixth Assessment Report (AR6)"];
const GWP_HORIZONS = ["100-year", "20-year"];

/** What each "Identified by" means, on hover. */
const IDENTIFIED_BY: Record<string, string> = {
  "Stated by company": "Named in the company's GHG report.",
  "Matched by system": "The factors in the company's workbook match this database.",
  "Stated by company, confirmed by system match": "Named in the GHG report, and the workbook's factors match it.",
  "Provided by company": "From a document the company provided.",
};

type GroupKey = "s1" | "s2" | "bio" | "exc" | "ef" | "gwp" | "calc";

type Update = Dispatch<SetStateAction<MethodologyState>>;

export function MethodologyReview({
  stated,
  review,
  onChange,
  verifier,
}: {
  stated: MethodologyStated;
  review: MethodologyState;
  onChange: Update;
  /** The signed-in verifier, named on each change. */
  verifier: string;
}) {
  const [closed, setClosed] = useState<Set<GroupKey>>(() => new Set());
  const who = () => ({ by: verifier, at: new Date().toISOString() });
  const group = (key: GroupKey) => ({
    open: !closed.has(key),
    onToggle: () =>
      setClosed((cur) => {
        const next = new Set(cur);
        if (next.has(key)) next.delete(key);
        else next.add(key);
        return next;
      }),
  });
  const rows = factorRows(stated, review);
  const efFlags = factorFlagCount(rows);
  const gwp = currentGwp(stated, review);

  return (
    <section className="s1-content s1-mr">
      <header className="s1-ws-header">
        <div className="s1-ws-header__id">
          <h1>Methodology review</h1>
          <InfoTip label="Methodology review">
            The boundary and methods the client&rsquo;s GHG report states. Accept or correct each one; every change is recorded.
          </InfoTip>
        </div>
      </header>

      <section className="s1-mr-card" aria-labelledby="s1-mr-boundary">
        <div className="s1-mr-card__head">
          <span className="s1-mr-card__icon s1-mr-card__icon--boundary">
            <SquareDashed aria-hidden />
          </span>
          <h2 id="s1-mr-boundary" className="s1-mr-card__title">
            Inventory Boundary
          </h2>
        </div>
        <div className="s1-mr-card__body">
          <div className="s1-mr-lead">
            <TextField
              field={stated.reportingPeriod}
              review={review}
              single
              onSave={(draft) => onChange((s) => saveText(s, stated.reportingPeriod, draft, who()))}
              onRevert={() => onChange((s) => revertText(s, stated.reportingPeriod, who()))}
            />
            <Boundary stated={stated} review={review} onChange={onChange} who={who} />
          </div>

          <Group title="Scope 1 emission categories" {...group("s1")}>
            <CategoryTable
              heading="Category"
              categories={stated.categories.scope1}
              review={review}
              labelOf={(c) => `Scope 1 ${c.name}`}
              onChange={onChange}
              who={who}
            />
          </Group>

          <Group title="Scope 2 emission categories" {...group("s2")}>
            <div className="s1-mr-split">
              <CategoryTable
                heading="Location-Based"
                categories={stated.categories.location}
                review={review}
                labelOf={(c) => `Location-based ${c.name}`}
                onChange={onChange}
                who={who}
                stacked
              />
              <CategoryTable
                heading="Market-Based"
                categories={stated.categories.market}
                review={review}
                labelOf={(c) => `Market-based ${c.name}`}
                onChange={onChange}
                who={who}
                stacked
              />
            </div>
          </Group>

          <Group title="Biogenic emissions" {...group("bio")}>
            <CategoryTable
              heading="Type"
              categories={stated.categories.biogenic}
              review={review}
              labelOf={(c) => c.name}
              onChange={onChange}
              who={who}
            />
          </Group>

          <Group title="Exclusions" {...group("exc")}>
            <TextRows fields={stated.exclusions} review={review} onChange={onChange} who={who} />
          </Group>
        </div>
      </section>

      <section className="s1-mr-card" aria-labelledby="s1-mr-methods">
        <div className="s1-mr-card__head">
          <span className="s1-mr-card__icon s1-mr-card__icon--methods">
            <TextAlignJustify aria-hidden />
          </span>
          <h2 id="s1-mr-methods" className="s1-mr-card__title">
            Methods
          </h2>
        </div>
        <div className="s1-mr-card__body">
          <Group title="Emission factors source" flags={efFlags} {...group("ef")}>
            <div className="s1-mr-boxes">
              {(["scope1", "scope2"] as const).map((scope) => (
                <FactorBox key={scope} scope={scope} rows={rows[scope]} stated={stated} onChange={onChange} who={who} />
              ))}
            </div>
          </Group>

          <Group title="GWP factors source" flags={gwpFlag(gwp.horizon) ? 1 : 0} {...group("gwp")}>
            <GwpTable stated={stated} review={review} onChange={onChange} who={who} />
          </Group>

          <Group title="Calculation methodology" {...group("calc")}>
            <TextRows fields={stated.calculation} review={review} onChange={onChange} who={who} rows={4} />
          </Group>
        </div>
      </section>
    </section>
  );
}

type Who = () => { by: string; at: string };

/* ================================ building blocks ================================ */

/** A group that folds from its header; the header shows only its open flags. */
function Group({
  title,
  flags = 0,
  open,
  onToggle,
  children,
}: {
  title: string;
  flags?: number;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  return (
    <div className={`s1-mr-group${open ? " is-open" : ""}`}>
      <button className="s1-mr-group__head" type="button" aria-expanded={open} onClick={onToggle}>
        <ChevronRight className="s1-mr-chev" aria-hidden />
        <span className="s1-mr-group__title">{title}</span>
        {flags > 0 ? <span className="s1-mr-flag">{flags === 1 ? "1 flag" : `${flags} flags`}</span> : null}
      </button>
      {open ? <div className="s1-mr-group__body">{children}</div> : null}
    </div>
  );
}

/** The one line under a changed value: who changed it, when, and Revert. */
function Adjusted({ by, at, original, onRevert }: { by: string; at: string; original: string; onRevert: () => void }) {
  return (
    <div className="s1-mr-adjusted">
      <span>
        <Pencil className="s1-mr-ico" aria-hidden /> Adjusted by verifier {by} · {formatWhen(at)}
      </span>
      <button className="s1-mr-link" type="button" onClick={onRevert} title={`Revert to: ${original}`}>
        Revert
      </button>
    </div>
  );
}

function Identified({ by, tip }: { by: string; tip?: string }) {
  return (
    <span className="s1-mr-by" title={tip ?? IDENTIFIED_BY[by]}>
      {by}
    </span>
  );
}

function shorten(text: string): string {
  if (!text) return "Not detected";
  return text.length > 90 ? `${text.slice(0, 90)}…` : text;
}

/* ================================ inventory boundary ================================ */

function Boundary({ stated, review, onChange, who }: { stated: MethodologyStated; review: MethodologyState; onChange: Update; who: Who }) {
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const approach = currentApproach(stated, review);
  const views = stated.entities.map((entity) => ({ entity, view: entityView(entity, approach, review) }));
  const reviewed = views.filter((v) => v.view.reviewed).length;
  const toggle = (id: string) =>
    setExpanded((cur) => {
      const next = new Set(cur);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div className="s1-mr-field">
      <label className="s1-mr-label" htmlFor="s1-mr-approach">
        Organizational boundary approach
      </label>
      <select
        id="s1-mr-approach"
        className="s1-select s1-mr-select s1-mr-select--wide"
        value={approach}
        onChange={(e) => onChange((s) => setApproach(s, stated, e.target.value as BoundaryApproach, who()))}
      >
        {BOUNDARY_APPROACHES.map((a) => (
          <option key={a} value={a}>
            {a}
          </option>
        ))}
      </select>
      {review.approach ? (
        <Adjusted
          by={review.approach.by}
          at={review.approach.at}
          original={stated.approach}
          onRevert={() => onChange((s) => revertApproach(s, stated, who()))}
        />
      ) : null}

      <div className="s1-mr-scroll">
        <table className="s1-mr-table s1-mr-entities">
          <thead>
            <tr>
              <th>Entity</th>
              <th className="s1-mr-col-value">{inclusionLabel(approach)}</th>
              <th className="s1-mr-col-review">
                Review · {reviewed} of {views.length}
              </th>
            </tr>
          </thead>
          <tbody>
            {views.map(({ entity, view }) => {
              const open = expanded.has(entity.id);
              return (
                <Fragment key={entity.id}>
                  <tr>
                    <td>
                      <button className="s1-mr-entity" type="button" aria-expanded={open} onClick={() => toggle(entity.id)}>
                        <ChevronRight className="s1-mr-chev" aria-hidden />
                        {entity.name}
                        <span className="s1-mr-muted">
                          · {entity.facilities.length} {entity.facilities.length === 1 ? "facility" : "facilities"}
                        </span>
                      </button>
                      {view.note ? <div className="s1-mr-note">{view.note}</div> : null}
                    </td>
                    <td>
                      {isYesNo(approach) ? (
                        <select
                          className="s1-select s1-mr-select"
                          value={view.value}
                          aria-label={`Included: ${entity.name}`}
                          onChange={(e) => onChange((s) => setEntityValue(s, view, e.target.value))}
                        >
                          <option value="Yes">Yes</option>
                          <option value="No">No</option>
                        </select>
                      ) : (
                        <span className="s1-mr-pct">
                          <input
                            className="s1-mr-input s1-mr-input--pct"
                            type="number"
                            min={0}
                            max={100}
                            value={view.value}
                            aria-label={`${inclusionLabel(approach)} for ${entity.name}`}
                            onChange={(e) => onChange((s) => setEntityValue(s, view, e.target.value))}
                          />
                          %
                        </span>
                      )}
                    </td>
                    <td>
                      {!view.reviewed ? (
                        <button
                          className="s1-mr-accept"
                          type="button"
                          onClick={() => onChange((s) => acceptEntity(s, entity, view, approach, who()))}
                        >
                          Accept
                        </button>
                      ) : view.corrected ? (
                        <span className="s1-mr-chip s1-mr-chip--corrected">Corrected from {view.originalLabel}</span>
                      ) : (
                        <span className="s1-mr-chip s1-mr-chip--accepted">Accepted</span>
                      )}
                    </td>
                  </tr>
                  {open
                    ? entity.facilities.map((facility) => (
                        <tr key={facility} className="s1-mr-sub">
                          <td>{facility}</td>
                          <td className="s1-mr-muted">Inherits {view.inherits}</td>
                          <td />
                        </tr>
                      ))
                    : null}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function CategoryTable({
  heading,
  categories,
  review,
  labelOf,
  onChange,
  who,
  stacked = false,
}: {
  heading: string;
  categories: StatedCategory[];
  review: MethodologyState;
  labelOf: (category: StatedCategory) => string;
  onChange: Update;
  who: Who;
  /** Scope 2's two columns: the adjusted line goes under the row, not beside it. */
  stacked?: boolean;
}) {
  return (
    <div className="s1-mr-scroll">
      <table className={`s1-mr-table s1-mr-cats${stacked ? " s1-mr-cats--stacked" : ""}`}>
        <thead>
          <tr>
            <th>{heading}</th>
            <th className="s1-mr-col-incl">Included</th>
            {stacked ? null : <th aria-hidden />}
          </tr>
        </thead>
        <tbody>
          {categories.map((category) => {
            const edit = review.categories[category.id];
            const value = edit?.value ?? category.value;
            const label = labelOf(category);
            const adjusted = edit ? (
              <Adjusted
                by={edit.by}
                at={edit.at}
                original={category.value}
                onRevert={() => onChange((s) => revertCategory(s, category, label, who()))}
              />
            ) : null;
            return (
              <Fragment key={category.id}>
                <tr className={stacked && edit ? "has-adjusted" : undefined}>
                  <td>{category.name}</td>
                  <td>
                    <select
                      className="s1-select s1-mr-select"
                      value={value}
                      aria-label={`${stacked ? `${heading}, included` : "Included"}: ${category.name}`}
                      onChange={(e) => onChange((s) => setCategory(s, category, label, e.target.value as Inclusion, who()))}
                    >
                      {INCLUSIONS.map((option) => (
                        <option key={option} value={option}>
                          {option}
                        </option>
                      ))}
                    </select>
                  </td>
                  {stacked ? null : <td>{adjusted}</td>}
                </tr>
                {stacked && adjusted ? (
                  <tr className="s1-mr-adjusted-row">
                    <td colSpan={2}>{adjusted}</td>
                  </tr>
                ) : null}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/* ================================== text fields ================================== */

function TextRows({
  fields,
  review,
  onChange,
  who,
  rows = 3,
}: {
  fields: StatedText[];
  review: MethodologyState;
  onChange: Update;
  who: Who;
  rows?: number;
}) {
  return (
    <div className="s1-mr-texts">
      {fields.map((field) => (
        <div key={field.id} className="s1-mr-textrow">
          <div className="s1-mr-textrow__label">{field.label}</div>
          <TextField
            field={field}
            review={review}
            rows={rows}
            onSave={(draft) => onChange((s) => saveText(s, field, draft, who()))}
            onRevert={() => onChange((s) => revertText(s, field, who()))}
          />
        </div>
      ))}
    </div>
  );
}

/** A stated text: Edit opens it, Save or Cancel closes it. */
function TextField({
  field,
  review,
  single = false,
  rows = 3,
  onSave,
  onRevert,
}: {
  field: StatedText;
  review: MethodologyState;
  /** The reporting period: a label above, a one-line input. */
  single?: boolean;
  rows?: number;
  onSave: (draft: string) => void;
  onRevert: () => void;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const edit = review.texts[field.id];
  const value = currentText(field, review);
  const close = () => setDraft(null);

  const view =
    draft === null ? (
      <div className={single ? "s1-mr-inline" : "s1-mr-textview"}>
        <div className={single ? "s1-mr-value" : "s1-mr-textview__value"}>
          {value ? <span>{value}</span> : <span className="s1-mr-none">Not detected</span>}
          {field.source && !edit ? (
            <>
              {" "}
              <span className="s1-mr-cite">{field.source}</span>
            </>
          ) : null}
        </div>
        <button className="s1-mr-btn" type="button" aria-label={`Edit ${field.label.toLowerCase()}`} onClick={() => setDraft(value)}>
          Edit
        </button>
      </div>
    ) : (
      <div className={single ? "s1-mr-inline" : "s1-mr-editor"}>
        {single ? (
          <input className="s1-mr-input s1-mr-input--period" value={draft} aria-label={field.label} onChange={(e) => setDraft(e.target.value)} />
        ) : (
          <textarea className="s1-mr-input" rows={rows} value={draft} aria-label={field.label} onChange={(e) => setDraft(e.target.value)} />
        )}
        <div className="s1-mr-actions">
          <button
            className="s1-mr-btn s1-mr-btn--pri"
            type="button"
            onClick={() => {
              onSave(draft);
              close();
            }}
          >
            Save
          </button>
          <button className="s1-mr-btn" type="button" onClick={close}>
            Cancel
          </button>
        </div>
      </div>
    );

  return (
    <div className="s1-mr-field">
      {single ? <div className="s1-mr-label">{field.label}</div> : null}
      {view}
      {edit && draft === null ? <Adjusted by={edit.by} at={edit.at} original={shorten(field.value)} onRevert={onRevert} /> : null}
    </div>
  );
}

/* ================================ emission factors ================================ */

const SCOPE_TITLE: Record<FactorScope, string> = { scope1: "Scope 1", scope2: "Scope 2" };

function FactorBox({
  scope,
  rows,
  stated,
  onChange,
  who,
}: {
  scope: FactorScope;
  rows: FactorRow[];
  stated: MethodologyStated;
  onChange: Update;
  who: Who;
}) {
  const [drafts, setDrafts] = useState<Record<string, { database: string; edition: string }>>({});
  const [adding, setAdding] = useState<{ database: string; edition: string } | null>(null);
  const draftFor = (id: string, next: { database: string; edition: string } | null) =>
    setDrafts((cur) => {
      const copy = { ...cur };
      if (next) copy[id] = next;
      else delete copy[id];
      return copy;
    });

  return (
    <div className="s1-mr-box">
      <div className="s1-mr-box__title">{SCOPE_TITLE[scope]}</div>
      <div className="s1-mr-scroll">
        <table className="s1-mr-table s1-mr-factors">
          <thead>
            <tr>
              <th>Database</th>
              <th className="s1-mr-col-edition">Edition</th>
              <th>Identified by</th>
              <th className="s1-mr-col-flag">Flag</th>
              <th className="s1-mr-col-actions" aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {rows
              .filter((row) => !row.hidden)
              .map((row) => {
                const draft = drafts[row.id];
                if (draft) {
                  return (
                    <FactorEditor
                      key={row.id}
                      draft={draft}
                      onDraft={(next) => draftFor(row.id, next)}
                      onSave={() => {
                        onChange((s) => saveFactor(s, stated, scope, row.id, draft, who()));
                        draftFor(row.id, null);
                      }}
                      onCancel={() => draftFor(row.id, null)}
                    />
                  );
                }
                const tip = row.original
                  ? `Set by verifier ${row.by} · ${formatWhen(row.at ?? "")}. Original: ${row.original.database} · ${row.original.edition} · ${row.original.identifiedBy}`
                  : row.added
                    ? `Added by verifier ${row.by} · ${formatWhen(row.at ?? "")}`
                    : undefined;
                return (
                  <tr key={row.id} className={row.flag ? "is-flagged" : undefined}>
                    <td>{row.database}</td>
                    <td>{row.edition}</td>
                    <td>
                      <Identified by={row.identifiedBy} tip={tip} />
                    </td>
                    <td>{row.flag ? <span className="s1-mr-flag">{row.flag}</span> : null}</td>
                    <td>
                      <div className="s1-mr-actions">
                        <button
                          className="s1-mr-btn"
                          type="button"
                          aria-label={`Edit ${row.database}${row.edition ? ` ${row.edition}` : ""}`}
                          onClick={() => draftFor(row.id, { database: row.database, edition: row.edition })}
                        >
                          Edit
                        </button>
                        {row.original ? (
                          <button className="s1-mr-link" type="button" onClick={() => onChange((s) => revertFactor(s, stated, scope, row.id, who()))}>
                            Revert
                          </button>
                        ) : null}
                        {row.added ? (
                          <button className="s1-mr-link" type="button" onClick={() => onChange((s) => removeFactor(s, stated, scope, row.id, who()))}>
                            Remove
                          </button>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                );
              })}
            {adding ? (
              <FactorEditor
                draft={adding}
                onDraft={setAdding}
                onSave={() => {
                  onChange((s) => addFactor(s, stated, scope, adding, who()));
                  setAdding(null);
                }}
                onCancel={() => setAdding(null)}
              />
            ) : null}
          </tbody>
        </table>
      </div>
      <div className="s1-mr-box__foot">
        <button className="s1-mr-btn" type="button" onClick={() => setAdding({ database: "", edition: "" })} disabled={Boolean(adding)}>
          <Plus className="s1-mr-ico" aria-hidden /> Add source
        </button>
      </div>
    </div>
  );
}

function FactorEditor({
  draft,
  onDraft,
  onSave,
  onCancel,
}: {
  draft: { database: string; edition: string };
  onDraft: (next: { database: string; edition: string }) => void;
  onSave: () => void;
  onCancel: () => void;
}) {
  return (
    <tr className="s1-mr-editrow">
      <td>
        <input
          className="s1-mr-input"
          value={draft.database}
          placeholder="EPA eGRID"
          aria-label="Database"
          onChange={(e) => onDraft({ ...draft, database: e.target.value })}
        />
      </td>
      <td>
        <input
          className="s1-mr-input"
          value={draft.edition}
          placeholder="eGRID2023"
          aria-label="Edition"
          onChange={(e) => onDraft({ ...draft, edition: e.target.value })}
        />
      </td>
      <td className="s1-mr-muted">Set by verifier on save</td>
      <td />
      <td>
        <div className="s1-mr-actions">
          <button className="s1-mr-btn s1-mr-btn--pri" type="button" disabled={!draft.database.trim()} onClick={onSave}>
            Save
          </button>
          <button className="s1-mr-btn" type="button" onClick={onCancel}>
            Cancel
          </button>
        </div>
      </td>
    </tr>
  );
}

/* ====================================== GWP ====================================== */

function GwpTable({ stated, review, onChange, who }: { stated: MethodologyStated; review: MethodologyState; onChange: Update; who: Who }) {
  const [draft, setDraft] = useState<{ set: string; horizon: string } | null>(null);
  const gwp = currentGwp(stated, review);
  const flag = gwpFlag(gwp.horizon);
  const tip = review.gwp
    ? `Set by verifier ${review.gwp.by} · ${formatWhen(review.gwp.at)}. Original: ${stated.gwp.set} · ${stated.gwp.horizon} · ${stated.gwp.identifiedBy}`
    : undefined;

  return (
    <div className="s1-mr-scroll">
      <table className="s1-mr-table s1-mr-factors s1-mr-gwp">
        <thead>
          <tr>
            <th>GWP set</th>
            <th className="s1-mr-col-edition">Time horizon</th>
            <th>Identified by</th>
            <th className="s1-mr-col-flag">Flag</th>
            <th className="s1-mr-col-actions" aria-label="Actions" />
          </tr>
        </thead>
        <tbody>
          {draft ? (
            <tr className="s1-mr-editrow">
              <td>
                <select className="s1-select s1-mr-select s1-mr-select--fill" value={draft.set} aria-label="GWP set" onChange={(e) => setDraft({ ...draft, set: e.target.value })}>
                  {GWP_SETS.map((set) => (
                    <option key={set} value={set}>
                      {set}
                    </option>
                  ))}
                </select>
              </td>
              <td>
                <select
                  className="s1-select s1-mr-select s1-mr-select--fill"
                  value={draft.horizon}
                  aria-label="Time horizon"
                  onChange={(e) => setDraft({ ...draft, horizon: e.target.value })}
                >
                  {GWP_HORIZONS.map((horizon) => (
                    <option key={horizon} value={horizon}>
                      {horizon}
                    </option>
                  ))}
                </select>
              </td>
              <td className="s1-mr-muted">Set by verifier on save</td>
              <td />
              <td>
                <div className="s1-mr-actions">
                  <button
                    className="s1-mr-btn s1-mr-btn--pri"
                    type="button"
                    onClick={() => {
                      onChange((s) => saveGwp(s, stated, draft, who()));
                      setDraft(null);
                    }}
                  >
                    Save
                  </button>
                  <button className="s1-mr-btn" type="button" onClick={() => setDraft(null)}>
                    Cancel
                  </button>
                </div>
              </td>
            </tr>
          ) : (
            <tr className={flag ? "is-flagged" : undefined}>
              <td>{gwp.set}</td>
              <td>{gwp.horizon}</td>
              <td>
                <Identified by={gwp.identifiedBy} tip={tip} />
              </td>
              <td>{flag ? <span className="s1-mr-flag">{flag}</span> : null}</td>
              <td>
                <div className="s1-mr-actions">
                  <button className="s1-mr-btn" type="button" aria-label="Edit GWP set" onClick={() => setDraft({ set: gwp.set, horizon: gwp.horizon })}>
                    Edit
                  </button>
                  {review.gwp ? (
                    <button className="s1-mr-link" type="button" onClick={() => onChange((s) => revertGwp(s, stated, who()))}>
                      Revert
                    </button>
                  ) : null}
                </div>
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function formatWhen(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });
}
