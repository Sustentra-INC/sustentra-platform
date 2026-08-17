import type { ReactNode } from "react";

export const UNKNOWN_VALUE_CLASS = "s2-unknown-value";

export function isOneOf<T extends string>(value: string, allowed: readonly T[]): value is T {
  return allowed.includes(value as T);
}

export function UnknownValue({ value }: { value: unknown }) {
  const label = String(value);
  return (
    <span className={UNKNOWN_VALUE_CLASS} title={`Unrecognised value: ${label}`}>
      {label}
    </span>
  );
}

export function Truncate({ children, title }: { children: ReactNode; title?: string }) {
  const resolvedTitle = title ?? (typeof children === "string" ? children : undefined);
  return (
    <span className="s2-truncate" title={resolvedTitle}>
      {children}
    </span>
  );
}

