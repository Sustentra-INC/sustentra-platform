"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { lineRecomputed, lineReported } from "../utils/verificationTable";
import { liveResultsFromRecalculation } from "../adapters/recalculationResultsAdapter";
import {
  documentsBasis,
  getRecalculation,
  gwpLabel,
  getRecalculationReference,
  pluralCount,
  UNCOUNTED_REASON,
  uncountedHint,
  uncountedGroups,
  uncountedMessage,
  type Recalculation,
  type RecalculationReference,
} from "../api/recalculation";
import { userFacingApiError } from "../api/s1Backend";
import type { EngagementConfig, RecalculationSettings } from "../types";
import type { TeamMember } from "../types/engagement";
import type { VerificationStore } from "../verification/verificationStore";
import { CalculationPanels, panelIds } from "./CalculationPanels";
import { QualityChecksPanel } from "./QualityChecksPanel";
import { RecalculationInputs } from "./RecalculationInputs";
import { VerificationResults } from "./VerificationResults";

/** The Results rows whose drawer shows the per-line calculation panel (row id to panel id). */
const DRAWER_PANELS: Record<string, string> = {
  "s1-stationary": "stationary",
  "s1-mobile": "mobile",
  "s2l-electricity": "purchased_energy:electricity",
};

/**
 * Verification results in backend mode: the demo's boxes and calculation panel, filled from
 * the engagement's recalculation (reviewed evidence only) by the live results adapter. Its
 * inputs and data quality checks fold above the boxes.
 */

/** Who can be recorded as examiner: the engagement team, or the signed-in person while Setup has none. */
export function examinerOptions(engagement: EngagementConfig): TeamMember[] {
  if (engagement.engagementTeam?.length) return engagement.engagementTeam;
  const login = engagement.signedInLogin;
  return login ? [{ name: engagement.signedInName ?? login, login }] : [];
}

/** What the numbers rest on, for the page's ⓘ. */
export function resultsBasis(result: Recalculation): string {
  const open = result.needs_input.length + result.awaiting_review.length;
  return (
    `Recalculated from ${documentsBasis(result)} on the EPA GHG Emission Factors Hub 2025. GWP set: ${gwpLabel(result)}. ` +
    `A difference is material above ±${result.tolerance_pct}% of the reported total.` +
    (open ? ` ${open} ${open === 1 ? "item still needs" : "items still need"} an input or a review.` : "")
  );
}
export function BackendVerificationResults({
  engagement,
  store,
  onSaveInputs,
  onError,
  onOpenDocument,
  focusLineKey,
  onOpenEvidence,
  onOpenEvidenceTree,
}: {
  engagement: EngagementConfig;
  store: VerificationStore;
  /** Saves settings.recalculation on the engagement; rejects with the API error. */
  onSaveInputs: (next: RecalculationSettings) => Promise<void>;
  /** True when the error was handled (e.g. the session ended). */
  onError: (error: unknown) => boolean;
  /** Opens a reviewed record's document (Extraction review) from the Source pane. */
  onOpenDocument?: (documentId: string, valueId?: string) => void;
  /** Opens the calculation panel holding this line key, with the line expanded (Evidence links here). */
  focusLineKey?: string;
  /** Shows "Open in Evidence" on each line; called with the line key. */
  onOpenEvidence?: (lineKey: string) => void;
  /** Opens the Evidence tree (the notice about values not on a calculation line links here). */
  onOpenEvidenceTree?: () => void;
}) {
  const engagementId = engagement.engagementId;
  const [result, setResult] = useState<Recalculation | null>(null);
  const [reference, setReference] = useState<RecalculationReference | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  // Bumped to fetch again (after a save, or "Try again"); also resets the inputs panel.
  const [attempt, setAttempt] = useState(0);
  // The parent passes a fresh callback every render; keep the latest without refetching.
  const onErrorRef = useRef(onError);
  useEffect(() => {
    onErrorRef.current = onError;
  });
  const live = useMemo(() => (result ? liveResultsFromRecalculation(result) : null), [result]);

  useEffect(() => {
    if (!engagementId) return;
    let live = true;
    Promise.all([getRecalculation(engagementId), getRecalculationReference()])
      .then(([next, ref]) => {
        if (!live) return;
        setResult(next);
        setReference(ref);
        setLoadError(null);
      })
      .catch((error: unknown) => {
        if (!live || onErrorRef.current(error)) return;
        setLoadError(userFacingApiError(error));
      });
    return () => {
      live = false;
    };
  }, [engagementId, attempt]);

  /** Saves and refetches. Resolves to the error message, or null when saved (or the session ended). */
  async function save(next: RecalculationSettings, { quiet = false }: { quiet?: boolean } = {}): Promise<string | null> {
    setSaving(true);
    setSaveError(null);
    try {
      await onSaveInputs(next);
      setAttempt((n) => n + 1);
      return null;
    } catch (error) {
      if (onErrorRef.current(error)) return null;
      const message = `Not saved. ${userFacingApiError(error)}`;
      if (!quiet) setSaveError(message);
      return message;
    } finally {
      setSaving(false);
    }
  }

  if (!engagementId) {
    return (
      <section className="s1-content s1-vr">
        <div className="s1-ws-empty">
          <p>Pick or create an engagement in Setup to see its verification results.</p>
        </div>
      </section>
    );
  }
  if (loadError) {
    return (
      <section className="s1-content s1-vr">
        <div className="s1-ws-empty">
          <p>Could not load the recalculation. {loadError}</p>
          <button
            className="s1-button"
            type="button"
            onClick={() => {
              setLoadError(null);
              setAttempt((n) => n + 1);
            }}
          >
            Try again
          </button>
        </div>
      </section>
    );
  }
  // A result for the previously picked engagement is never shown for this one.
  if (!result || !reference || !live || result.engagement_id !== engagementId) {
    return (
      <section className="s1-content s1-vr">
        <p className="s1-muted s1-vr-status">Recalculating from reviewed evidence…</p>
      </section>
    );
  }

  const calculationProps = {
    engagementId: result.engagement_id,
    lines: result.calculation_lines ?? [],
    unplaced: result.calculation_unplaced,
    inputs: result.calculation_line_inputs,
    comparisons: result.comparisons,
    gwpSet: gwpLabel(result),
    settings: engagement.recalculation ?? {},
    onSave: (next: RecalculationSettings) => save(next, { quiet: true }),
    store,
    team: examinerOptions(engagement),
    signedInLogin: engagement.signedInLogin,
    onOpenDocument,
    onOpenEvidence,
  };

  return (
    <>
      <p className="s1-muted s1-vr-gwp" data-testid="results-gwp-set">
        GWP set: {gwpLabel(result)}
      </p>
      {(result.gwp_info ?? []).map((line) => (
        <p key={line} className="s1-muted s1-vr-gwp">
          {line}
        </p>
      ))}
      {result.gwp_blocked ? (
        <p className="s1-vw-red" role="alert">
          {result.gwp_blocked}
        </p>
      ) : null}
    <VerificationResults
      rows={[]}
      store={store}
      lines={live.lines}
      boxTotals={live.boxTotals}
      gasRows={live.gasRows}
      team={examinerOptions(engagement)}
      signedInLogin={engagement.signedInLogin}
      basis={resultsBasis(result)}
      onOpenDocument={onOpenDocument}
      registerFindings
      liveMateriality={result.tolerance_pct / 100}
      lineDetail={(line) => {
        const only = DRAWER_PANELS[line.id];
        // No line (and no unplaced record) in this panel: the drawer keeps its facility table.
        if (!only || !panelIds(result.calculation_lines ?? [], result.calculation_unplaced).includes(only)) return null;
        const reported = lineReported(line);
        const recomputed = lineRecomputed(line);
        return (
          <CalculationPanels
            only={only}
            totals={{ reported, recomputed, difference: reported === null || recomputed === null ? null : recomputed - reported }}
            {...calculationProps}
          />
        );
      }}
      panels={
        result.calculation_lines?.length ? (
          <CalculationPanels {...calculationProps} focusLineKey={focusLineKey} />
        ) : null
      }
      inputs={
        <>
          {uncountedMessage(result.uncounted_values) ? (
            <div className="s1-vr-status s1-vr-uncounted" role="status">
              <p>
                {uncountedMessage(result.uncounted_values)}
                {onOpenEvidenceTree ? (
                  <>
                    {" "}
                    <button className="s1-linklike" type="button" onClick={onOpenEvidenceTree}>
                      Open Evidence
                    </button>
                  </>
                ) : null}
              </p>
              <details>
                <summary>Why, and which documents</summary>
                <ul>
                  {uncountedGroups(result.uncounted_values).map((g) => (
                    <li key={g.reason}>
                      {pluralCount(g.records, "record", "records")}: {UNCOUNTED_REASON[g.reason]}. {uncountedHint(g.reason, g.records)}
                      <ul>
                        {g.documents.map((d) => (
                          <li key={d.document_id}>
                            {d.file_name} ({pluralCount(d.accepted_records, "record", "records")})
                          </li>
                        ))}
                      </ul>
                    </li>
                  ))}
                </ul>
              </details>
            </div>
          ) : null}
          {/* Folded, its count in the header: the boxes lead the page, as in the demo. */}
          {result.quality_checks ? <QualityChecksPanel checks={result.quality_checks} initiallyOpen={false} /> : null}
          <RecalculationInputs
            key={`${engagementId}:${attempt}`}
            result={result}
            reference={reference}
            settings={engagement.recalculation ?? {}}
            saving={saving}
            error={saveError}
            onSave={(next) => void save(next)}
          />
        </>
      }
    />
    </>
  );
}
