import { liveResultsFromRecalculation } from "../adapters/recalculationResultsAdapter";
import type { Recalculation } from "../api/recalculation";
import { OutputScreen, type LiveOutput } from "../components/OutputScreen";
import { liveStatementFigures } from "../utils/outputStatement";
import liveExample from "./fixtures/recalculationLive.json";

const RESULT = liveExample as unknown as Recalculation;

/** Output's live statement on a recorded backend response, to test what sits under the download button. */
export function LiveOutputForTest({ demo = false, onError }: { demo?: boolean; onError?: (e: unknown) => boolean }) {
  const results = liveResultsFromRecalculation(RESULT);
  const live: LiveOutput = {
    statement: liveStatementFigures(results.lines, results.boxTotals, results.inventory, RESULT.tolerance_pct),
    exportHref: "/api/v1/engagements/E1/export",
    savedCopiesFor: demo ? undefined : "E1",
    onError,
    gwpBasis: "AR5", findings: [], basisLines: [],
  };
  return <OutputScreen lines={results.lines} live={live} />;
}
