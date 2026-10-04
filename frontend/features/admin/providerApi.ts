import { api } from "../../lib/api";

/**
 * Provider-admin API (FE-004) — managing organisations. Calls `/api/v1/provider/*`
 * (ORG-001, not built yet) via the same-origin cookie client. Shapes are the
 * agreed contracts; adjust here if the backend lands differently.
 */

export type OrgStatus = "active" | "suspended";

export interface Org {
  id: string;
  name: string;
  slug: string;
  status: OrgStatus;
  max_users: number;
  user_count?: number;
  created_at?: string;
}

export interface OrgPage {
  items: Org[];
  total: number;
  page: number;
  page_size: number;
}

export interface InitialAdmin {
  email: string;
  first_name: string;
  last_name: string;
}

export interface CreateOrgInput {
  name: string;
  slug: string;
  max_users: number;
  initial_admin?: InitialAdmin;
}

export function listOrgs(
  params: { search?: string; status?: OrgStatus | ""; page?: number } = {},
): Promise<OrgPage> {
  const query = new URLSearchParams();
  if (params.search) query.set("search", params.search);
  if (params.status) query.set("status", params.status);
  if (params.page && params.page > 1) query.set("page", String(params.page));
  const qs = query.toString();
  return api<OrgPage>(`/provider/orgs${qs ? `?${qs}` : ""}`);
}

export function createOrg(input: CreateOrgInput): Promise<Org> {
  return api<Org>("/provider/orgs", { method: "POST", body: input });
}

export function getOrg(orgId: string): Promise<Org> {
  return api<Org>(`/provider/orgs/${encodeURIComponent(orgId)}`);
}

export function updateOrg(orgId: string, patch: { name?: string; max_users?: number }): Promise<Org> {
  return api<Org>(`/provider/orgs/${encodeURIComponent(orgId)}`, { method: "PATCH", body: patch });
}

export function suspendOrg(orgId: string): Promise<void> {
  return api<void>(`/provider/orgs/${encodeURIComponent(orgId)}/suspend`, { method: "POST" });
}

export function activateOrg(orgId: string): Promise<void> {
  return api<void>(`/provider/orgs/${encodeURIComponent(orgId)}/activate`, { method: "POST" });
}

/** Slug rule shared with the backend: lowercase alphanumeric + hyphens, 3–63. */
export function slugIssue(slug: string): string | null {
  if (!/^[a-z0-9-]{3,63}$/.test(slug)) {
    return "Use 3–63 lowercase letters, numbers, or hyphens.";
  }
  return null;
}
