import type { TraceColumn, TraceOperand } from "../../api/calcTrace";

/** Significant digits for a column that gives no display hint: enough to read, never the full float. */
const DEFAULT_SIG = 7;

type Display = TraceColumn["display"];

const clamp = (n: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, n));

/** Decimal places a number is shown with, from the column's hint (dp wins; sig is relative to the value). */
export function decimalsFor(value: number, display?: Display): number {
  if (display?.dp !== undefined) return clamp(Math.trunc(display.dp), 0, 20);
  const sig = clamp(Math.trunc(display?.sig ?? DEFAULT_SIG), 1, 21);
  if (!Number.isFinite(value)) return 0;
  // A zero has no magnitude: it keeps the precision a small value would have, so 0 beside 0.6 reads 0.6.
  if (value === 0) return sig - 1;
  return clamp(sig - 1 - Math.floor(Math.log10(Math.abs(value))), 0, 20);
}

/**
 * A number to the column's precision. A `dp` column always shows its fixed decimals ("1.00"); a `sig`
 * column shows what its significant digits need, without trailing zeros.
 */
export function formatNumber(value: number, display?: Display, digits?: number): string {
  if (!Number.isFinite(value)) return "—";
  const places = digits ?? decimalsFor(value, display);
  const fixed = display?.dp !== undefined;
  const rounded = Number(value.toFixed(places));
  return (Object.is(rounded, -0) ? 0 : rounded).toLocaleString("en-US", {
    minimumFractionDigits: fixed ? places : 0,
    maximumFractionDigits: places,
  });
}

/** "t CO2e" reads "t CO₂e"; the wire carries plain ASCII. */
export function prettyUnit(unit: string | undefined): string {
  return (unit ?? "").replace(/CO2/g, "CO₂").replace(/CH4/g, "CH₄").replace(/N2O/g, "N₂O");
}

const isNumber = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/** The text of one operand: "53.06 kg/MMBtu", "100%", a string value as given, or null when it has no value. */
export function operandText(operand: Pick<TraceOperand, "value" | "unit" | "column">, column?: TraceColumn): string | null {
  const { value } = operand;
  if (value === null || value === undefined) return null;
  if (typeof value === "string") return value;
  if (!isNumber(value)) return "—";
  // A fraction shown as a percentage: the consolidated share, and any column declared in "%" (a screening factor).
  if ((column?.key === "share" || column?.unit === "%") && !operand.unit) return `${formatNumber(value * 100, { sig: 6 })}%`;
  const unit = prettyUnit(operand.unit);
  return `${formatNumber(value, column?.display)}${unit ? ` ${unit}` : ""}`;
}

/**
 * "+344.9" or "−30" for a difference between two sides that are shown differently; null when the two
 * displayed strings are the same ("1.00" against "1.00"), or the difference rounds to nothing at the
 * precision of the larger side (so 0 against 0.6 shows 0.6, not a rounded 1 or 0).
 */
export function differenceText(difference: number | null | undefined, value: unknown, display?: Display): string | null {
  if (!isNumber(difference)) return null;
  let digits: number;
  if (isNumber(value)) {
    const other = value - difference;
    if (formatNumber(value, display) === formatNumber(other, display)) return null;
    digits = decimalsFor(Math.max(Math.abs(value), Math.abs(other)), display);
  } else {
    digits = decimalsFor(Math.abs(difference), display);
  }
  const rounded = Number(difference.toFixed(digits));
  if (rounded === 0) return null;
  return `${rounded > 0 ? "+" : "−"}${formatNumber(Math.abs(rounded), display, digits)}`;
}
