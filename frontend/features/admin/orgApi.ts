import { api } from "../../lib/api";

/**
 * Org-admin API (FE-005) — managing users within one organisation. Calls
 * `/api/v1/orgs/{org_id}/*` (ORG-002 / ORG-003) and the audit log (COMP-002),
 * via the same-origin cookie client. Shapes are the agreed contracts.
 */

export type UserRole = "org_admin" | "org_member";
export type UserStatus = "active" | "invited" | "suspended";

export interface OrgUser {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  role: UserRole;
  status: UserStatus;
}

export interface UsersResult {
  items: OrgUser[];
  /** Users matching the filters. */
  total: number;
  max_users: number;
  /** Seats in use across the whole org, regardless of filters. */
  seats_used: number;
}

export interface Me {
  id: string;
  email: string;
  role: "provider_admin" | "org_admin" | "org_member";
  org_id?: string | null;
  org_slug?: string | null;
  first_name?: string;
  last_name?: string;
}

/** The signed-in user (client-side). */
export function getCurrentUser(): Promise<Me> {
  return api<Me>("/auth/me");
}

export function listOrgUsers(
  orgId: string,
  params: { status?: UserStatus | ""; role?: UserRole | "" } = {},
): Promise<UsersResult> {
  const query = new URLSearchParams();
  if (params.status) query.set("status", params.status);
  if (params.role) query.set("role", params.role);
  query.set("page_size", "100"); // the list is not paginated in the UI; 100 is the API maximum
  const qs = query.toString();
  return api<UsersResult>(`/orgs/${encodeURIComponent(orgId)}/users${qs ? `?${qs}` : ""}`);
}

export function getOrgUser(orgId: string, userId: string): Promise<OrgUser> {
  return api<OrgUser>(`/orgs/${encodeURIComponent(orgId)}/users/${encodeURIComponent(userId)}`);
}

export function updateUserRole(orgId: string, userId: string, role: UserRole): Promise<OrgUser> {
  return api<OrgUser>(`/orgs/${encodeURIComponent(orgId)}/users/${encodeURIComponent(userId)}`, {
    method: "PATCH",
    body: { role },
  });
}

export function suspendUser(orgId: string, userId: string): Promise<void> {
  return api<void>(`/orgs/${encodeURIComponent(orgId)}/users/${encodeURIComponent(userId)}/suspend`, {
    method: "POST",
  });
}

export function reactivateUser(orgId: string, userId: string): Promise<void> {
  return api<void>(`/orgs/${encodeURIComponent(orgId)}/users/${encodeURIComponent(userId)}/reactivate`, {
    method: "POST",
  });
}

/** Soft-delete (COMP-001). */
export function deleteUser(orgId: string, userId: string): Promise<void> {
  return api<void>(`/orgs/${encodeURIComponent(orgId)}/users/${encodeURIComponent(userId)}`, {
    method: "DELETE",
  });
}

export interface InviteInput {
  email: string;
  role: UserRole;
  first_name: string;
  last_name: string;
}

export function inviteUser(orgId: string, input: InviteInput): Promise<OrgUser> {
  return api<OrgUser>(`/orgs/${encodeURIComponent(orgId)}/invites`, { method: "POST", body: input });
}

export function resendInvite(orgId: string, userId: string): Promise<void> {
  return api<void>(`/orgs/${encodeURIComponent(orgId)}/invites/${encodeURIComponent(userId)}/resend`, {
    method: "POST",
  });
}

export interface AuditEvent {
  id: string;
  event_type: string;
  created_at: string;
  actor_user_id?: string | null;
  actor_role?: string | null;
  /** Display name of whoever did it ("Sustentra" for provider staff). */
  actor: string | null;
  target_type?: string | null;
  target_id?: string | null;
  /** Display name of the affected user, when the target is a user. */
  target?: string | null;
  metadata?: Record<string, unknown>;
}

export interface AuditResult {
  items: AuditEvent[];
  /** Pass back as `cursor` (with the same filters) for the next page; null on the last page. */
  next_cursor: string | null;
}

/** Org audit log (COMP-002): newest first, cursor-paginated. */
export function listAuditLog(
  orgId: string,
  params: { type?: string; cursor?: string | null } = {},
): Promise<AuditResult> {
  const query = new URLSearchParams();
  if (params.type) query.set("event_type", params.type);
  if (params.cursor) query.set("cursor", params.cursor);
  const qs = query.toString();
  return api<AuditResult>(`/orgs/${encodeURIComponent(orgId)}/audit-logs${qs ? `?${qs}` : ""}`);
}
