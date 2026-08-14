"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import {
  BUTTON_LINK,
  CARD,
  HEADING,
  LEDE,
  MUTED,
  NOTICE_ERROR,
  NOTICE_FLAG,
  NOTICE_INFO
} from "../../../components/intake/styles";
import { getReviewQueue } from "../../../lib/api/intake-review";
import { waitedFor } from "../../../lib/intake-format";
import type { ReviewQueue } from "../../../lib/intake-types";

type Phase = "loading" | "ready" | "unauthenticated" | "forbidden" | "error";

/** Plain-language reasons, so the queue reads without knowing the trigger names. */
const TRIGGER_LABEL: Record<string, string> = {
  human_class_datapoint: "Needs a person to confirm",
  failed_clarification: "They tried twice and could not answer",
  user_requested_help: "They asked us for help",
  contradiction: "Conflicts with an earlier answer",
  condition_met: "Their answers sent it to us"
};

export default function ReviewQueuePage() {
  const [phase, setPhase] = useState<Phase>("loading");
  const [queue, setQueue] = useState<ReviewQueue | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setQueue(await getReviewQueue());
      setPhase("ready");
    } catch (caught) {
      const text = caught instanceof Error ? caught.message : "Could not load the queue.";
      if (text.toLowerCase().includes("sign-in")) {
        setPhase("unauthenticated");
      } else if (text.includes("Sustentra staff")) {
        setPhase("forbidden");
      } else {
        setMessage(text);
        setPhase("error");
      }
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (phase === "loading") {
    return (
      <section>
        <h1 className={HEADING}>Review queue</h1>
        <p className={LEDE}>Loading what is waiting.</p>
      </section>
    );
  }

  if (phase === "unauthenticated") {
    return (
      <section>
        <h1 className={HEADING}>Please sign in</h1>
        <p className={LEDE}>The review queue needs a signed-in Sustentra account.</p>
        <Link href="/intake/login" className={BUTTON_LINK}>
          Go to sign in
        </Link>
      </section>
    );
  }

  if (phase === "forbidden") {
    return (
      <section>
        <h1 className={HEADING}>Not your screen</h1>
        <p className={LEDE}>
          The review queue is for the Sustentra team. If you are a client, your questions are
          on your interview screen.
        </p>
        <Link href="/intake/interview" className={BUTTON_LINK}>
          Back to your questions
        </Link>
      </section>
    );
  }

  if (phase === "error" || !queue) {
    return (
      <section>
        <h1 className={HEADING}>Review queue</h1>
        <div className={NOTICE_ERROR} role="alert">
          <p>{message ?? "Could not load the queue."}</p>
        </div>
      </section>
    );
  }

  const late = queue.items.filter((item) => item.past_sla);

  return (
    <section>
      <h1 className={HEADING}>Review queue</h1>
      <p className={LEDE}>
        Questions clients could not answer, oldest first. Each one has been promised an answer
        within {queue.sla_hours} hours.
      </p>

      {late.length > 0 ? (
        <div className={NOTICE_FLAG}>
          <p>
            <strong>
              {late.length} question{late.length === 1 ? " is" : "s are"} past the{" "}
              {queue.sla_hours}-hour promise.
            </strong>{" "}
            They are at the top of the list.
          </p>
        </div>
      ) : null}

      {queue.count === 0 ? (
        <div className={NOTICE_INFO}>
          <p>Nothing is waiting. Every client question has been answered.</p>
        </div>
      ) : (
        <ol className="list-none p-0">
          {queue.items.map((item) => (
            <li key={item.escalation_id}>
              <Link
                href={`/intake/review/${item.escalation_id}`}
                className={`${CARD} block no-underline hover:border-brand`}
              >
                <div className="mb-1 flex flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold tracking-wide text-brand uppercase">
                    {item.client}
                  </span>
                  {item.site ? <span className={MUTED}>{item.site}</span> : null}
                  {item.past_sla ? (
                    <span className="rounded-full bg-flag-soft px-2 py-0.5 text-xs font-semibold text-flag">
                      past {queue.sla_hours}h
                    </span>
                  ) : null}
                </div>

                <p className="mb-1 text-lg font-semibold text-ink">{item.question}</p>
                <p className={MUTED}>
                  {item.why ?? TRIGGER_LABEL[item.trigger] ?? item.trigger.replace(/_/g, " ")} -
                  came in {waitedFor(item.hours_open)}
                </p>
              </Link>
            </li>
          ))}
        </ol>
      )}

      <p className={`mt-2 ${MUTED}`}>
        {queue.count} open. Digest and reminder emails are sent on a schedule, so nothing
        depends on this screen being open.
      </p>

      <p className="mt-4">
        <Link href="/intake/review/metrics" className={BUTTON_LINK}>
          How onboarding is going
        </Link>
      </p>
    </section>
  );
}
