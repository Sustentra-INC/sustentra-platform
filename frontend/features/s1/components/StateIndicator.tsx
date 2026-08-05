import type { StateDimension } from "../types";
import { STATE_ROLE_BY_PAIR, type StateRole } from "../constants/stateIndicators";

interface StateIndicatorProps {
  dimension: StateDimension;
  value: string;
  label: string;
  explain?: string;
}

export function StateIndicator({ dimension, value, label, explain }: StateIndicatorProps) {
  const role = STATE_ROLE_BY_PAIR[dimension]?.[value] ?? "unmapped";
  const displayLabel = role === "unmapped" ? `unmapped: ${label}` : label;

  return (
    <span
      className={`s1-state s1-state--${role satisfies StateRole | "unmapped"}`}
      tabIndex={explain ? 0 : undefined}
      title={explain}
    >
      {displayLabel}
    </span>
  );
}
