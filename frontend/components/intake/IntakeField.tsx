"use client";

import type { SeedFormField } from "../../lib/intake-types";

interface IntakeFieldProps {
  field: SeedFormField;
  value: string;
  error?: string;
  onChange: (fieldId: string, value: string) => void;
  idPrefix?: string;
}

const CONTROL =
  "w-full rounded-md border border-line bg-surface px-3 py-2.5 " +
  "focus:border-brand focus:ring-2 focus:ring-brand/25 focus:outline-none";

const CONTROL_ERROR = "border-danger focus:border-danger focus:ring-danger/25";

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

  const className = `${CONTROL}${error ? ` ${CONTROL_ERROR}` : ""}`;

  const shared = {
    id,
    name: id,
    value,
    className,
    "aria-invalid": error ? true : undefined,
    "aria-describedby": describedBy.length ? describedBy.join(" ") : undefined,
    onChange: (
      event: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>
    ) => onChange(field.field_id, event.target.value)
  };

  const isSelect = field.input === "select" && (field.options?.length ?? 0) > 0;

  return (
    <div className="mb-[1.15rem]">
      <label htmlFor={id} className="mb-1 block font-semibold">
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
        <textarea {...shared} className={`${className} min-h-20 resize-y`} />
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
        <p id={`${id}-error`} role="alert" className="mt-1.5 text-sm text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}
