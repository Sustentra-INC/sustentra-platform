"use client";

import type { SeedFormField } from "../../lib/intake-types";

interface IntakeFieldProps {
  field: SeedFormField;
  value: string;
  error?: string;
  onChange: (fieldId: string, value: string) => void;
  idPrefix?: string;
}

/**
 * Renders one seed-form input from its config definition.
 *
 * Fields the client never answers (derived values) render nothing. Fields whose
 * permitted values are still awaiting expert sign-off render as free text and
 * say so, rather than offering invented options.
 */
export function IntakeField({ field, value, error, onChange, idPrefix = "" }: IntakeFieldProps) {
  if (field.input === "derived") return null;

  const id = `${idPrefix}${field.field_id}`;
  const describedBy: string[] = [];
  if (field.help) describedBy.push(`${id}-help`);
  if (error) describedBy.push(`${id}-error`);

  const shared = {
    id,
    name: id,
    value,
    "aria-invalid": error ? true : undefined,
    "aria-describedby": describedBy.length ? describedBy.join(" ") : undefined,
    onChange: (
      event: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>
    ) => onChange(field.field_id, event.target.value)
  };

  const isSelect = field.input === "select" && (field.options?.length ?? 0) > 0;

  return (
    <div className={`intake-field${error ? " has-error" : ""}`}>
      <label htmlFor={id}>
        {field.label}
        {!field.required ? <span className="optional-tag"> (optional)</span> : null}
        {field.provisional ? (
          <span
            className="provisional-tag"
            title={field.provisional_reason ?? "Awaiting expert sign-off"}
          >
            awaiting sign-off
          </span>
        ) : null}
      </label>

      {field.help ? (
        <p className="help" id={`${id}-help`}>
          {field.help}
        </p>
      ) : null}

      {isSelect ? (
        <select {...shared}>
          <option value="">Select...</option>
          {field.options?.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      ) : field.input === "textarea" ? (
        <textarea {...shared} />
      ) : (
        <input
          {...shared}
          type={
            field.input === "email"
              ? "email"
              : field.input === "number"
                ? "number"
                : field.input === "date"
                  ? "date"
                  : "text"
          }
        />
      )}

      {error ? (
        <p className="field-error" id={`${id}-error`} role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
