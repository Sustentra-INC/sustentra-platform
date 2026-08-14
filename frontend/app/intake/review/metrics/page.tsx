"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import {
  BUTTON_LINK,
  CARD,
  HEADING,
  LEDE,
  MUTED,
  NOTICE_ERROR,
  SECTION_TITLE
} from "../../../../components/intake/styles";
import { getMetrics } from "../../../../lib/api/intake-metrics";
import type { ClientJourney, MetricsSummary } from "../../../../lib/intake-types";

type Phase = "loading" | "ready" | "forbidden" | "error";

function hours(value: number | null): string {
  if (value === null) return "—";
  if (value < 48) return `${value.toFixed(1)} hours`;
  return `${(value / 24).toFixed(1)} days`;
}

function percent(value: number | null): string {
  return value === null ? "—" : `${Math.round(value)}%`;
}

/** One headline number. The caption carries the meaning, not the figure. */
function Figure({
  value,
  label,
  note
}: {
  value: string;
  label: string;
  note?: string;
}) {
  return (
    <div className="mb-6">
      <p className="font-display text-4xl leading-none">{value}</p>
      <p className="mt-2 font-semibold">{label}</p>
      {note ? <p className={MUTED}>{note}</p> : null}
    </div>
  );
}

function clientState(item: ClientJourney): string {
  if (!item.started_at) return "Not started";
  if (item.is_complete) return `Finished in ${hours(item.hours_to_complete)}`;
  return `${item.datapoints_settled} of ${item.datapoints_total} answered`;
}

export default function MetricsPage() {
  const [phase, setPhase] = useState<Phase>("loading");
  const [metrics, setMetrics] = useState<MetricsSummary | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    getMetrics()
      .then((loaded) => {
        if (cancelled) return;
        setMetrics(loaded);
        setPhase("ready");
      })
      .catch((caught: unknown) => {
        if (cancelled) return;
        const text = caught instanceof Error ? caught.message : "Could not load.";
        setMessage(text);
        setPhase(text.includes("Sustentra staff") ? "forbidden" : "error");
      });

    return () => {
      cancelled = true;
    };
  }, []);

  if (phase === "loading") {
    return (
      <section>
        <h1 className={HEADING}>How onboarding is going</h1>
        <p className={LEDE}>Working it out.</p>
      </section>
    );
  }

  if (phase === "forbidden") {
    return (
      <section>
        <h1 className={HEADING}>Not your screen</h1>
        <p className={LEDE}>These numbers are for the Sustentra team.</p>
      </section>
    );
  }

  if (!metrics) {
    return (
      <section>
        <h1 className={HEADING}>How onboarding is going</h1>
        <div className={NOTICE_ERROR} role="alert">
          <p>{message ?? "Could not load the numbers."}</p>
        </div>
      </section>
    );
  }

  return (
    <section className="intake-enter">
      <Link href="/intake/review" className={`${BUTTON_LINK} text-sm`}>
        &larr; Back to the queue
      </Link>

      <h1 className={`${HEADING} mt-3`}>How onboarding is going</h1>
      <p className={LEDE}>
        {metrics.clients_complete} of {metrics.clients_started} clients who started have
        finished.
      </p>

      <div className={CARD}>
        {/* The one that measures onboarding leads. */}
        <Figure
          value={percent(metrics.no_stuck_rate)}
          label="Completed without getting stuck"
          note="No contradiction, no failed attempt, no request for help."
        />
        <Figure
          value={hours(metrics.median_hours_to_complete)}
          label="Median time to complete"
          note="From first sign-in until the last question is resolved."
        />
        <Figure
          value={percent(metrics.zero_escalation_rate)}
          label="Completed with no escalations at all"
          note="The literal wording of the spec. It counts the routine confirmations every client generates by design, so expect it to read low."
        />

        {metrics.clients_complete > 0 ? (
          <p className={MUTED}>
            Fastest {hours(metrics.fastest_hours)}, slowest {hours(metrics.slowest_hours)}.
          </p>
        ) : null}
      </div>

      {/* Sample size is stated next to the numbers, not buried underneath. */}
      {!metrics.enough_data ? (
        <div className="mb-6 rounded-lg bg-flag-soft px-5 py-4 text-flag">
          <p>
            <strong>
              {metrics.sample_size === 0
                ? "No client has finished yet."
                : `Based on ${metrics.sample_size} finished client${
                    metrics.sample_size === 1 ? "" : "s"
                  }.`}
            </strong>{" "}
            Read these as individual cases, not as a trend — a median needs at least{" "}
            {metrics.minimum_sample}.
          </p>
        </div>
      ) : null}

      <div className={CARD}>
        <h2 className={`${SECTION_TITLE} mb-3`}>Every client</h2>
        {metrics.clients.length === 0 ? (
          <p className={MUTED}>No clients yet.</p>
        ) : (
          <ul className="list-none p-0">
            {metrics.clients.map((item) => (
              <li key={item.org_id} className="border-t border-line py-3 first:border-t-0">
                <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                  <span className="font-semibold">{item.legal_name ?? item.org_id}</span>
                  <span className={MUTED}>{clientState(item)}</span>
                </div>
                <p className={MUTED}>
                  {item.escalations_open > 0
                    ? `${item.escalations_open} waiting on us · `
                    : ""}
                  {item.escalations_routine} routine
                  {item.got_stuck ? (
                    <span className="text-flag">
                      {" "}
                      · got stuck {item.escalations_stuck}{" "}
                      {item.escalations_stuck === 1 ? "time" : "times"}
                    </span>
                  ) : null}
                </p>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className={CARD}>
        <h2 className={`${SECTION_TITLE} mb-3`}>Read this with care</h2>
        <ul className="list-disc pl-5">
          {metrics.caveats.map((note, index) => (
            <li key={index} className="mb-1">
              {note}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
