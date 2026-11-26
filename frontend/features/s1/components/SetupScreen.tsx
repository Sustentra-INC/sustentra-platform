"use client";

import { useRef, useState, type ReactNode } from "react";

import { IconBuilding, IconPin, IconPlus, IconTrash } from "./icons";

import type { EngagementConfig, FacilityOption } from "../types";
import type { InScopeField } from "../types/scope";
import { CountBadge } from "./CountBadge";
import { DateRangePicker } from "./DateRangePicker";
import { Dropdown } from "./Dropdown";
import { InfoTip } from "./InfoTip";
import { ZipRegionHint } from "./ZipRegionHint";

/**
 * Setup (screen 0). Records what the engagement covers so every later page
 * knows which data points apply. Facilities are a hard precondition for the
 * Evidence Workspace; the client contact and engagement team are preconditions
 * for Evidence Requests. Regulation and methodology are real selectors — nothing
 * downstream assumes SB 253, and no deadlines are derived here.
 *
 * In-scope data points: on live data the rows are the reported data points of the
 * GHG Required Data workbook (rows carry ``workbookRow``); a data point set out of
 * scope shows on Verification results as not in scope and is left out of coverage
 * and materiality. The fixture demo keeps its placeholder rows.
 */

const REGULATION_OPTIONS = [
  {
    short: "California Senate Bill 253",
    full: "California Senate Bill 253: Climate Corporate Data Accountability Act (California, USA)",
  },
  {
    // Official statute title unconfirmed — jurisdiction only until confirmed.
    short: "New York Part 253",
    full: "New York Part 253 (New York, USA)",
  },
];

const METHODOLOGY_OPTIONS = ["GHG Protocol Corporate Standard"];
const DATA_SCOPE_OPTIONS = ["Scope 1 & 2", "Scope 1, 2, and 3"];
const ASSURANCE_STANDARD_OPTIONS = ["ISO 14064-3"];
const ASSURANCE_LEVEL_SEG = [
  { value: "Limited assurance", label: "Limited" },
  { value: "Reasonable assurance", label: "Reasonable" },
];
const MATERIALITY_OPTIONS = ["5%", "10%"];
const MATERIALITY_SEG = MATERIALITY_OPTIONS.map((v) => ({ value: v, label: v }));

const LAYER_LABEL: Record<InScopeField["layer"], string> = {
  general: "General",
  scope1: "Scope 1",
  scope2: "Scope 2",
};

let facilitySeq = 0;
/** A new facility's id: unique within the engagement, stable once saved. */
function newFacilityId(): string {
  facilitySeq += 1;
  return `facility-${Date.now().toString(36)}-${facilitySeq}`;
}

export function SetupScreen({
  engagement,
  onChange,
  inScopeFields,
  onInScopeChange,
  picker,
  gridRegions,
  lookupZip,
  foundFacilities = [],
}: {
  engagement: EngagementConfig;
  onChange: (next: EngagementConfig) => void;
  inScopeFields: InScopeField[];
  onInScopeChange: (fields: InScopeField[]) => void;
  /** Backend mode: choose / create the engagement being edited (S1-BE-002). */
  picker?: ReactNode;
  /** eGRID subregions to pick a facility's grid region from (backend mode). */
  gridRegions?: { code: string; name: string }[];
  /** eGRID subregions for a ZIP code (backend mode), to suggest each facility's grid region. */
  lookupZip?: (zip: string) => Promise<string[]>;
  /** Facilities named on uploaded bills that match no Setup facility yet. */
  foundFacilities?: { name: string; address: string | null }[];
}) {
  const set = (patch: Partial<EngagementConfig>) => onChange({ ...engagement, ...patch });
  // Live data: the rows are the workbook's data points, each with its workbook row.
  const live = inScopeFields.some((f) => f.workbookRow !== undefined);
  const team = engagement.engagementTeam ?? [];
  const [tab, setTab] = useState<"engagement" | "people" | "points">("engagement");
  const inScope = inScopeFields.filter((f) => f.inScope).length;

  function addFacility(seed?: { name: string; address: string | null }) {
    const id = newFacilityId();
    set({
      facilities: [
        ...engagement.facilities,
        { facilityId: id, name: seed?.name ?? "New facility", ...(seed?.address ? { address: seed.address } : {}) },
      ],
    });
  }
  function patchFacility(facilityId: string, patch: Partial<FacilityOption>) {
    set({ facilities: engagement.facilities.map((f) => (f.facilityId === facilityId ? { ...f, ...patch } : f)) });
  }
  function renameFacility(facilityId: string, name: string) {
    patchFacility(facilityId, { name });
  }
  function removeFacility(facilityId: string) {
    set({ facilities: engagement.facilities.filter((f) => f.facilityId !== facilityId) });
  }

  function setTeam(next: EngagementConfig["engagementTeam"]) {
    set({ engagementTeam: next });
  }

  return (
    <section className="s1-content s1-setup">
      <header className="s1-ws-header">
        <div className="s1-ws-header__id">
          <h1>Setup</h1>
          <InfoTip label="Setup">
            What this engagement covers. Facilities are used to match documents on Evidence; the client contact and
            the team are used on requests.
          </InfoTip>
        </div>
      </header>

      {picker}

      {/* Tabs and section cards. Only shown once an engagement is selected in backend mode. */}
      {picker && !engagement.engagementId ? null : (
        <>
          <div role="tablist" aria-label="Setup sections" className="s1-ws-factabs s1-ws-factabs--page">
            <button
              type="button"
              role="tab"
              aria-selected={tab === "engagement"}
              className={`s1-ws-factab${tab === "engagement" ? " is-on" : ""}`}
              onClick={() => setTab("engagement")}
            >
              Engagement
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === "people"}
              className={`s1-ws-factab${tab === "people" ? " is-on" : ""}`}
              onClick={() => setTab("people")}
            >
              Facilities and people
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === "points"}
              className={`s1-ws-factab${tab === "points" ? " is-on" : ""}`}
              onClick={() => setTab("points")}
            >
              In-scope data points
              <CountBadge variant="indigo">{inScope}/{inScopeFields.length}</CountBadge>
            </button>
          </div>

          {tab === "engagement" && (
            <>
              {/* Engagement basics. In backend mode they belong to the picked engagement. */}
              <div className="s1-setup-card">
                <div className="s1-setup-card__col-left">
                  <h2>
                    {picker ? "Details" : "Engagement"}
                    <InfoTip label={picker ? "Details" : "Engagement"}>
                      The company being assured, the period it reports on, and the rules it reports under.
                    </InfoTip>
                  </h2>
                </div>
                <div className="s1-setup-card__col-right">
                  <div className="s1-setup-grid">
                    {picker ? (
                      <label className="s1-setup-field">
                        <span className="s1-field-label">Engagement name</span>
                        <input
                          value={engagement.engagementName ?? ""}
                          maxLength={200}
                          onChange={(e) => set({ engagementName: e.target.value })}
                        />
                      </label>
                    ) : null}
                    <label className="s1-setup-field">
                      <span className="s1-field-label">Company name</span>
                      <input value={engagement.clientName} onChange={(e) => set({ clientName: e.target.value })} />
                    </label>
                    <div className="s1-setup-field">
                      <span id="setup-rp-label" className="s1-field-label">Reporting period</span>
                      <DateRangePicker
                        start={engagement.reportingPeriod.start}
                        end={engagement.reportingPeriod.end}
                        onChange={(s, e) => set({ reportingPeriod: { start: s, end: e } })}
                        labelId="setup-rp-label"
                      />
                    </div>
                    <div className="s1-setup-field">
                      <span id="setup-regulation-label" className="s1-field-label">Regulation</span>
                      <Dropdown
                        value={engagement.regulation ?? ""}
                        onChange={(v) => {
                          const opt = REGULATION_OPTIONS.find((o) => o.short === v);
                          if (opt) set({ regulation: opt.short, regulationJurisdiction: opt.full });
                        }}
                        options={REGULATION_OPTIONS.map((o) => ({ value: o.short, label: o.short, description: o.full }))}
                        placeholder="Choose a regulation"
                        labelId="setup-regulation-label"
                      />
                    </div>
                    <div className="s1-setup-field">
                      <span id="setup-methodology-label" className="s1-field-label">Methodology</span>
                      <Dropdown
                        value={engagement.methodology ?? METHODOLOGY_OPTIONS[0]}
                        onChange={(v) => set({ methodology: v })}
                        options={METHODOLOGY_OPTIONS.map((m) => ({ value: m, label: m }))}
                        labelId="setup-methodology-label"
                      />
                    </div>
                  </div>
                </div>
              </div>

              {/* Scope & assurance */}
              <div className="s1-setup-card">
                <div className="s1-setup-card__col-left">
                  <h2>
                    Scope &amp; assurance
                    <InfoTip label="Scope and assurance">
                      The coverage and the standard the opinion is issued under. They set the in-scope data points and the
                      statement.
                    </InfoTip>
                  </h2>
                </div>
                <div className="s1-setup-card__col-right">
                  <div className="s1-setup-grid">
                    <SegmentedField
                      id="setup-datascope-label"
                      label="Data scope"
                      options={DATA_SCOPE_OPTIONS.map((v) => ({ value: v, label: v }))}
                      value={engagement.dataScope ?? DATA_SCOPE_OPTIONS[0]}
                      onChange={(v) => set({ dataScope: v })}
                    />
                    <div className="s1-setup-field">
                      <span id="setup-standard-label" className="s1-field-label">Assurance standard</span>
                      <Dropdown
                        value={engagement.assuranceStandard ?? ASSURANCE_STANDARD_OPTIONS[0]}
                        onChange={(v) => set({ assuranceStandard: v })}
                        options={ASSURANCE_STANDARD_OPTIONS.map((o) => ({ value: o, label: o }))}
                        labelId="setup-standard-label"
                      />
                    </div>
                    <SegmentedField
                      id="setup-level-label"
                      label="Assurance level"
                      options={ASSURANCE_LEVEL_SEG}
                      value={engagement.assuranceLevel ?? ""}
                      onChange={(v) => set({ assuranceLevel: v })}
                    />
                    <SegmentedField
                      id="setup-materiality-label"
                      label="Materiality threshold"
                      options={MATERIALITY_SEG}
                      value={engagement.materialityThreshold ?? MATERIALITY_OPTIONS[0]}
                      onChange={(v) => set({ materialityThreshold: v })}
                    />
                  </div>
                </div>
              </div>
            </>
          )}

          {tab === "people" && (
            <>
              {/* Facilities */}
              <div className="s1-setup-card">
                <div className="s1-setup-card__col-left">
                  <h2>
                    Facilities{" "}
                    <span className="s1-heading-count">{engagement.facilities.length}</span>
                    <InfoTip label="Facilities">
                      Bills are matched to a facility by its name or street address. The grid region sets the factor for its
                      electricity (Scope 2, location-based).
                    </InfoTip>
                  </h2>
                </div>
                <div className="s1-setup-card__col-right">
                  {engagement.facilities.length ? (
                    <div className="s1-fac">
                      {engagement.facilities.map((f) => (
                        <div className="s1-fac__row" key={f.facilityId}>
                          <span aria-hidden="true" className="s1-fac__icon">
                            <IconBuilding size={18} />
                          </span>
                          <input
                            className="s1-fac__name"
                            aria-label="Facility name"
                            value={f.name}
                            onChange={(e) => renameFacility(f.facilityId, e.target.value)}
                          />
                          <div className="s1-fac__address-wrap">
                            <IconPin size={16} aria-hidden="true" />
                            <input
                              className="s1-fac__address"
                              aria-label="Street address"
                              placeholder="e.g. 15 State Street, Albany, NY"
                              value={f.address ?? ""}
                              onChange={(e) => patchFacility(f.facilityId, { address: e.target.value })}
                            />
                          </div>
                          {gridRegions ? (
                            <>
                              <span id={`grl-${f.facilityId}`} className="s1-sr-only">Grid region</span>
                              <div className="s1-fac__region-wrap">
                                <Dropdown
                                  value={f.gridRegion ?? ""}
                                  onChange={(v) => patchFacility(f.facilityId, { gridRegion: v || undefined })}
                                  options={[
                                    { value: "", label: "Not set" },
                                    ...gridRegions.map((r) => ({ value: r.code, label: `${r.code} · ${r.name}` })),
                                  ]}
                                  placeholder="Not set"
                                  labelId={`grl-${f.facilityId}`}
                                />
                              </div>
                            </>
                          ) : null}
                          <button
                            className="s1-fac__remove"
                            type="button"
                            aria-label={`Remove ${f.name || "facility"}`}
                            onClick={() => removeFacility(f.facilityId)}
                          >
                            <IconTrash size={16} aria-hidden="true" />
                          </button>
                          {gridRegions && lookupZip ? (
                            <ZipRegionHint
                              address={f.address}
                              region={f.gridRegion}
                              lookup={lookupZip}
                              onUse={(code) => patchFacility(f.facilityId, { gridRegion: code })}
                            />
                          ) : null}
                        </div>
                      ))}
                    </div>
                  ) : null}
                  {foundFacilities.length ? (
                    <div className="s1-fac__found">
                      <span className="s1-fac__found-label">Found on uploaded bills</span>
                      <ul>
                        {foundFacilities.map((found) => (
                          <li key={`${found.name}|${found.address ?? ""}`}>
                            <div className="s1-fac__found-row">
                              <span>
                                {found.name}
                                {found.address ? <span className="s1-muted"> · {found.address}</span> : null}
                              </span>
                              <button
                                className="s1-button s1-button--soft s1-button--compact"
                                type="button"
                                onClick={() => addFacility(found)}
                              >
                                Add as facility
                              </button>
                            </div>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  <button className="s1-button s1-button--soft s1-fac__add" type="button" onClick={() => addFacility()}>
                    <IconPlus size={15} aria-hidden="true" /> Add facility
                  </button>
                </div>
              </div>

              {/* Client contact */}
              <div className="s1-setup-card">
                <div className="s1-setup-card__col-left">
                  <h2>
                    Client contact
                    <InfoTip label="Client contact">One recipient for the whole engagement. Requests are sent to this address.</InfoTip>
                  </h2>
                </div>
                <div className="s1-setup-card__col-right">
                  <div className="s1-contact-panel">
                    <span className="s1-contact-avatar" aria-hidden="true">
                      {initials(engagement.clientContact?.name)}
                    </span>
                    <div className="s1-contact-fields">
                      <label className="s1-contact-field">
                        <span className="s1-field-label">Name</span>
                        <input
                          className="s1-input"
                          value={engagement.clientContact?.name ?? ""}
                          onChange={(e) => set({ clientContact: { ...contact(engagement), name: e.target.value } })}
                        />
                      </label>
                      <label className="s1-contact-field">
                        <span className="s1-field-label">Email</span>
                        <input
                          className="s1-input"
                          type="email"
                          value={engagement.clientContact?.email ?? ""}
                          onChange={(e) => set({ clientContact: { ...contact(engagement), email: e.target.value } })}
                        />
                      </label>
                      <label className="s1-contact-field">
                        <span className="s1-field-label">Company</span>
                        <input
                          className="s1-input"
                          value={engagement.clientContact?.company ?? ""}
                          onChange={(e) => set({ clientContact: { ...contact(engagement), company: e.target.value } })}
                        />
                      </label>
                    </div>
                  </div>
                </div>
              </div>

              {/* Engagement team */}
              <div className="s1-setup-card">
                <div className="s1-setup-card__col-left">
                  <h2>
                    Engagement team{" "}
                    <span className="s1-heading-count">{team.length}</span>
                    <InfoTip label="Engagement team">Who can raise a request or examine a result. Typically up to four people.</InfoTip>
                  </h2>
                </div>
                <div className="s1-setup-card__col-right">
                  {team.length > 0 && (
                    <div className="s1-team-grid">
                      {team.map((m, i) => (
                        <div className="s1-team-card" key={m.login}>
                          <span className={`s1-team-avatar s1-team-avatar--${i % 4}`} aria-hidden="true">
                            {initials(m.name)}
                          </span>
                          <span className="s1-team-info">
                            <input
                              className="s1-team-name"
                              aria-label="Name"
                              value={m.name}
                              placeholder="Name"
                              onChange={(e) => setTeam(team.map((t, j) => (j === i ? { ...t, name: e.target.value } : t)))}
                            />
                            <span className="s1-team-login-row">
                              <span className="s1-team-login-label">Login</span>
                              <input
                                className="s1-num s1-setup-row__login s1-team-login"
                                aria-label="Login"
                                value={m.login}
                                placeholder="login"
                                onChange={(e) => setTeam(team.map((t, j) => (j === i ? { ...t, login: e.target.value } : t)))}
                              />
                            </span>
                          </span>
                          <button
                            className="s1-team-remove"
                            type="button"
                            aria-label={`Remove ${m.name}`}
                            onClick={() => setTeam(team.filter((_, j) => j !== i))}
                          >
                            <IconTrash size={16} aria-hidden="true" />
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                  <button
                    className="s1-button s1-button--soft s1-team-add"
                    type="button"
                    onClick={() => setTeam([...team, { name: "New member", login: `login${team.length + 1}` }])}
                  >
                    <IconPlus size={15} aria-hidden="true" /> Add member
                  </button>
                </div>
              </div>
            </>
          )}

          {tab === "points" && (
            <>
              {/* In-scope data points: the workbook's reported data points (live), placeholders (demo) */}
              <div className="s1-setup-card s1-setup-card--wide">
                <div className="s1-setup-card__head">
                  <h2>
                    In-scope data points
                    <InfoTip label="In-scope data points">
                      The reported data points of the client&rsquo;s inventory. Untick one the client does not report: it then
                      shows as not in scope on Verification results and is left out of coverage and materiality.
                    </InfoTip>
                  </h2>
                  <span className="s1-state s1-state--resolved">
                    {inScope} of {inScopeFields.length} in scope
                  </span>
                </div>
                <div className="s1-table-wrap">
                  <table className="s1-table">
                    <colgroup>
                      <col style={{ width: "7%" }} />
                      <col />
                      <col style={{ width: "11%" }} />
                      <col style={{ width: "13%" }} />
                      {live ? <col style={{ width: "13%" }} /> : null}
                      <col style={{ width: live ? "22%" : "16%" }} />
                    </colgroup>
                    <thead>
                      <tr>
                        <th>In scope</th>
                        <th>Data point</th>
                        <th>Scope</th>
                        <th>Requirement</th>
                        {live ? <th>Workbook row</th> : null}
                        <th>{live ? "How it is checked" : "Evidence"}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {inScopeFields.map((field, i) => (
                        <tr key={field.methodologyFieldId}>
                          <td>
                            <input
                              type="checkbox"
                              checked={field.inScope}
                              aria-label={`In scope: ${field.label}`}
                              onChange={(e) =>
                                onInScopeChange(inScopeFields.map((f, j) => (j === i ? { ...f, inScope: e.target.checked } : f)))
                              }
                            />
                          </td>
                          <td>{field.label}</td>
                          <td>{LAYER_LABEL[field.layer]}</td>
                          <td>{field.requirementLevel ?? "None"}</td>
                          {live ? (
                            <>
                              <td className="s1-num s1-muted">{field.workbookRow}</td>
                              <td className="s1-muted">{field.checkedBy}</td>
                            </>
                          ) : (
                            <td>{field.completenessStatus ?? "Pending"}</td>
                          )}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          )}
        </>
      )}
    </section>
  );
}

function contact(engagement: EngagementConfig) {
  return engagement.clientContact ?? { name: "", email: "", company: engagement.clientName };
}

function initials(name: string | null | undefined): string {
  if (!name?.trim()) return "";
  const words = name.trim().split(/\s+/);
  const first = words[0][0];
  const last = words.length > 1 ? words[words.length - 1][0] : "";
  return (first + last).toUpperCase();
}

function SegmentedField({
  id,
  label,
  options,
  value,
  onChange,
}: {
  id: string;
  label: string;
  options: { value: string; label: string }[];
  value: string;
  onChange: (v: string) => void;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const selectedIdx = options.findIndex((o) => o.value === value);

  function handleKeyDown(e: React.KeyboardEvent) {
    const cur = selectedIdx < 0 ? 0 : selectedIdx;
    let next = -1;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") next = (cur + 1) % options.length;
    else if (e.key === "ArrowLeft" || e.key === "ArrowUp") next = (cur - 1 + options.length) % options.length;
    if (next < 0) return;
    e.preventDefault();
    onChange(options[next].value);
    refs.current[next]?.focus();
  }

  return (
    <div className="s1-setup-field">
      <span id={id} className="s1-field-label">{label}</span>
      <div
        className="s1-ws-factabs s1-ws-factabs--seg"
        role="radiogroup"
        aria-labelledby={id}
        onKeyDown={handleKeyDown}
      >
        {options.map((opt, i) => (
          <button
            key={opt.value}
            ref={(el) => { refs.current[i] = el; }}
            type="button"
            role="radio"
            aria-checked={opt.value === value}
            className={`s1-ws-factab${opt.value === value ? " is-on" : ""}`}
            tabIndex={i === selectedIdx || (selectedIdx < 0 && i === 0) ? 0 : -1}
            onClick={() => onChange(opt.value)}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  );
}
