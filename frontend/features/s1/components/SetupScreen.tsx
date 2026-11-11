"use client";

import { Plus, X } from "lucide-react";
import type { ReactNode } from "react";

import type { EngagementConfig, FacilityOption } from "../types";
import type { InScopeField } from "../types/scope";
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
const ASSURANCE_LEVEL_OPTIONS = ["Limited assurance", "Reasonable assurance"];
const MATERIALITY_OPTIONS = ["5%", "10%"];

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

      {/* Engagement basics. In backend mode they belong to the picked engagement. */}
      {picker && !engagement.engagementId ? null : (
      <>
      <div className="s1-setup-card">
        <h2>{picker ? "Details" : "Engagement"}</h2>
        <div className="s1-setup-grid">
          {picker ? (
            <label className="s1-setup-field">
              <span>Engagement name</span>
              <input
                value={engagement.engagementName ?? ""}
                maxLength={200}
                onChange={(e) => set({ engagementName: e.target.value })}
              />
            </label>
          ) : null}
          <label className="s1-setup-field">
            <span>Company name</span>
            <input value={engagement.clientName} onChange={(e) => set({ clientName: e.target.value })} />
          </label>
          <label className="s1-setup-field">
            <span>Reporting period</span>
            <div className="s1-setup-inline">
              <input
                type="date"
                value={engagement.reportingPeriod.start}
                onChange={(e) => set({ reportingPeriod: { ...engagement.reportingPeriod, start: e.target.value } })}
              />
              <input
                type="date"
                value={engagement.reportingPeriod.end}
                onChange={(e) => set({ reportingPeriod: { ...engagement.reportingPeriod, end: e.target.value } })}
              />
            </div>
          </label>
          <label className="s1-setup-field">
            <span>Regulation</span>
            <select
              value={engagement.regulation ?? ""}
              onChange={(e) => {
                const opt = REGULATION_OPTIONS.find((o) => o.short === e.target.value);
                if (opt) set({ regulation: opt.short, regulationJurisdiction: opt.full });
              }}
            >
              {/* An unset regulation shows as unset, not as the first option. */}
              {engagement.regulation ? null : (
                <option value="" disabled>
                  Choose a regulation
                </option>
              )}
              {REGULATION_OPTIONS.map((o) => (
                <option key={o.short} value={o.short}>
                  {o.full}
                </option>
              ))}
            </select>
          </label>
          <label className="s1-setup-field">
            <span>Methodology</span>
            <select value={engagement.methodology ?? METHODOLOGY_OPTIONS[0]} onChange={(e) => set({ methodology: e.target.value })}>
              {METHODOLOGY_OPTIONS.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>

      {/* Scope & assurance */}
      <div className="s1-setup-card">
        <h2>
          Scope &amp; assurance
          <InfoTip label="Scope and assurance">
            The coverage and the standard the opinion is issued under. They set the in-scope data points and the
            statement.
          </InfoTip>
        </h2>
        <div className="s1-setup-grid">
          <label className="s1-setup-field">
            <span>Data scope</span>
            <select value={engagement.dataScope ?? DATA_SCOPE_OPTIONS[0]} onChange={(e) => set({ dataScope: e.target.value })}>
              {DATA_SCOPE_OPTIONS.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
          </label>
          <label className="s1-setup-field">
            <span>Assurance standard</span>
            <select value={engagement.assuranceStandard ?? ASSURANCE_STANDARD_OPTIONS[0]} onChange={(e) => set({ assuranceStandard: e.target.value })}>
              {ASSURANCE_STANDARD_OPTIONS.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
          </label>
          <label className="s1-setup-field">
            <span>Assurance level</span>
            <select value={engagement.assuranceLevel ?? ""} onChange={(e) => set({ assuranceLevel: e.target.value })}>
              {engagement.assuranceLevel ? null : (
                <option value="" disabled>
                  Choose a level
                </option>
              )}
              {ASSURANCE_LEVEL_OPTIONS.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
          </label>
          <label className="s1-setup-field">
            <span>Materiality threshold</span>
            <select value={engagement.materialityThreshold ?? MATERIALITY_OPTIONS[0]} onChange={(e) => set({ materialityThreshold: e.target.value })}>
              {MATERIALITY_OPTIONS.map((o) => (
                <option key={o} value={o}>
                  {o} of total
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>

      {/* Facilities */}
      <div className="s1-setup-card">
        <h2>
          Facilities
          <InfoTip label="Facilities">
            Bills are matched to a facility by its name or street address. The grid region sets the factor for its
            electricity (Scope 2, location-based).
          </InfoTip>
        </h2>
        {engagement.facilities.length ? (
          <div className={`s1-fac${gridRegions ? " s1-fac--regions" : ""}`}>
            <div className="s1-fac__head" aria-hidden>
              <span>Name</span>
              <span>Street address</span>
              {gridRegions ? <span>Grid region (eGRID)</span> : null}
              <span />
            </div>
            {engagement.facilities.map((f) => (
              <div className="s1-fac__row" key={f.facilityId}>
                <input aria-label="Facility name" value={f.name} onChange={(e) => renameFacility(f.facilityId, e.target.value)} />
                <input
                  className="s1-fac__address"
                  aria-label="Street address"
                  placeholder="e.g. 15 State Street, Albany, NY"
                  value={f.address ?? ""}
                  onChange={(e) => patchFacility(f.facilityId, { address: e.target.value })}
                />
                {gridRegions ? (
                  <select
                    className="s1-fac__region"
                    aria-label="Grid region"
                    value={f.gridRegion ?? ""}
                    onChange={(e) => patchFacility(f.facilityId, { gridRegion: e.target.value || undefined })}
                  >
                    <option value="">Not set</option>
                    {gridRegions.map((r) => (
                      <option key={r.code} value={r.code}>
                        {r.code} · {r.name}
                      </option>
                    ))}
                  </select>
                ) : null}
                <RemoveButton label={`Remove ${f.name || "facility"}`} onClick={() => removeFacility(f.facilityId)} />
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
            <strong>Found on uploaded bills</strong>
            <span className="s1-muted"> · not matched to a facility yet</span>
            <ul>
              {foundFacilities.map((found) => (
                <li key={`${found.name}|${found.address ?? ""}`}>
                  <span>
                    {found.name}
                    {found.address ? <span className="s1-muted"> · {found.address}</span> : null}
                  </span>
                  <button className="s1-linklike" type="button" onClick={() => addFacility(found)}>
                    Add as facility
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        <AddButton onClick={() => addFacility()}>Add facility</AddButton>
      </div>

      {/* Client contact */}
      <div className="s1-setup-card">
        <h2>
          Client contact
          <InfoTip label="Client contact">One recipient for the whole engagement. Requests are sent to this address.</InfoTip>
        </h2>
        <div className="s1-setup-grid">
          <label className="s1-setup-field">
            <span>Name</span>
            <input
              value={engagement.clientContact?.name ?? ""}
              onChange={(e) => set({ clientContact: { ...contact(engagement), name: e.target.value } })}
            />
          </label>
          <label className="s1-setup-field">
            <span>Email</span>
            <input
              type="email"
              value={engagement.clientContact?.email ?? ""}
              onChange={(e) => set({ clientContact: { ...contact(engagement), email: e.target.value } })}
            />
          </label>
          <label className="s1-setup-field">
            <span>Company</span>
            <input
              value={engagement.clientContact?.company ?? ""}
              onChange={(e) => set({ clientContact: { ...contact(engagement), company: e.target.value } })}
            />
          </label>
        </div>
      </div>

      {/* Engagement team */}
      <div className="s1-setup-card">
        <h2>
          Engagement team
          <InfoTip label="Engagement team">Who can raise a request or examine a result. Typically up to four people.</InfoTip>
        </h2>
        <div className="s1-setup-list">
          <div className="s1-setup-row s1-setup-row--head" aria-hidden>
            <span>Name</span>
            <span>Login</span>
            <span />
          </div>
          {team.map((m, i) => (
            <div className="s1-setup-row" key={m.login}>
              <input
                aria-label="Name"
                value={m.name}
                onChange={(e) => setTeam(team.map((t, j) => (j === i ? { ...t, name: e.target.value } : t)))}
              />
              <input
                aria-label="Login"
                className="s1-num s1-setup-row__login"
                value={m.login}
                onChange={(e) => setTeam(team.map((t, j) => (j === i ? { ...t, login: e.target.value } : t)))}
              />
              <RemoveButton label={`Remove ${m.name}`} onClick={() => setTeam(team.filter((_, j) => j !== i))} />
            </div>
          ))}
        </div>
        <AddButton onClick={() => setTeam([...team, { name: "New member", login: `login${team.length + 1}` }])}>
          Add member
        </AddButton>
      </div>

      {/* In-scope data points: the workbook's reported data points (live), placeholders (demo) */}
      <div className="s1-setup-card">
        <div className="s1-setup-card__head">
          <h2>
            In-scope data points
            <InfoTip label="In-scope data points">
              The reported data points of the client&rsquo;s inventory. Untick one the client does not report: it then
              shows as not in scope on Verification results and is left out of coverage and materiality.
            </InfoTip>
          </h2>
          <span className="s1-state s1-state--resolved">
            {inScopeFields.filter((f) => f.inScope).length} of {inScopeFields.length} in scope
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
    </section>
  );
}

function RemoveButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button className="s1-setup-remove" type="button" aria-label={label} title={label} onClick={onClick}>
      <X aria-hidden />
    </button>
  );
}

function AddButton({ onClick, children }: { onClick: () => void; children: ReactNode }) {
  return (
    <button className="s1-setup-add" type="button" onClick={onClick}>
      <Plus aria-hidden /> {children}
    </button>
  );
}

function contact(engagement: EngagementConfig) {
  return engagement.clientContact ?? { name: "", email: "", company: engagement.clientName };
}
