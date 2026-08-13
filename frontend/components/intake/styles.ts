/**
 * Shared Tailwind class strings for the intake screens.
 *
 * Kept in one place so the screens stay consistent and a restyle is a single
 * edit rather than a hunt through five files.
 */

export const HEADING = "mb-1.5 text-2xl font-semibold tracking-tight";

export const LEDE = "mb-7 text-ink-soft";

export const CARD = "mb-5 rounded-lg border border-line bg-surface p-6";

export const SITE_BLOCK = "mb-4 rounded-lg border border-line bg-surface-soft p-5";

export const BUTTON =
  "rounded-md border border-brand bg-brand px-5 py-2.5 font-semibold text-white " +
  "hover:brightness-110 disabled:opacity-55 disabled:hover:brightness-100 " +
  "focus:ring-2 focus:ring-brand/40 focus:outline-none";

export const BUTTON_SECONDARY =
  "rounded-md border border-brand bg-transparent px-5 py-2.5 font-semibold text-brand " +
  "hover:bg-brand-soft focus:ring-2 focus:ring-brand/40 focus:outline-none";

export const BUTTON_LINK = "text-brand underline hover:no-underline";

export const NOTICE_INFO = "mb-5 rounded-lg border border-brand/25 bg-brand-soft px-4 py-3";

export const NOTICE_ERROR =
  "mb-5 rounded-lg border border-danger/25 bg-danger-soft px-4 py-3 text-danger";

export const NOTICE_FLAG =
  "mb-5 rounded-lg border border-flag/30 bg-flag-soft px-4 py-3 text-flag";

export const FIELD_GRID = "grid grid-cols-1 gap-x-4 sm:grid-cols-2";

export const MUTED = "text-sm text-ink-soft";
