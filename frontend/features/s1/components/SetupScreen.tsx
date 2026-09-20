"use client";

import type { EngagementConfig } from "../types";
import type { InScopeField } from "../types/scope";

/**
 * Setup (screen 0). Records what the engagement covers so every later page
 * knows which data points apply. Facilities are a hard precondition for the
 * Evidence Workspace; the client contact and engagement team are preconditions
 * for Evidence Requests. Regulation and methodology are real selectors — nothing
 * downstream assumes SB 253, and no deadlines are derived here.
 *
 * The in-scope data-point list is placeholder: the real field list is pending
 * from product. The rows carry methodologyFieldId and a completeness slot so
 * the shape does not have to be retrofitted.
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

const METHODOLOGY_OPTIONS = ["GHG Protocol Corporate Standard", "ISO 14064-1:2018"];

const LAYER_LABEL: Record<InScopeField["layer"], string> = {
  general: "General",
  scope1: "Scope 1",
  scope2: "Scope 2",
};

export function SetupScreen({
  engagement,
  onChange,
  inScopeFields,
  onInScopeChange,
}: {
  engagement: EngagementConfig;
  onChange: (next: EngagementConfig) => void;
  inScopeFields: InScopeField[];
  onInScopeChange: (fields: InScopeField[]) => void;
}) {
  const set = (patch: Partial<EngagementConfig>) => onChange({ ...engagement, ...patch });
  const team = engagement.engagementTeam ?? [];

  function addFacility() {
    const id = `facility-${Date.now().toString(36)}`;
    set({ facilities: [...engagement.facilities, { facilityId: id, name: "New facility" }] });
  }
  function renameFacility(facilityId: string, name: string) {
    set({ facilities: engagement.facilities.map((f) => (f.facilityId === facilityId ? { ...f, name } : f)) });
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
          <span className="s1-muted">What this engagement covers. Facilities feed the Evidence Workspace; the client contact and team feed Evidence Requests.</span>
        </div>
      </header>

      {/* Engagement basics */}
      <div className="s1-setup-card">
        <h2>Engagement</h2>
        <div className="s1-setup-grid">
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
              value={engagement.regulation}
              onChange={(e) => {
                const opt = REGULATION_OPTIONS.find((o) => o.short === e.target.value);
                if (opt) set({ regulation: opt.short, regulationJurisdiction: opt.full });
              }}
            >
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

      {/* Facilities */}
      <div className="s1-setup-card">
        <h2>Facilities</h2>
        <p className="s1-muted">Entered manually. The Evidence Workspace facility column and filter read from this list.</p>
        <div className="s1-setup-list">
          {engagement.facilities.map((f) => (
            <div className="s1-setup-row" key={f.facilityId}>
              <input value={f.name} onChange={(e) => renameFacility(f.facilityId, e.target.value)} />
              <span className="s1-mono s1-muted">{f.facilityId}</span>
              <button className="s1-linklike" type="button" onClick={() => removeFacility(f.facilityId)}>
                Remove
              </button>
            </div>
          ))}
        </div>
        <button className="s1-button" type="button" onClick={addFacility}>
          Add facility
        </button>
      </div>

      {/* Client contact */}
      <div className="s1-setup-card">
        <h2>Client contact</h2>
        <p className="s1-muted">One recipient for the whole engagement. Evidence Requests sends to this address.</p>
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
          <label className="s1-setup-field">
            <span>Your email (Request-by-email “from”)</span>
            <input type="email" value={engagement.verifierEmail ?? ""} onChange={(e) => set({ verifierEmail: e.target.value })} />
          </label>
        </div>
      </div>

      {/* Engagement team */}
      <div className="s1-setup-card">
        <h2>Engagement team</h2>
        <p className="s1-muted">The “raised by” options on a request. Typically up to four people.</p>
        <div className="s1-setup-list">
          {team.map((m, i) => (
            <div className="s1-setup-row" key={m.login}>
              <input
                value={m.name}
                onChange={(e) => setTeam(team.map((t, j) => (j === i ? { ...t, name: e.target.value } : t)))}
              />
              <input
                className="s1-mono"
                value={m.login}
                onChange={(e) => setTeam(team.map((t, j) => (j === i ? { ...t, login: e.target.value } : t)))}
              />
              <button className="s1-linklike" type="button" onClick={() => setTeam(team.filter((_, j) => j !== i))}>
                Remove
              </button>
            </div>
          ))}
        </div>
        <button
          className="s1-button"
          type="button"
          onClick={() => setTeam([...team, { name: "New member", login: `login${team.length + 1}` }])}
        >
          Add member
        </button>
      </div>

      {/* In-scope data points — placeholder */}
      <div className="s1-setup-card">
        <div className="s1-setup-card__head">
          <h2>In-scope data points</h2>
          <span className="s1-state s1-state--open">Field list pending · placeholder rows</span>
        </div>
        <p className="s1-muted">
          The in-scope list is what makes the rest of the product finite. These rows are placeholders until product
          delivers the field list; each already carries its methodology field id and a slot for completeness status.
        </p>
        <div className="s1-table-wrap">
          <table className="s1-table">
            <colgroup>
              <col style={{ width: "6%" }} />
              <col style={{ minWidth: "16rem" }} />
              <col style={{ width: "10%" }} />
              <col style={{ width: "12%" }} />
              <col style={{ minWidth: "18rem" }} />
              <col style={{ width: "12%" }} />
            </colgroup>
            <thead>
              <tr>
                <th>In scope</th>
                <th>Data point</th>
                <th>Layer</th>
                <th>Requirement</th>
                <th>Methodology field id</th>
                <th>Completeness</th>
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
                  <td className="s1-mono s1-muted">{field.methodologyFieldId}</td>
                  <td className="s1-muted">{field.completenessStatus ?? "Pending"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

function contact(engagement: EngagementConfig) {
  return engagement.clientContact ?? { name: "", email: "", company: engagement.clientName };
}
