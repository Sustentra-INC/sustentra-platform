import { intakeRequest } from "./intake";
import type { Profile, ProfileHistory } from "../intake-types";

/**
 * The profile page (Phase E).
 *
 * Both calls default to the caller's own company. Passing another org's id only
 * works for a Sustentra reviewer; the API returns 403 for anyone else, so a
 * client cannot reach another client's record by editing the URL.
 */

export function getProfile(orgId?: string): Promise<Profile> {
  const query = orgId ? `?org_id=${encodeURIComponent(orgId)}` : "";
  return intakeRequest<Profile>(`/v1/intake/profile${query}`);
}

export function getProfileHistory(options: { orgId?: string; limit?: number } = {}) {
  const params = new URLSearchParams();
  if (options.orgId) params.set("org_id", options.orgId);
  if (options.limit) params.set("limit", String(options.limit));
  const query = params.toString();
  return intakeRequest<ProfileHistory>(
    `/v1/intake/profile/history${query ? `?${query}` : ""}`
  );
}
