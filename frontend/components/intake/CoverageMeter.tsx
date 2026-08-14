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
 *
 * Deliberately no time estimate. We have not measured how long this takes -
 * that is what the instrumentation phase is for - and a made-up "about 4
 * minutes" is the same sin as a made-up data field.
 *
 * The bar eases rather than jumps, so answering a question feels like it landed
 * somewhere. It is decoration in the honest sense: the number above it carries
 * the meaning, and a screen reader gets that number, not the animation.
 */
export function CoverageMeter({ coverage }: CoverageMeterProps) {
  const pct = coverage.total === 0 ? 0 : (coverage.complete / coverage.total) * 100;
  const left = Math.max(0, coverage.total - coverage.complete);

  return (
    <div className="mb-8">
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <span className="text-sm font-semibold">
          {left === 0
            ? "All done"
            : `${left} question${left === 1 ? "" : "s"} to go`}
        </span>
        {coverage.escalated > 0 ? (
          <span className="text-sm text-flag">{coverage.escalated} with our team</span>
        ) : null}
      </div>

      <div
        className="h-1.5 w-full overflow-hidden rounded-full bg-line"
        role="progressbar"
        aria-valuenow={coverage.complete}
        aria-valuemin={0}
        aria-valuemax={coverage.total}
        aria-valuetext={`${coverage.complete} of ${coverage.total} questions complete`}
        aria-label="Interview progress"
      >
        <div
          className="h-full rounded-full bg-brand transition-[width] duration-500 ease-out motion-reduce:transition-none"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
