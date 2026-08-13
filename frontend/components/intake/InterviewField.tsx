"use client";

import type { SeedFormField } from "../../lib/intake-types";

interface InterviewFieldProps {
  field: SeedFormField;
  value: unknown;
  error?: string;
  onChange: (fieldId: string, value: unknown) => void;
}

const CONTROL =
  "w-full rounded-md border border-line bg-surface px-3 py-2.5 " +
  "focus:border-brand focus:ring-2 focus:ring-brand/25 focus:outline-none";

/**
 * One interview answer field.
 *
 * Richer than the seed form's IntakeField because interview answers are not all
 * strings: screening follow-ups are booleans and several questions collect a
 * short list of names.
 */
export function InterviewField({ field, value, error, onChange }: InterviewFieldProps) {
  const id = `q-${field.field_id}`;
  const describedBy = [field.help ? `${id}-help` : null, error ? `${id}-error` : null]
    .filter(Boolean)
    .join(" ");

  function renderControl() {
    if (field.input === "yes_no") {
      return (
        <div className="flex gap-2" role="group" aria-labelledby={`${id}-label`}>
          {[
            { label: "Yes", answer: true },
            { label: "No", answer: false }
          ].map((option) => (
            <button
              key={option.label}
              type="button"
              onClick={() => onChange(field.field_id, option.answer)}
              className={`rounded-md border px-4 py-2 font-semibold ${
                value === option.answer
                  ? "border-brand bg-brand text-white"
                  : "border-line bg-surface hover:border-brand"
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>
      );
    }

    if (field.input === "list") {
      const items = Array.isArray(value) ? (value as string[]) : [""];
      return (
        <div className="grid gap-2">
          {items.map((item, index) => (
            <div key={index} className="flex gap-2">
              <input
                className={CONTROL}
                value={item}
                placeholder={field.item_label ?? "Add one"}
                onChange={(event) => {
                  const next = [...items];
                  next[index] = event.target.value;
                  onChange(field.field_id, next);
                }}
              />
              {items.length > 1 ? (
                <button
                  type="button"
                  className="text-brand underline"
                  onClick={() =>
                    onChange(
                      field.field_id,
                      items.filter((_, position) => position !== index)
                    )
                  }
                >
                  Remove
                </button>
              ) : null}
            </div>
          ))}
          <button
            type="button"
            className="justify-self-start text-brand underline"
            onClick={() => onChange(field.field_id, [...items, ""])}
          >
            Add another
          </button>
        </div>
      );
    }

    if (field.input === "select") {
      return (
        <select
          id={id}
          className={CONTROL}
          value={(value as string) ?? ""}
          aria-describedby={describedBy || undefined}
          onChange={(event) => onChange(field.field_id, event.target.value)}
        >
          <option value="">Select...</option>
          {field.options?.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      );
    }

    if (field.input === "textarea") {
      return (
        <textarea
          id={id}
          className={`${CONTROL} min-h-20 resize-y`}
          value={(value as string) ?? ""}
          aria-describedby={describedBy || undefined}
          onChange={(event) => onChange(field.field_id, event.target.value)}
        />
      );
    }

    return (
      <input
        id={id}
        type={field.input === "number" ? "number" : field.input === "date" ? "date" : "text"}
        className={`${CONTROL}${error ? " border-danger" : ""}`}
        value={(value as string) ?? ""}
        aria-describedby={describedBy || undefined}
        onChange={(event) => onChange(field.field_id, event.target.value)}
      />
    );
  }

  return (
    <div className="mb-5">
      <label id={`${id}-label`} htmlFor={id} className="mb-1 block font-semibold">
        {field.label}
        {!field.required ? (
          <span className="text-sm font-normal text-ink-soft"> (optional)</span>
        ) : null}
        {field.provisional ? (
          <span
            className="ml-1.5 inline-block rounded-full bg-flag-soft px-2 py-0.5 align-middle text-[0.72rem] font-semibold text-flag"
            title={field.provisional_reason ?? "Awaiting expert sign-off"}
          >
            awaiting sign-off
          </span>
        ) : null}
      </label>

      {field.help ? (
        <p id={`${id}-help`} className="mb-1.5 text-sm text-ink-soft">
          {field.help}
        </p>
      ) : null}

      {renderControl()}

      {error ? (
        <p id={`${id}-error`} role="alert" className="mt-1.5 text-sm text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}
