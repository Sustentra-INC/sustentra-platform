/**
 * The one period formatter. Human output only — "August 2025", "Q3 2025",
 * "FY2025", "Aug–Oct 2025" — never a raw ISO range in anything a person reads.
 * Used by the Workspace, the request message, the cards, and Screens 5 and 6.
 */

const MONTH = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];
const ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function parts(iso: string): { y: number; m: number; d: number } | null {
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return null;
  return { y, m, d };
}
function lastDay(y: number, m: number): number {
  return new Date(y, m, 0).getDate();
}

/** Format a start/end ISO date pair as a human period. */
export function formatPeriod(start: string | null | undefined, end: string | null | undefined): string {
  if (!start || !end) return start || end || "";
  const a = parts(start);
  const b = parts(end);
  if (!a || !b) return start === end ? start : `${start} to ${end}`;

  const wholeMonths = a.d === 1 && b.d === lastDay(b.y, b.m);

  if (a.y === b.y && a.d === b.d && a.m === b.m) return `${a.d} ${ABBR[a.m - 1]} ${a.y}`;

  if (a.y === b.y && wholeMonths) {
    if (a.m === b.m) return `${MONTH[a.m - 1]} ${a.y}`;
    if (a.m === 1 && b.m === 12) return `FY${a.y}`;
    if ([[1, 3], [4, 6], [7, 9], [10, 12]].some(([s, e]) => a.m === s && b.m === e)) {
      return `Q${Math.ceil(a.m / 3)} ${a.y}`;
    }
    return `${ABBR[a.m - 1]}–${ABBR[b.m - 1]} ${a.y}`;
  }

  if (a.m === 1 && a.d === 1 && b.m === 12 && b.d === 31) {
    return a.y === b.y ? `FY${a.y}` : `${a.y}–${b.y}`;
  }
  return `${ABBR[a.m - 1]} ${a.y} – ${ABBR[b.m - 1]} ${b.y}`;
}

/** One ISO date as a person reads it, "Oct 8, 2026"; anything else as it was typed. */
function formatDay(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!match) return iso;
  const [y, m, d] = [Number(match[1]), Number(match[2]), Number(match[3])];
  if (m < 1 || m > 12 || d < 1 || d > 31) return iso;
  return `${ABBR[m - 1]} ${d}, ${y}`;
}

/**
 * The engagement's reporting period, as the dashboard, the engagement bar and the Output
 * show it: "Oct 8, 2026 – Dec 31, 2026". An engagement is saved as it is filled in, so
 * either date may not be set yet; the missing one is named in its place ("Oct 8, 2026 –
 * end date not set"), never shown as "Invalid Date". No middle dot, so it reads as one
 * item where the dashboard joins it to the regulation with " · ". The Excel workpaper
 * writes the same words (backend workpaper_export_service.format_reporting_period).
 */
export function formatReportingPeriod(start: string | null | undefined, end: string | null | undefined): string {
  if (start && end) return `${formatDay(start)} – ${formatDay(end)}`;
  if (start) return `${formatDay(start)} – end date not set`;
  if (end) return `start date not set – ${formatDay(end)}`;
  return "Reporting period not set";
}
