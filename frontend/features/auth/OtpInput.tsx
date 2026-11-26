"use client";
import { useRef, type KeyboardEvent, type ClipboardEvent } from "react";
import styles from "./auth.module.css";

interface OtpInputProps {
  length: number;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  hasError?: boolean;
}

export function OtpInput({ length, value, onChange, disabled, hasError }: OtpInputProps) {
  const refs = useRef<(HTMLInputElement | null)[]>([]);
  const digits = Array.from({ length }, (_, i) => value[i] ?? "");

  function focus(i: number) {
    refs.current[i]?.focus();
  }

  function handleChange(i: number, raw: string) {
    const digit = raw.replace(/\D/g, "").slice(-1);
    const next = digits.map((d, idx) => (idx === i ? digit : d)).join("");
    onChange(next);
    if (digit && i < length - 1) focus(i + 1);
  }

  function handleKeyDown(i: number, e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Backspace") {
      if (digits[i]) {
        onChange(digits.map((d, idx) => (idx === i ? "" : d)).join(""));
      } else if (i > 0) {
        onChange(digits.map((d, idx) => (idx === i - 1 ? "" : d)).join(""));
        focus(i - 1);
      }
      e.preventDefault();
    } else if (e.key === "ArrowLeft" && i > 0) {
      focus(i - 1);
      e.preventDefault();
    } else if (e.key === "ArrowRight" && i < length - 1) {
      focus(i + 1);
      e.preventDefault();
    }
  }

  function handlePaste(e: ClipboardEvent<HTMLInputElement>) {
    e.preventDefault();
    const pasted = e.clipboardData.getData("text").replace(/\D/g, "").slice(0, length);
    onChange(pasted);
    focus(Math.min(pasted.length, length - 1));
  }

  return (
    <fieldset
      className={styles.otpFieldset}
      style={{ "--otp-cols": length } as React.CSSProperties}
    >
      <legend className={`s1-field-label ${styles.otpLegend}`}>Verification code</legend>
      <div className={styles.otpGrid}>
        {Array.from({ length }, (_, i) => {
          const isTrailingEmpty = i > value.length;
          return (
            <input
              key={i}
              ref={(el) => {
                refs.current[i] = el;
              }}
              aria-label={`Digit ${i + 1}`}
              inputMode="numeric"
              maxLength={1}
              value={digits[i]}
              onChange={(e) => handleChange(i, e.target.value)}
              onKeyDown={(e) => handleKeyDown(i, e)}
              onPaste={handlePaste}
              disabled={disabled}
              autoFocus={i === 0}
              autoComplete={i === 0 ? "one-time-code" : "off"}
              className={[
                styles.otpBox,
                isTrailingEmpty ? styles.otpBoxEmpty : "",
                hasError ? styles.otpBoxError : "",
              ]
                .filter(Boolean)
                .join(" ")}
            />
          );
        })}
      </div>
    </fieldset>
  );
}
