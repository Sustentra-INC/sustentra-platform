import type { ReactNode } from "react";

/** Which visual variant to use. */
export type BadgeVariant =
  | "indigo"      // --accent-soft bg, --brand-dark text; default
  | "on-indigo"   // white at 22% over an active nav item; white text
  | "neutral"     // --sf-inset bg, --ink-2 text
  | "danger";     // --state-blocking-bg, --state-blocking-fg

interface CountBadgeProps {
  children: ReactNode;
  variant?: BadgeVariant;
  "aria-label"?: string;
}

/**
 * Small pill that shows a number or short count label.
 * Heights 20px, fully round (--r-pill), token-sized font.
 *
 * Usage:
 *   <CountBadge>14</CountBadge>
 *   <CountBadge variant="danger">3</CountBadge>
 */
export function CountBadge({
  children,
  variant = "indigo",
  "aria-label": ariaLabel,
}: CountBadgeProps) {
  return (
    <span
      className={`s1-badge s1-badge--${variant}`}
      aria-label={ariaLabel}
    >
      {children}
    </span>
  );
}
