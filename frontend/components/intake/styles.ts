/**
 * Shared Tailwind class strings for the intake screens.
 *
 * Kept in one place so the screens stay consistent and a restyle is a single
 * edit rather than a hunt through five files.
 *
 * Two rules this set follows deliberately:
 *
 * 1. **Not everything is a card.** Boxing every block flattens the page - the
 *    eye has nowhere to land. Cards are for things a client acts on; everything
 *    else is plain text separated by space and a rule.
 * 2. **Space does the work.** The old set leaned on borders to separate
 *    content. Whitespace separates it more calmly and reads less like a form
 *    generator.
 */

export const HEADING = "mb-2 text-[1.75rem] leading-tight font-normal text-ink";

export const LEDE = "mb-8 text-ink-soft";

/** For things a client acts on. Not for every block of text. */
export const CARD = "mb-5 rounded-xl border border-line bg-surface p-7 shadow-[0_1px_2px_rgba(22,36,31,0.04)]";

/** For read-only blocks: a rule and space, no box. */
export const SECTION = "mb-9 border-t border-line-soft pt-6";

export const SECTION_TITLE = "mb-1 font-display text-xl";

export const SITE_BLOCK = "mb-4 rounded-lg bg-surface-soft p-5";

export const BUTTON =
  "intake-pressable rounded-lg border border-brand bg-brand px-6 py-3 font-semibold text-white " +
  "hover:bg-brand-deep hover:border-brand-deep disabled:opacity-50 " +
  "focus-visible:ring-2 focus-visible:ring-brand/40 focus-visible:outline-none";

export const BUTTON_SECONDARY =
  "intake-pressable rounded-lg border border-line bg-surface px-6 py-3 font-semibold text-ink " +
  "hover:border-brand hover:text-brand " +
  "focus-visible:ring-2 focus-visible:ring-brand/40 focus-visible:outline-none";

export const BUTTON_LINK =
  "text-brand underline underline-offset-2 hover:no-underline focus-visible:outline-none " +
  "focus-visible:ring-2 focus-visible:ring-brand/40 rounded-sm";

/** The big yes/no pair. Sized for confidence, not for a form. */
export const CHOICE =
  "intake-pressable min-w-28 rounded-lg border px-7 py-3.5 text-lg font-semibold";

export const CHOICE_ON = "border-brand bg-brand text-white";

export const CHOICE_OFF = "border-line bg-surface hover:border-brand hover:text-brand";

export const NOTICE_INFO = "mb-6 rounded-lg bg-brand-soft px-5 py-4";

export const NOTICE_ERROR =
  "mb-6 rounded-lg border border-danger/20 bg-danger-soft px-5 py-4 text-danger";

export const NOTICE_FLAG = "mb-6 rounded-lg bg-flag-soft px-5 py-4 text-flag";

/**
 * One column, not two.
 *
 * A two-column grid inside a reading-width page left labels wrapping onto three
 * lines and the eye zig-zagging. A single column is also the faster way through
 * a form: one thing to answer at a time, no deciding where to look next.
 */
export const FIELD_GRID = "grid grid-cols-1";

export const MUTED = "text-sm text-ink-soft";

export const EYEBROW = "text-xs font-semibold tracking-[0.08em] text-brand uppercase";
