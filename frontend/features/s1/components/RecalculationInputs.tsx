"use client";

import { useState } from "react";

import type { Recalculation, RecalculationReference } from "../api/recalculation";
import type { RecalculationCertificate, RecalculationSettings } from "../types";

/**
 * What the recalculation needs that the evidence does not carry: the eGRID subregion
 * for each facility, the EPA fuel where the match is not clear, renewable energy
 * certificates, the client's reported totals, and the GWP set. Nothing here is
 * defaulted silently: the backend lists what is missing and this panel asks for it.
 */
export function RecalculationInputs({
  result,
  reference,
  settings,
  saving,
  error,
  onSave,
}: {
  result: Recalculation;
  reference: RecalculationReference;
  settings: RecalculationSettings;
  saving: boolean;
  error: string | null;
  onSave: (next: RecalculationSettings) => void;
}) {
  const [draft, setDraft] = useState<RecalculationSettings>(settings);
  const [reportedText, setReportedText] = useState<Record<string, string>>(() =>
    Object.fromEntries(Object.entries(settings.reported ?? {}).map(([key, value]) => [key, String(value)]))
  );
  const [certificateText, setCertificateText] = useState<{ label: string; mwh: string }[]>(() =>
    (settings.certificates ?? []).map((c) => ({ label: c.label, mwh: String(c.mwh) }))
  );
  const asks = result.needs_input;
  const [open, setOpen] = useState(asks.length > 0);

  const facilities = Array.from(
    new Set([
      ...asks.filter((a) => a.kind === "grid_region").map((a) => a.key),
      ...(result.categories.purchased_electricity_location_based?.lines.map((l) => l.key) ?? []),
      ...Object.keys(draft.grid_regions ?? {}),
    ])
  );
  const fuelAsks = asks.filter((a) => a.kind === "fuel_choice");
  const otherAsks = asks.filter((a) => a.kind !== "grid_region" && a.kind !== "fuel_choice");

  const badReported = Object.entries(reportedText).filter(([, text]) => text.trim() && !Number.isFinite(Number(text)));
  const badCertificates = certificateText.filter((c) => !c.label.trim() || !(Number(c.mwh) > 0));
  const invalid = badReported.length > 0 || badCertificates.length > 0;

  function save() {
    const reported: Record<string, number> = {};
    for (const [key, text] of Object.entries(reportedText)) if (text.trim()) reported[key] = Number(text);
    const certificates: RecalculationCertificate[] = certificateText.map((c) => ({
      label: c.label.trim(),
      mwh: Number(c.mwh),
    }));
    onSave({ ...draft, reported, certificates });
  }

  const setRegion = (facility: string, region: string) => {
    const grid_regions = { ...(draft.grid_regions ?? {}) };
    if (region) grid_regions[facility] = region;
    else delete grid_regions[facility];
    setDraft({ ...draft, grid_regions });
  };
  const setFuel = (key: string, fuel: string) => {
    const fuel_choices = { ...(draft.fuel_choices ?? {}) };
    if (fuel) fuel_choices[key] = fuel;
    else delete fuel_choices[key];
    setDraft({ ...draft, fuel_choices });
  };

  return (
    <section className="s1-rc" aria-label="Recalculation inputs">
      <button className="s1-rc__head" type="button" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span className="s1-rc__title">Recalculation inputs</span>
        <span className={`s1-state s1-state--${asks.length ? "open" : "resolved"}`}>
          {asks.length ? `${asks.length} needed` : "Complete"}
        </span>
        {result.awaiting_review.length ? (
          <span className="s1-state s1-state--unverifiable">{result.awaiting_review.length} awaiting review</span>
        ) : null}
        <span className="s1-muted s1-rc__meta">
          {reference.dataset} · {result.gwp_set} GWPs · ±{result.tolerance_pct}% tolerance
        </span>
      </button>

      {open ? (
        <div className="s1-rc__body">
          {otherAsks.length || result.awaiting_review.length ? (
            <ul className="s1-rc__asks">
              {otherAsks.map((a) => (
                <li key={`${a.kind}|${a.key}`}>{a.message}</li>
              ))}
              {result.awaiting_review.map((a) => (
                <li key={`${a.document_id}|${a.record}`}>
                  {a.record}: {a.fields.map((f) => f.replace(/_/g, " ")).join(", ")} not reviewed yet. Review it in
                  Extraction Review to include it.
                </li>
              ))}
            </ul>
          ) : null}

          <div className="s1-rc__grid">
            <fieldset className="s1-rc__group">
              <legend>Grid region (eGRID subregion) per facility</legend>
              {facilities.length === 0 ? (
                <p className="s1-muted">No reviewed electricity bills yet.</p>
              ) : (
                facilities.map((facility) => {
                  const ask = asks.find((a) => a.kind === "grid_region" && a.key === facility);
                  return (
                    <label key={facility} className="s1-rc__field">
                      <span>
                        {facility}
                        {ask ? <span className="s1-rc__need"> needed</span> : null}
                      </span>
                      <select value={draft.grid_regions?.[facility] ?? ""} onChange={(e) => setRegion(facility, e.target.value)}>
                        <option value="">Choose a subregion</option>
                        {reference.egrid_subregions.map((r) => (
                          <option key={r.egrid_subregion} value={r.egrid_subregion}>
                            {r.egrid_subregion} · {r.name}
                          </option>
                        ))}
                      </select>
                      {ask ? <span className="s1-muted s1-rc__hint">{ask.message}</span> : null}
                    </label>
                  );
                })
              )}
            </fieldset>

            <fieldset className="s1-rc__group">
              <legend>Method</legend>
              <label className="s1-rc__field">
                <span>GWP set</span>
                <select value={draft.gwp_set ?? reference.default_gwp_set} onChange={(e) => setDraft({ ...draft, gwp_set: e.target.value })}>
                  {reference.gwp_sets.map((g) => (
                    <option key={g} value={g}>
                      {g === "AR5" ? "AR5 (EPA Hub, Table 11)" : `${g} (IPCC)`}
                    </option>
                  ))}
                </select>
              </label>
              {fuelAsks.map((a) => (
                <label key={a.key} className="s1-rc__field">
                  <span>
                    {a.message}
                    <span className="s1-rc__need"> needed</span>
                  </span>
                  <select value={draft.fuel_choices?.[a.key] ?? ""} onChange={(e) => setFuel(a.key, e.target.value)}>
                    <option value="">Choose the EPA fuel</option>
                    {(a.options ?? []).map((o) => (
                      <option key={o} value={o}>
                        {o}
                      </option>
                    ))}
                  </select>
                </label>
              ))}
              {Object.entries(draft.fuel_choices ?? {})
                .filter(([key]) => !fuelAsks.some((a) => a.key === key))
                .map(([key, fuel]) => (
                  <div key={key} className="s1-rc__chosen">
                    <span className="s1-muted">{key.replace(":", " · ").replace(/_/g, " ")}</span>
                    <span>{fuel}</span>
                    <button className="s1-linklike" type="button" onClick={() => setFuel(key, "")}>
                      Clear
                    </button>
                  </div>
                ))}
            </fieldset>

            <fieldset className="s1-rc__group">
              <legend>Renewable energy certificates (market-based)</legend>
              {certificateText.map((c, index) => (
                <div key={index} className="s1-rc__cert">
                  <input
                    aria-label="Certificate"
                    placeholder="e.g. REC retirement report 1"
                    value={c.label}
                    onChange={(e) =>
                      setCertificateText(certificateText.map((x, i) => (i === index ? { ...x, label: e.target.value } : x)))
                    }
                  />
                  <input
                    aria-label="MWh"
                    inputMode="decimal"
                    placeholder="MWh"
                    value={c.mwh}
                    onChange={(e) =>
                      setCertificateText(certificateText.map((x, i) => (i === index ? { ...x, mwh: e.target.value } : x)))
                    }
                  />
                  <button
                    className="s1-linklike"
                    type="button"
                    onClick={() => setCertificateText(certificateText.filter((_, i) => i !== index))}
                  >
                    Remove
                  </button>
                </div>
              ))}
              <button
                className="s1-linklike"
                type="button"
                onClick={() => setCertificateText([...certificateText, { label: "", mwh: "" }])}
              >
                Add certificate
              </button>
            </fieldset>

            <fieldset className="s1-rc__group s1-rc__group--wide">
              <legend>Reported values (from the client&rsquo;s summary documents)</legend>
              <div className="s1-rc__reported">
                {reference.reported_data_points.map((p) => (
                  <label key={p.key} className="s1-rc__field s1-rc__field--row">
                    <span>
                      {p.label} <span className="s1-muted">· row {p.workbook_row}</span>
                    </span>
                    <span className="s1-rc__num">
                      <input
                        inputMode="decimal"
                        value={reportedText[p.key] ?? ""}
                        aria-invalid={badReported.some(([key]) => key === p.key)}
                        onChange={(e) => setReportedText({ ...reportedText, [p.key]: e.target.value })}
                      />
                      <span className="s1-muted">{p.unit === "t CO2e" ? "tCO₂e" : p.unit}</span>
                    </span>
                  </label>
                ))}
              </div>
            </fieldset>
          </div>

          <div className="s1-rc__actions">
            <button className="s1-button s1-button--pri" type="button" disabled={saving || invalid} onClick={save}>
              {saving ? "Saving…" : "Save and recalculate"}
            </button>
            {invalid ? (
              <span className="s1-rc__error">
                {badReported.length ? "Reported values must be numbers. " : ""}
                {badCertificates.length ? "Each certificate needs a name and a positive MWh." : ""}
              </span>
            ) : error ? (
              <span className="s1-rc__error">{error}</span>
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}
