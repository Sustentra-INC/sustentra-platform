"use client";

import { useEffect, useMemo, useState } from "react";

import { ApiError } from "../../../lib/api";
import { bulkInvite, listMembers, type OrgMember } from "../../admin/orgApi";
import type { TeamDirectory } from "../components/TeamMemberPicker";

const FAILED: Record<string, string> = {
  already_member: "That person is already in your organization.",
  seat_limit: "No seats left. Ask an org admin to remove someone or your provider for more seats.",
  invalid: "That is not a valid email address.",
};

/** The org's people for the Setup team picker. Null (plain inputs) when there is no org to read. */
export function useTeamDirectory(
  orgId: string | null | undefined,
  role: "provider_admin" | "org_admin" | "org_member" | undefined,
): TeamDirectory | undefined {
  const [state, setState] = useState<{ orgName: string; members: OrgMember[] } | null>(null);

  useEffect(() => {
    if (!orgId) return;
    let active = true;
    listMembers(orgId)
      .then((res) => {
        if (active) setState({ orgName: res.org_name, members: res.items });
      })
      .catch(() => {
        // No directory: Setup keeps its plain inputs rather than failing the page.
      });
    return () => {
      active = false;
    };
  }, [orgId]);

  const canInvite = role === "org_admin";
  return useMemo(() => {
    if (!orgId || !state) return undefined;
    return {
      orgName: state.orgName,
      members: state.members,
      canInvite,
      invite: async (email: string) => {
        try {
          const res = await bulkInvite(orgId, [email], "org_member");
          const result = res.results[0];
          if (result?.status !== "invited") throw new Error(FAILED[result?.status ?? ""] ?? "Could not send the invitation.");
        } catch (err) {
          if (err instanceof ApiError) throw new Error(err.detail);
          throw err;
        }
        setState((s) =>
          s ? { ...s, members: [...s.members, { id: `invited:${email}`, email, name: "", status: "invited" }] } : s,
        );
      },
    };
  }, [orgId, state, canInvite]);
}
