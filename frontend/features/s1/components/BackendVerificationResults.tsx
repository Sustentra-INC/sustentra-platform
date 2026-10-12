"use client";

import { useEffect, useRef, useState } from "react";

import {
  getRecalculation,
  getRecalculationReference,
  recalculationMateriality,
  recalculationRows,
  type Recalculation,
  type RecalculationReference,
} from "../api/recalculation";
import { userFacingApiError } from "../api/s1Backend";
import type { EngagementConfig, RecalculationSettings } from "../types";
import type { VerificationStore } from "../verification/verificationStore";
import { RecalculationInputs } from "./RecalculationInputs";
import { VerificationResults } from "./VerificationResults";

/**
 * Verification results in backend mode: the rows come from the engagement's
 * recalculation (reviewed evidence only), and its inputs are edited above them.
 */
export function BackendVerificationResults({
  engagement,
  store,
  onSaveInputs,
  onError,
}: {
  engagement: EngagementConfig;
  store: VerificationStore;
  /** Saves settings.recalculation on the engagement; rejects with the API error. */
  onSaveInputs: (next: RecalculationSettings) => Promise<void>;
  /** True when the error was handled (e.g. the session ended). */
  onError: (error: unknown) => boolean;
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

  async function save(next: RecalculationSettings) {
    setSaving(true);
    setSaveError(null);
    try {
      await onSaveInputs(next);
      setAttempt((n) => n + 1);
    } catch (error) {
      if (!onErrorRef.current(error)) setSaveError(`Not saved. ${userFacingApiError(error)}`);
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
  if (!result || !reference || result.engagement_id !== engagementId) {
    return (
      <section className="s1-content s1-vr">
        <p className="s1-muted s1-vr-status">Recalculating from reviewed evidence…</p>
      </section>
    );
  }

  return (
    <VerificationResults
      rows={recalculationRows(result)}
      store={store}
      materiality={recalculationMateriality(result)}
      inputs={
        <RecalculationInputs
          key={`${engagementId}:${attempt}`}
          result={result}
          reference={reference}
          settings={engagement.recalculation ?? {}}
          saving={saving}
          error={saveError}
          onSave={(next) => void save(next)}
        />
      }
    />
  );
}
