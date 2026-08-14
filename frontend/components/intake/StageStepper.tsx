"use client";

/**
 * Where the client is in the whole journey.
 *
 * The coverage meter answers "how far through this bit am I". It does not
 * answer the question people actually arrive with, which is "how much of this
 * is there". Three named stages answer that in one glance, from the first
 * screen.
 *
 * Only stages that exist are listed. Document upload belongs to the existing S1
 * pipeline and has no screen here yet, so it is not shown - a step a client can
 * never reach would be a promise we are not keeping.
 */

export type Stage = "details" | "questions" | "profile";

const STAGES: Array<{ id: Stage; label: string }> = [
  { id: "details", label: "Your details" },
  { id: "questions", label: "Questions" },
  { id: "profile", label: "Your profile" }
];

interface StageStepperProps {
  current: Stage;
}

export function StageStepper({ current }: StageStepperProps) {
  const index = STAGES.findIndex((stage) => stage.id === current);

  return (
    <nav aria-label="Progress through onboarding" className="mb-8">
      <ol className="flex list-none flex-wrap items-center gap-x-3 gap-y-2 p-0">
        {STAGES.map((stage, position) => {
          const done = position < index;
          const here = position === index;

          return (
            <li key={stage.id} className="flex items-center gap-3">
              <span
                aria-current={here ? "step" : undefined}
                className={`flex items-center gap-2 text-sm ${
                  here ? "font-semibold text-ink" : done ? "text-brand" : "text-ink-soft"
                }`}
              >
                <span
                  aria-hidden="true"
                  className={`flex h-6 w-6 items-center justify-center rounded-full border text-xs font-semibold ${
                    done
                      ? "border-brand bg-brand text-white"
                      : here
                        ? "border-brand text-brand"
                        : "border-line text-ink-soft"
                  }`}
                >
                  {done ? "✓" : position + 1}
                </span>
                {stage.label}
                {/* Stated for screen readers, which cannot see the tick. */}
                {done ? <span className="sr-only"> (done)</span> : null}
              </span>

              {position < STAGES.length - 1 ? (
                <span
                  aria-hidden="true"
                  className={`h-px w-6 ${done ? "bg-brand" : "bg-line"}`}
                />
              ) : null}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
