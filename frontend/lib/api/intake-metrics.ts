import { intakeRequest } from "./intake";
import type { ClientJourney, MetricsSummary } from "../intake-types";

/**
 * The two success metrics (Phase F). Sustentra staff only - the API returns
 * 403 for anyone else, so this is not merely a hidden link.
 */

export function getMetrics(): Promise<MetricsSummary> {
  return intakeRequest<MetricsSummary>("/v1/intake/metrics");
}

export function getClientJourney(orgId: string): Promise<ClientJourney> {
  return intakeRequest<ClientJourney>(
    `/v1/intake/metrics/orgs/${encodeURIComponent(orgId)}`
  );
}
