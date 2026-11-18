/**
 * The two links between a calculation line's supporting schedule (Evidence) and its calculation
 * panel (Verification results). Both carry the line key, so the target opens on that line.
 */
export function resultsViewForLine(lineKey: string) {
  return { name: "results", lineKey } as const;
}

export function scheduleViewForLine(lineKey: string) {
  return { name: "schedule", lineKey } as const;
}
