"use client";

import { useEffect, useMemo, useState } from "react";

import { FreeTextAnswer } from "./FreeTextAnswer";
import { InterviewField } from "./InterviewField";
import {
  BUTTON,
  BUTTON_LINK,
  CARD,
  CHOICE,
  CHOICE_OFF,
  CHOICE_ON,
  EYEBROW,
  MUTED,
  NOTICE_INFO
} from "./styles";
import type { FieldError, InterviewQuestion, SeedFormField } from "../../lib/intake-types";

interface QuestionCardProps {
  question: InterviewQuestion;
  errors: FieldError[];
  busy: boolean;
  /** Busy for long enough to be worth admitting to. See the interview page. */
  showBusy?: boolean;
  onAnswer: (answer: Record<string, unknown>, aiAssisted?: boolean) => void;
  onNotSure: () => void;
  onHandedOver: (message: string) => void;
}

function initialValues(question: InterviewQuestion): Record<string, unknown> {
  const values: Record<string, unknown> = {};
  for (const field of question.fields) {
    if (field.default_value !== undefined) values[field.field_id] = field.default_value;
  }
  return values;
}

function isRevealed(field: SeedFormField, values: Record<string, unknown>): boolean {
  if (!field.reveal_when) return true;
  return values[field.reveal_when.field] === field.reveal_when.equals;
}

export function QuestionCard({
  question,
  errors,
  busy,
  showBusy = false,
  onAnswer,
  onNotSure,
  onHandedOver
}: QuestionCardProps) {
  const [values, setValues] = useState<Record<string, unknown>>(() => initialValues(question));
  const [showExplainer, setShowExplainer] = useState(false);

  // A new question means a fresh answer sheet.
  useEffect(() => {
    setValues(initialValues(question));
    setShowExplainer(false);
  }, [question.datapoint_id, question.scope_ref]);

  const isScreening = question.answer_shape === "yes_no";
  const present = values.present;

  const visibleFields = useMemo(
    () => question.fields.filter((field) => isRevealed(field, values)),
    [question.fields, values]
  );

  function update(fieldId: string, value: unknown) {
    setValues((current) => ({ ...current, [fieldId]: value }));
  }

  function errorFor(fieldId: string) {
    return errors.find((error) => error.field === fieldId)?.message;
  }

  function answerScreening(answer: boolean) {
    const next = { ...values, present: answer };
    setValues(next);
    // "No" ends the question there; "Yes" usually reveals follow-ups.
    if (!answer) onAnswer({ present: false });
  }

  const showFollowUps = !isScreening || present === true;
  const canSubmit = !isScreening || present !== undefined;
  const hasFollowUps = showFollowUps && visibleFields.length > 0;

  return (
    // Keyed by question in the parent, so this whole block re-mounts and the
    // entry animation plays: one question giving way to the next, rather than
    // text swapping in place.
    <div className={`${CARD} intake-question`}>
      {question.scope_label ? (
        <p className={`mb-2 ${EYEBROW}`}>{question.scope_label}</p>
      ) : null}

      <h2 className="font-display text-2xl leading-snug">{question.question}</h2>

      <button
        type="button"
        className={`${BUTTON_LINK} mt-2 text-sm`}
        aria-expanded={showExplainer}
        onClick={() => setShowExplainer((open) => !open)}
      >
        What does this mean?
      </button>

      {showExplainer ? (
        <div className={`${NOTICE_INFO} intake-enter mt-3 mb-0`}>
          <p>{question.explainer}</p>
        </div>
      ) : null}

      <div className="mt-6">
        {isScreening ? (
          <div className="flex gap-3" role="group" aria-label="Yes or no">
            {[
              { label: "Yes", answer: true },
              { label: "No", answer: false }
            ].map((option) => (
              <button
                key={option.label}
                type="button"
                disabled={busy}
                aria-pressed={present === option.answer}
                onClick={() => answerScreening(option.answer)}
                className={`${CHOICE} ${
                  present === option.answer ? CHOICE_ON : CHOICE_OFF
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
        ) : null}

        {errorFor("present") ? (
          <p role="alert" className="mt-3 text-sm text-danger">
            {errorFor("present")}
          </p>
        ) : null}

        {/* Follow-ups unfold in sequence rather than appearing all at once. */}
        {hasFollowUps ? (
          <div className={`intake-reveal ${isScreening ? "mt-7" : ""}`}>
            {visibleFields.map((field) => (
              <InterviewField
                key={field.field_id}
                field={field}
                value={values[field.field_id]}
                error={errorFor(field.field_id)}
                onChange={update}
              />
            ))}
          </div>
        ) : null}
      </div>

      {question.fields.some((field) => field.input !== "derived") ? (
        <div className="mt-5">
          <FreeTextAnswer
            question={question}
            disabled={busy}
            onConfirm={(fields) => onAnswer({ ...values, ...fields }, true)}
            onHandedOver={onHandedOver}
          />
        </div>
      ) : null}

      <div className="mt-7 flex flex-wrap items-center gap-4">
        {showFollowUps ? (
          <button
            type="button"
            className={BUTTON}
            disabled={busy || !canSubmit}
            onClick={() => onAnswer(values)}
          >
            {showBusy ? "Saving…" : "Continue"}
          </button>
        ) : null}

        {question.not_sure_allowed ? (
          <button
            type="button"
            className={`${BUTTON_LINK} text-sm`}
            disabled={busy}
            onClick={onNotSure}
          >
            I&apos;m not sure
          </button>
        ) : null}
      </div>

      {/* Said once, on the first screen, by the page - not repeated on every
          card. Kept here only where it is genuinely the next thing to know. */}
      {question.not_sure_allowed && !hasFollowUps ? (
        <p className={`mt-3 ${MUTED}`}>Not sure is fine — we will find it out for you.</p>
      ) : null}
    </div>
  );
}
