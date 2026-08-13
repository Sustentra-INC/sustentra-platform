"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { InterviewField } from "../../../../components/intake/InterviewField";
import {
  BUTTON,
  BUTTON_LINK,
  CARD,
  HEADING,
  LEDE,
  MUTED,
  NOTICE_ERROR,
  NOTICE_FLAG,
  NOTICE_INFO
} from "../../../../components/intake/styles";
import { getEscalation, resolveEscalation } from "../../../../lib/api/intake-review";
import { openFor, readableTime } from "../../../../lib/intake-format";
import type { EscalationDetail, SeedFormField } from "../../../../lib/intake-types";

type Phase = "loading" | "ready" | "resolved" | "forbidden" | "error";

function isRevealed(field: SeedFormField, values: Record<string, unknown>): boolean {
  if (!field.reveal_when) return true;
  return values[field.reveal_when.field] === field.reveal_when.equals;
}

function describe(value: unknown): string {
  if (value === null || value === undefined) return "-";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .map(([key, item]) => `${key.replace(/_/g, " ")}: ${describe(item)}`)
      .join(", ");
  }
  return String(value);
}

export default function EscalationPage() {
  const params = useParams<{ escalationId: string }>();
  const router = useRouter();
  const escalationId = params.escalationId;

  const [phase, setPhase] = useState<Phase>("loading");
  const [detail, setDetail] = useState<EscalationDetail | null>(null);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [note, setNote] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;

    getEscalation(escalationId)
      .then((found) => {
        if (cancelled) return;
        setDetail(found);
        // Whatever the client managed to say is the starting point, so a
        // reviewer confirms rather than retypes.
        setValues(found.current_value ?? {});
        setPhase(found.status === "resolved" ? "resolved" : "ready");
      })
      .catch((caught: unknown) => {
        if (cancelled) return;
        const text = caught instanceof Error ? caught.message : "Could not load it.";
        setMessage(text);
        setPhase(text.includes("Sustentra staff") ? "forbidden" : "error");
      });

    return () => {
      cancelled = true;
    };
  }, [escalationId]);

  // One list, oldest first: what happened to the answer and what happened to
  // the ticket are the same story from a reviewer's point of view.
  const timeline = useMemo(() => {
    if (!detail) return [];
    const entries = [
      ...detail.audit_trail.map((entry) => ({
        at: entry.at,
        text: `${entry.action} by ${entry.actor_id}${entry.note ? ` (${entry.note})` : ""}`
      })),
      ...detail.history.map((entry) => ({
        at: entry.at,
        text:
          entry.from === null || entry.from === undefined || entry.from === ""
            ? `${entry.field ?? "value"} set to ${describe(entry.to)} (${entry.actor})`
            : `${entry.field ?? "value"} ${describe(entry.from)} → ${describe(entry.to)} (${
                entry.actor
              })`
      }))
    ];
    return entries.sort((left, right) => left.at.localeCompare(right.at));
  }, [detail]);

  // trigger_reason is already shown as "Why it came to us", and a blank field
  // is worse than no field.
  const companyDetails = useMemo(
    () =>
      Object.entries(detail?.seed_context ?? {}).filter(
        ([key, value]) => key !== "trigger_reason" && value !== null && value !== ""
      ),
    [detail]
  );

  const fields = detail?.answer_fields ?? [];
  const isScreening = detail?.answer_shape === "yes_no";
  const visibleFields = useMemo(
    () => fields.filter((field) => isRevealed(field, values)),
    [fields, values]
  );

  function update(fieldId: string, value: unknown) {
    setValues((current) => ({ ...current, [fieldId]: value }));
  }

  async function onResolve() {
    setBusy(true);
    setMessage(null);
    try {
      await resolveEscalation(escalationId, {
        value: values,
        resolution_note: note.trim() || undefined
      });
      router.push("/intake/review");
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : "Could not save that answer.");
      setBusy(false);
    }
  }

  if (phase === "loading") {
    return (
      <section>
        <h1 className={HEADING}>Opening the question</h1>
        <p className={LEDE}>One moment.</p>
      </section>
    );
  }

  if (phase === "forbidden") {
    return (
      <section>
        <h1 className={HEADING}>Not your screen</h1>
        <p className={LEDE}>Only the Sustentra team can answer escalated questions.</p>
      </section>
    );
  }

  if (!detail) {
    return (
      <section>
        <h1 className={HEADING}>Could not open it</h1>
        <div className={NOTICE_ERROR} role="alert">
          <p>{message ?? "That escalation does not exist."}</p>
        </div>
        <Link href="/intake/review" className={BUTTON_LINK}>
          Back to the queue
        </Link>
      </section>
    );
  }

  const answered = Object.keys(values).length > 0;

  return (
    <section>
      <Link href="/intake/review" className={`${BUTTON_LINK} text-sm`}>
        &larr; Back to the queue
      </Link>

      <h1 className={`${HEADING} mt-3`}>{detail.question}</h1>
      <p className={LEDE}>
        {detail.client}
        {detail.site ? ` - ${detail.site}` : ""} - waiting {openFor(detail.hours_open)}
      </p>

      {detail.past_sla ? (
        <div className={NOTICE_FLAG}>
          <p>This one is past the promise made to the client.</p>
        </div>
      ) : null}

      {phase === "resolved" ? (
        <div className={NOTICE_INFO}>
          <p>
            Already answered: {describe(detail.resolution_value)}
            {detail.resolution_note ? ` - ${detail.resolution_note}` : ""}
          </p>
        </div>
      ) : null}

      {message ? (
        <div className={NOTICE_ERROR} role="alert">
          <p>{message}</p>
        </div>
      ) : null}

      {/* What the reviewer needs, so nobody has to open another screen. */}
      <div className={CARD}>
        <h2 className="mb-3 text-lg font-semibold">Why it came to us</h2>
        <p className="mb-4">{detail.why ?? detail.trigger.replace(/_/g, " ")}</p>

        {detail.explainer ? (
          <>
            <h3 className="mb-1 text-sm font-semibold tracking-wide text-brand uppercase">
              What the client was told this means
            </h3>
            <p className="mb-4">{detail.explainer}</p>
          </>
        ) : null}

        <h3 className="mb-1 text-sm font-semibold tracking-wide text-brand uppercase">
          What they tried
        </h3>
        {detail.attempts.length === 0 ? (
          <p className={`mb-4 ${MUTED}`}>Nothing recorded.</p>
        ) : (
          <ul className="mb-4 list-disc pl-5">
            {detail.attempts.map((attempt, index) => (
              <li key={index}>{describe(attempt)}</li>
            ))}
          </ul>
        )}

        <h3 className="mb-1 text-sm font-semibold tracking-wide text-brand uppercase">
          Their company details
        </h3>
        <dl className="grid grid-cols-1 gap-x-6 sm:grid-cols-2">
          {companyDetails.map(([key, value]) => (
            <div key={key} className="mb-1 flex gap-2">
              <dt className={MUTED}>{key.replace(/_/g, " ")}</dt>
              <dd>{describe(value)}</dd>
            </div>
          ))}
        </dl>
      </div>

      {phase === "ready" ? (
        <div className={CARD}>
          <h2 className="mb-4 text-lg font-semibold">Your answer</h2>

          {isScreening ? (
            <div className="mb-5 flex gap-2" role="group" aria-label="Yes or no">
              {[
                { label: "Yes", answer: true },
                { label: "No", answer: false }
              ].map((option) => (
                <button
                  key={option.label}
                  type="button"
                  disabled={busy}
                  onClick={() => update("present", option.answer)}
                  className={`rounded-md border px-6 py-2.5 font-semibold ${
                    values.present === option.answer
                      ? "border-brand bg-brand text-white"
                      : "border-line bg-surface hover:border-brand"
                  }`}
                >
                  {option.label}
                </button>
              ))}
            </div>
          ) : null}

          {(!isScreening || values.present === true) &&
            visibleFields.map((field) => (
              <InterviewField
                key={field.field_id}
                field={field}
                value={values[field.field_id]}
                onChange={update}
              />
            ))}

          <label className="mt-2 block" htmlFor="resolution-note">
            <span className="mb-1 block font-semibold">
              How you know (kept on the record)
            </span>
            <textarea
              id="resolution-note"
              rows={3}
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder="e.g. Confirmed by phone with the facilities manager, 14 Aug."
              className="w-full rounded-md border border-line bg-surface px-3 py-2.5 focus:border-brand focus:ring-2 focus:ring-brand/25 focus:outline-none"
            />
          </label>

          <div className="mt-5 flex flex-wrap items-center gap-3">
            <button
              type="button"
              className={BUTTON}
              disabled={busy || !answered}
              onClick={onResolve}
            >
              {busy ? "Saving..." : "Save answer and tell the client"}
            </button>
            <Link href="/intake/review" className={BUTTON_LINK}>
              Not now
            </Link>
          </div>

          <p className={`mt-3 ${MUTED}`}>
            This is written into the client&apos;s profile as answered by the team, with your
            name against it, and they are emailed that it is done.
          </p>
        </div>
      ) : null}

      {/* The audit trail, because a team answer must be as traceable as a client one. */}
      <div className={CARD}>
        <h2 className="mb-3 text-lg font-semibold">History</h2>
        <ul className="list-none p-0">
          {timeline.map((entry, index) => (
            <li key={index} className="mb-1">
              <span className={MUTED}>{readableTime(entry.at)}</span> - {entry.text}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
