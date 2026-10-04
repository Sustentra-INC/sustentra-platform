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
      className={`s1-state s1-state--${role satisfies StateRole | "unmapped"} ${explain ? "s1-state--explained" : ""}`}
      tabIndex={explain ? 0 : undefined}
    >
      {displayLabel}
      {explain ? <span className="s1-tooltip" role="tooltip">{explain}</span> : null}
    </span>
  );
}
