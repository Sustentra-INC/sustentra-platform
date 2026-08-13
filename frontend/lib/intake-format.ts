/**
 * Plain-language formatting for the intake screens (Phase D2).
 *
 * Separate from lib/format.ts, which belongs to the S1 surface and is untouched.
 * Everything here is about reading like a sentence rather than a record: a
 * reviewer glancing at the queue should never have to parse an ISO timestamp or
 * read "waiting 0 hours".
 */

/** "just now" / "3 hours ago" / "2 days ago" from an hours-open number. */
export function waitedFor(hours: number): string {
  if (hours < 1) return "just now";
  const whole = Math.round(hours);
  if (whole < 24) return `${whole} hour${whole === 1 ? "" : "s"} ago`;
  const days = Math.round(whole / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

/** How long something has been open, as a phrase. */
export function openFor(hours: number): string {
  if (hours < 1) return "less than an hour";
  const whole = Math.round(hours);
  if (whole < 24) return `${whole} hour${whole === 1 ? "" : "s"}`;
  const days = Math.round(whole / 24);
  return `${days} day${days === 1 ? "" : "s"}`;
}

/** A timestamp a person can read. Falls back to the raw value if unparseable. */
export function readableTime(timestamp: string): string {
  const parsed = new Date(timestamp);
  if (Number.isNaN(parsed.getTime())) return timestamp;
  return parsed.toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit"
  });
}
