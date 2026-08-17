import {
  DOCUMENTS,
  ENGAGEMENT,
  FINDINGS,
  LINES,
  REQUESTS,
  REQUIREMENTS,
} from "./meridian";
import type {
  DocumentRecord,
  Finding,
  InventoryLine,
  RequestRecord,
  Requirement,
} from "../types";

export type S2FixtureMode =
  | "meridian"
  | "meridian-empty"
  | "meridian-none-examined"
  | "meridian-filtered-empty"
  | "meridian-loading"
  | "meridian-error"
  | "meridian-degraded"
  | "meridian-blocked"
  | "meridian-complete";

export interface S2FixtureData {
  mode: S2FixtureMode;
  engagement: typeof ENGAGEMENT;
  lines: InventoryLine[];
  requirements: Requirement[];
  findings: Finding[];
  requests: RequestRecord[];
  documents: DocumentRecord[];
  missingLineNames: string[];
}

export function getInventory(mode: S2FixtureMode = selectedFixtureMode()): S2FixtureData {
  if (mode === "meridian-empty") {
    return buildFixture({ mode, lines: [], requirements: [], findings: [], requests: [], documents: DOCUMENTS });
  }

  if (mode === "meridian-degraded") {
    const missingLineNames = ["Fleet · Mobile combustion", "Carson Terminal · Fugitive emissions"];
    return buildFixture({
      mode,
      lines: LINES.slice(0, 6),
      requirements: REQUIREMENTS.filter((requirement) =>
        LINES.slice(0, 6).some((line) => line.id === requirement.lineId)
      ),
      missingLineNames,
    });
  }

  if (mode === "meridian-none-examined") {
    return buildFixture({
      mode,
      requirements: REQUIREMENTS.map((requirement) => ({
        ...requirement,
        reviewState: "not examined",
        performedBy: null,
        performedAt: null,
        technique: null,
      })),
      findings: [],
    });
  }

  if (mode === "meridian-complete") {
    return buildFixture({
      mode,
      requirements: REQUIREMENTS.map((requirement) => ({
        ...requirement,
        reviewState: "examined — no exceptions",
        evidenceState: requirement.evidenceState === "no evidence held" ? "unobtainable" : requirement.evidenceState,
      })),
    });
  }

  return buildFixture({ mode });
}

function selectedFixtureMode(): S2FixtureMode {
  const value = process.env.NEXT_PUBLIC_S2_FIXTURE ?? process.env.VITE_FIXTURE ?? "meridian";
  return isFixtureMode(value) ? value : "meridian";
}

function buildFixture(
  overrides: Partial<Omit<S2FixtureData, "engagement">> & { mode: S2FixtureMode }
): S2FixtureData {
  return {
    mode: overrides.mode,
    engagement: ENGAGEMENT,
    lines: overrides.lines ?? LINES,
    requirements: overrides.requirements ?? REQUIREMENTS,
    findings: overrides.findings ?? FINDINGS,
    requests: overrides.requests ?? REQUESTS,
    documents: overrides.documents ?? DOCUMENTS,
    missingLineNames: overrides.missingLineNames ?? [],
  };
}

function isFixtureMode(value: string): value is S2FixtureMode {
  return [
    "meridian",
    "meridian-empty",
    "meridian-none-examined",
    "meridian-filtered-empty",
    "meridian-loading",
    "meridian-error",
    "meridian-degraded",
    "meridian-blocked",
    "meridian-complete",
  ].includes(value);
}

