import type { TraceColumn, TraceOperand } from "../../api/calcTrace";

/** Significant digits for a column that gives no display hint: enough to read, never the full float. */
const DEFAULT_SIG = 7;

type Display = TraceColumn["display"];

const clamp = (n: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, n));

/** Decimal places a number is shown with, from the column's hint (dp wins; sig is relative to the value). */
export function decimalsFor(value: number, display?: Display): number {
  if (display?.dp !== undefined) return clamp(Math.trunc(display.dp), 0, 20);
  const sig = clamp(Math.trunc(display?.sig ?? DEFAULT_SIG), 1, 21);
  if (value === 0 || !Number.isFinite(value)) return 0;
  return clamp(sig - 1 - Math.floor(Math.log10(Math.abs(value))), 0, 20);
}

export function formatNumber(value: number, display?: Display): string {
  if (!Number.isFinite(value)) return "—";
  const digits = decimalsFor(value, display);
  const rounded = Number(value.toFixed(digits));
  return (Object.is(rounded, -0) ? 0 : rounded).toLocaleString("en-US", { maximumFractionDigits: digits });
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
  if (column?.key === "share" && !operand.unit) return `${formatNumber(value * 100, { sig: 6 })}%`;
  const unit = prettyUnit(operand.unit);
  return `${formatNumber(value, column?.display)}${unit ? ` ${unit}` : ""}`;
}

/**
 * "+344.9" or "−30" for a difference that survives the value's display rounding; null when it rounds to
 * zero (the `differs()` rule of utils/verificationTable.ts, at the column's own precision).
 */
export function differenceText(difference: number | null | undefined, value: unknown, display?: Display): string | null {
  if (!isNumber(difference)) return null;
  const digits = decimalsFor(isNumber(value) ? value : difference, display);
  const rounded = Number(difference.toFixed(digits));
  if (rounded === 0) return null;
  return `${rounded > 0 ? "+" : "−"}${formatNumber(Math.abs(rounded), { dp: digits })}`;
}
