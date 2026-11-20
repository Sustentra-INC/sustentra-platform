import type { EngagementConfig, VehicleGroupSetting } from "../types";

const sameGroup = (a: VehicleGroupSetting, b: VehicleGroupSetting): boolean => {
  const { group_id: _a, ...left } = a;
  const { group_id: _b, ...right } = b;
  void [_a, _b];
  return JSON.stringify(Object.entries(left).sort()) === JSON.stringify(Object.entries(right).sort());
};

/**
 * The page's vehicle groups with the ids the server gave to the ones that had none (groups added since the last
 * save). A group takes the id of the saved group that is the same group in every field and not yet taken, so two
 * identical groups take their ids in order. Groups that already have an id, and groups the server has no match for
 * (they were edited again while the save ran), are left as they are; the server matches them by content next time.
 * Returns the same object when nothing changes.
 */
export function adoptGroupIds(config: EngagementConfig, saved: VehicleGroupSetting[] | undefined): EngagementConfig {
  const groups = config.recalculation?.vehicle_groups;
  if (!groups || !saved) return config;
  const taken = new Set(groups.map((g) => g.group_id).filter((id): id is string => Boolean(id)));
  let changed = false;
  const next = groups.map((group) => {
    if (group.group_id) return group;
    const match = saved.find((s) => s.group_id && !taken.has(s.group_id) && sameGroup(s, group));
    if (!match?.group_id) return group;
    taken.add(match.group_id);
    changed = true;
    return { ...group, group_id: match.group_id };
  });
  return changed ? { ...config, recalculation: { ...config.recalculation, vehicle_groups: next } } : config;
}
