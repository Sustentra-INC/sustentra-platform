"use client";

import { useState } from "react";

import { BUTTON, BUTTON_LINK, BUTTON_SECONDARY, MUTED, NOTICE_INFO } from "./styles";
import { parseFreeText } from "../../lib/api/intake";
import type { InterviewQuestion, ParseOutcome } from "../../lib/intake-types";

interface FreeTextAnswerProps {
  question: InterviewQuestion;
  disabled: boolean;
  /** Called when the client confirms the reading; the value is then saved normally. */
  onConfirm: (fields: Record<string, unknown>) => void;
  /** Called when the question was handed to the team instead. */
  onHandedOver: (message: string) => void;
}

/**
 * "Describe it in your own words."
 *
 * The typed answer is read, then **played back for the client to confirm** -
 * nothing is saved on their behalf. A reading we are not confident about
 * becomes one clarifying question; a second failure goes to a person.
 */
export function FreeTextAnswer({
  question,
  disabled,
  onConfirm,
  onHandedOver
}: FreeTextAnswerProps) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<ParseOutcome | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function read() {
    setBusy(true);
    setError(null);
    try {
      const response = await parseFreeText({
        datapoint_id: question.datapoint_id,
        scope_ref: question.scope_ref,
        text
      });
      setOutcome(response.outcome);
      if (response.outcome.status === "escalated") {
        onHandedOver(response.outcome.message ?? "We've passed that one to our team.");
        setOpen(false);
        setText("");
        setOutcome(null);
      }
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "We couldn't read that just now - you can use the fields above instead."
      );
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        className={`${BUTTON_LINK} text-sm`}
        disabled={disabled}
        onClick={() => setOpen(true)}
      >
        Prefer to describe it in your own words?
      </button>
    );
  }

  // A reading we are confident about: show it back before anything is saved.
  if (outcome?.status === "proposed") {
    return (
      <div className={NOTICE_INFO}>
        <p className="mb-1 font-semibold">Here&apos;s what we understood</p>
        <p className="mb-3">{outcome.summary}</p>
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            className={BUTTON}
            disabled={disabled}
            onClick={() => onConfirm(outcome.proposal)}
          >
            Yes, that&apos;s right
          </button>
          <button
            type="button"
            className={BUTTON_LINK}
            onClick={() => {
              setOutcome(null);
            }}
          >
            No, let me change it
          </button>
        </div>
        <p className={`mt-3 ${MUTED}`}>
          Nothing is saved until you confirm it.
        </p>
      </div>
    );
  }

  return (
    <div className="mt-2 rounded-lg border border-line bg-surface-soft p-4">
      <label htmlFor="free-text" className="mb-1 block font-semibold">
        In your own words
      </label>
      <p className={`mb-2 ${MUTED}`}>
        Write it however you would say it. We&apos;ll show you what we understood before
        saving anything.
      </p>

      {outcome?.status === "clarify" && outcome.clarifying_question ? (
        <div className={NOTICE_INFO}>
          <p>{outcome.clarifying_question}</p>
        </div>
      ) : null}

      {error ? (
        <p role="alert" className="mb-2 text-sm text-danger">
          {error}
        </p>
      ) : null}

      <textarea
        id="free-text"
        className="min-h-24 w-full resize-y rounded-md border border-line bg-surface px-3 py-2.5 focus:border-brand focus:ring-2 focus:ring-brand/25 focus:outline-none"
        value={text}
        onChange={(event) => setText(event.target.value)}
        placeholder="For example: about a dozen aircon units, the R-410A ones"
      />

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button
          type="button"
          className={BUTTON_SECONDARY}
          disabled={disabled || busy || text.trim().length === 0}
          onClick={read}
        >
          {busy ? "Reading..." : "Read my answer"}
        </button>
        <button
          type="button"
          className={BUTTON_LINK}
          onClick={() => {
            setOpen(false);
            setOutcome(null);
            setError(null);
          }}
        >
          Use the fields instead
        </button>
      </div>
    </div>
  );
}
