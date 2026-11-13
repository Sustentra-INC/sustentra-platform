/**
 * The demo site's backend (fixture mode only). `lib/api.ts` sends every request here instead of
 * the network, so the demo runs the same screens as staging (Evidence tree, supporting schedule,
 * calculation panels, methodology review, batch upload) over the Cascade Provisions demo data.
 *
 * Each module registers the routes it answers. Answers follow the backend's response shapes in
 * `features/s1/api/*` exactly. State lives in memory for the tab; the demo's Reset reloads it.
 * A route nobody answers is a 404, which the screens already treat as "not there yet".
 */
import { ApiError, type ApiOptions } from "../../../lib/api";
import { evidenceTreeRoutes } from "./evidenceTree";
import { methodologyRoutes } from "./methodology";
import { recalculationRoutes } from "./recalculation";
import { batchRoutes } from "./batches";
import type { DemoRoute } from "./types";

const ROUTES: DemoRoute[] = [...evidenceTreeRoutes, ...methodologyRoutes, ...recalculationRoutes, ...batchRoutes];

/** A short pause so loading states show briefly, as they do on staging. */
const LATENCY_MS = 180;

export async function demoApi<T>(path: string, options: ApiOptions = {}): Promise<T> {
  const method = (options.method ?? "GET").toUpperCase();
  const [pathname, search = ""] = path.split("?");
  const query = new URLSearchParams(search);
  for (const route of ROUTES) {
    if (route.method !== method) continue;
    const match = route.path.exec(pathname);
    if (!match) continue;
    await new Promise((resolve) => setTimeout(resolve, LATENCY_MS));
    const params = (match.groups ?? {}) as Record<string, string>;
    const decoded = Object.fromEntries(Object.entries(params).map(([k, v]) => [k, decodeURIComponent(v)]));
    return (await route.handle({ params: decoded, query, body: options.body })) as T;
  }
  throw new ApiError(404, "Not found.", { detail: "Not found." }, null);
}

/** Throws the error a real route would, for example a 409 or a 422 with the server's sentence. */
export function demoError(status: number, detail: string): never {
  throw new ApiError(status, detail, { detail }, null);
}
