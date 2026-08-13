"use client";

import type { Coverage } from "../../lib/intake-types";

interface CoverageMeterProps {
  coverage: Coverage;
}

/**
 * Progress through the interview.
 *
 * Shown as "14 of 22", not a percentage: the total genuinely moves as answers
 * come in, and a percentage that slides backwards reads as a bug rather than as
 * honesty about how much is left.
 */
export function CoverageMeter({ coverage }: CoverageMeterProps) {
  const pct = coverage.total === 0 ? 0 : (coverage.complete / coverage.total) * 100;

  return (
    <div className="mb-6 rounded-lg border border-line bg-surface-soft p-4">
      <div className="mb-2 flex items-baseline justify-between">
        <span className="font-semibold">{coverage.label}</span>
        {coverage.escalated > 0 ? (
          <span className="text-sm text-flag">
            {coverage.escalated} with our team
          </span>
        ) : null}
      </div>

      <div
        className="h-2 w-full overflow-hidden rounded-full bg-line"
        role="progressbar"
        aria-valuenow={coverage.complete}
        aria-valuemin={0}
        aria-valuemax={coverage.total}
        aria-label="Interview progress"
      >
        <div
          className="h-full rounded-full bg-brand transition-all duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>

      <p className="mt-2 text-sm text-ink-soft">{coverage.note}</p>
    </div>
  );
}
