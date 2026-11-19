"use client";

import { X } from "lucide-react";
import { useState } from "react";
import type { ClipboardEvent, KeyboardEvent } from "react";

import { NUMBER_FIELDS, addNumbers, type NumberKind } from "../utils/facilityNumbers";

/**
 * Optional account or meter numbers of one facility (provisional, see utils/facilityNumbers.ts).
 * Type one and press Enter, or paste a list separated by newlines, commas or semicolons. Each number
 * shows as a chip that can be removed.
 */
export function FacilityNumbersField({
  kind,
  facilityName,
  values,
  onChange,
}: {
  kind: NumberKind;
  facilityName: string;
  values: string[];
  onChange: (values: string[]) => void;
}) {
  const field = NUMBER_FIELDS[kind];
  const [draft, setDraft] = useState("");
  const [problem, setProblem] = useState<string | null>(null);

  function commit(text: string) {
    if (!text.trim()) {
      setProblem(null);
      setDraft("");
      return;
    }
    const result = addNumbers(values, text);
    if (result.values.length !== values.length) onChange(result.values);
    setProblem(result.problem);
    setDraft(result.problem ? text.trim() : "");
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" || e.key === ";" || e.key === ",") {
      e.preventDefault();
      commit(draft);
    }
  }

  function onPaste(e: ClipboardEvent<HTMLInputElement>) {
    const text = e.clipboardData.getData("text");
    if (/[\r\n,;]/.test(text)) {
      e.preventDefault();
      commit(`${draft}${text}`);
    }
  }

  const label = `${field.label} of ${facilityName || "facility"}`;
  return (
    <div className="s1-fac__numbers">
      <span className="s1-fac__numbers-label">
        {field.label} <span className="s1-muted">· optional</span>
      </span>
      {values.length ? (
        <ul className="s1-fac__chips" aria-label={label}>
          {values.map((value, index) => (
            <li className="s1-chip s1-fac__chip" key={`${value}-${index}`}>
              <span>{value}</span>
              <button
                type="button"
                className="s1-fac__chip-remove"
                aria-label={`Remove ${field.singular.toLowerCase()} number ${value}`}
                onClick={() => onChange(values.filter((_, i) => i !== index))}
              >
                <X aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      <input
        aria-label={`Add ${field.singular.toLowerCase()} number`}
        placeholder={field.placeholder}
        value={draft}
        onChange={(e) => {
          setDraft(e.target.value);
          if (problem) setProblem(null);
        }}
        onKeyDown={onKeyDown}
        onPaste={onPaste}
        onBlur={() => commit(draft)}
      />
      {problem ? (
        <span className="s1-fac__problem" role="alert">
          {problem}
        </span>
      ) : null}
    </div>
  );
}
