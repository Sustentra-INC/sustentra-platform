/**
 * The demo's copy of the server's vehicle group ids (`assign_group_ids` in
 * `backend/app/services/calculation_lines.py`): every group of a save has a `group_id`, the one it has when that id
 * belongs to a stored group, else the id of an unchanged stored group, else a new one. A renamed, reordered or
 * removed group never changes another group's id, so a mobile line keeps its documents.
 */
import type { EngagementConfig, VehicleGroupSetting } from "../types";

const GROUP_ID = /^vg-[a-z0-9](?:[a-z0-9-]{0,66}[a-z0-9])?$/;
const SAME = ["fuel", "vehicle_type", "factor_fuel_type", "on_road", "label"] as const;

let counter = 0;

function newId(taken: Set<string>): string {
  for (;;) {
    counter += 1;
    const candidate = `vg-${(Date.now() % 0xffffff).toString(16).padStart(6, "0")}${counter.toString(16).padStart(6, "0")}`;
    if (!taken.has(candidate)) return candidate;
  }
}

/** The groups of the stored engagement, each with the anchor it has (an id, else its old `vg-<slug>` anchor). */
function storedWithAnchors(stored: VehicleGroupSetting[]): { anchor: string; group: VehicleGroupSetting }[] {
  const slug = (text: string) => text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60).replace(/-+$/g, "") || "none";
  const seen = new Map<string, number>();
  return stored.map((group) => {
    const base = `vg-${slug(group.label ?? `${group.vehicle_type} (${group.factor_fuel_type})`)}`;
    const n = (seen.get(base) ?? 0) + 1;
    seen.set(base, n);
    return { anchor: group.group_id ?? (n === 1 ? base : `${base}-${n}`), group };
  });
}

export function assignDemoGroupIds(groups: VehicleGroupSetting[], stored: VehicleGroupSetting[] | undefined): VehicleGroupSetting[] {
  const known = storedWithAnchors(stored ?? []);
  const knownIds = new Set(known.map((k) => k.anchor));
  const used = new Set<string>();
  const out: VehicleGroupSetting[] = [];
  const pending: number[] = [];
  groups.forEach((group, i) => {
    const given = group.group_id;
    if (given && GROUP_ID.test(given) && knownIds.has(given) && !used.has(given)) {
      used.add(given);
      out.push({ ...group });
    } else {
      const { group_id: _dropped, ...rest } = group;
      void _dropped;
      out.push(rest);
      pending.push(i);
    }
  });
  for (const i of pending) {
    if (groups[i].group_id) continue; // an id this engagement never had is not trusted
    const match = known.find((k) => !used.has(k.anchor) && SAME.every((key) => k.group[key] === out[i][key]));
    if (match) {
      used.add(match.anchor);
      out[i].group_id = match.anchor;
    }
  }
  const taken = new Set([...knownIds, ...used]);
  for (const group of out) {
    if (!group.group_id) {
      group.group_id = newId(taken);
      taken.add(group.group_id);
    }
  }
  return out;
}

/** The engagement as the server would store it: every vehicle group has its id. */
export function withDemoGroupIds(next: EngagementConfig, previous: EngagementConfig | null): EngagementConfig {
  const groups = next.recalculation?.vehicle_groups;
  if (!groups) return next;
  return {
    ...next,
    recalculation: { ...next.recalculation, vehicle_groups: assignDemoGroupIds(groups, previous?.recalculation?.vehicle_groups) },
  };
}
