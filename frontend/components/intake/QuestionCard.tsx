"use client";

import { useEffect, useMemo, useState } from "react";

import { InterviewField } from "./InterviewField";
import { BUTTON, BUTTON_LINK, CARD, MUTED, NOTICE_INFO } from "./styles";
import type { FieldError, InterviewQuestion, SeedFormField } from "../../lib/intake-types";

interface QuestionCardProps {
  question: InterviewQuestion;
  errors: FieldError[];
  busy: boolean;
  onAnswer: (answer: Record<string, unknown>) => void;
  onNotSure: () => void;
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
  onAnswer,
  onNotSure
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

  return (
    <div className={CARD}>
      {question.scope_label ? (
        <p className="mb-1 text-sm font-semibold tracking-wide text-brand uppercase">
          {question.scope_label}
        </p>
      ) : null}

      <h2 className="mb-2 text-xl font-semibold">{question.question}</h2>

      <button
        type="button"
        className={`${BUTTON_LINK} text-sm`}
        aria-expanded={showExplainer}
        onClick={() => setShowExplainer((open) => !open)}
      >
        What does this mean?
      </button>

      {showExplainer ? (
        <div className={`${NOTICE_INFO} mt-3`}>
          <p>{question.explainer}</p>
        </div>
      ) : null}

      <div className="mt-5">
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
                onClick={() => answerScreening(option.answer)}
                className={`rounded-md border px-6 py-2.5 font-semibold ${
                  present === option.answer
                    ? "border-brand bg-brand text-white"
                    : "border-line bg-surface hover:border-brand"
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
        ) : null}

        {errorFor("present") ? (
          <p role="alert" className="mb-4 text-sm text-danger">
            {errorFor("present")}
          </p>
        ) : null}

        {showFollowUps
          ? visibleFields.map((field) => (
              <InterviewField
                key={field.field_id}
                field={field}
                value={values[field.field_id]}
                error={errorFor(field.field_id)}
                onChange={update}
              />
            ))
          : null}
      </div>

      <div className="mt-6 flex flex-wrap items-center gap-3">
        {showFollowUps ? (
          <button
            type="button"
            className={BUTTON}
            disabled={busy || !canSubmit}
            onClick={() => onAnswer(values)}
          >
            {busy ? "Saving..." : "Save and continue"}
          </button>
        ) : null}

        {question.not_sure_allowed ? (
          <button type="button" className={BUTTON_LINK} disabled={busy} onClick={onNotSure}>
            I&apos;m not sure
          </button>
        ) : null}
      </div>

      <p className={`mt-3 ${MUTED}`}>
        Not sure is fine - we will find the answer for you and keep going.
      </p>
    </div>
  );
}
