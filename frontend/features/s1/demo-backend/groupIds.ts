/**
 * The demo's copy of the server's vehicle group ids (`assign_group_ids` in
 * `backend/app/services/calculation_lines.py`): every group of a save has a `group_id`, the one it has when that id
 * belongs to a stored group, else the id of an unchanged stored group, else a new one. A renamed, reordered or
 * removed group never changes another group's id, so a mobile line keeps its documents.
 */
import type { EngagementConfig, VehicleGroupSetting } from "../types";

const GROUP_ID = /^vg(?:id)?-[a-z0-9](?:[a-z0-9-]{0,66}[a-z0-9])?$/;
const SAME = ["fuel", "vehicle_type", "factor_fuel_type", "on_road", "label"] as const;

let counter = 0;

function newId(taken: Set<string>): string {
  for (;;) {
    counter += 1;
    // "vgid-" and 12 hex digits: never an old `vg-<slug>` anchor, and its own slug
    const candidate = `vgid-${(Date.now() % 0xffffff).toString(16).padStart(6, "0")}${counter.toString(16).padStart(6, "0")}`;
    if (!taken.has(candidate)) return candidate;
  }
}

/** The groups of the stored engagement, each with the anchor it has: its id, else its old `vg-<slug>` anchor numbered by
 *  order, moved on (`-x2`, ...) when an id already uses it (the server's `vehicle_group_anchors`). */
function storedWithAnchors(stored: VehicleGroupSetting[]): { anchor: string; group: VehicleGroupSetting }[] {
  const slug = (text: string) => text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60).replace(/-+$/g, "") || "none";
  const own = new Set(stored.map((g) => g.group_id).filter((id): id is string => Boolean(id && GROUP_ID.test(id))));
  const seen = new Map<string, number>();
  return stored.map((group) => {
    const base = `vg-${slug(group.label ?? `${group.vehicle_type} (${group.factor_fuel_type})`)}`;
    const n = (seen.get(base) ?? 0) + 1;
    seen.set(base, n);
    if (group.group_id && GROUP_ID.test(group.group_id)) return { anchor: group.group_id, group };
    const old = n === 1 ? base : `${base}-${n}`;
    let anchor = old;
    for (let k = 2; own.has(anchor); k += 1) anchor = `${old}-x${k}`;
    own.add(anchor);
    return { anchor, group };
  });
}

const same = (a: VehicleGroupSetting, b: VehicleGroupSetting, ...skip: string[]): boolean => {
  const left = Object.entries(a).filter(([k]) => k !== "group_id" && !skip.includes(k)).sort();
  const right = Object.entries(b).filter(([k]) => k !== "group_id" && !skip.includes(k)).sort();
  return JSON.stringify(left) === JSON.stringify(right);
};

/** The server's `assign_group_ids`: a group keeps the id it has when that is a stored group's; one that sends no id is
 *  matched to a stored group the same in every field, then (renamed, or changed figures) to the one stored group
 *  that differs only there, never when another group of the save is as good a match; otherwise it is new. */
export function assignDemoGroupIds(groups: VehicleGroupSetting[], stored: VehicleGroupSetting[] | undefined): VehicleGroupSetting[] {
  const known = storedWithAnchors(stored ?? []);
  const knownIds = new Set(known.map((k) => k.anchor));
  const used = new Set<string>();
  const out: VehicleGroupSetting[] = [];
  let waiting: number[] = [];
  groups.forEach((group, i) => {
    const given = group.group_id;
    if (given && GROUP_ID.test(given) && knownIds.has(given) && !used.has(given)) {
      used.add(given);
      out.push({ ...group });
    } else {
      const { group_id: _dropped, ...rest } = group;
      void _dropped;
      out.push(rest);
      if (!group.group_id) waiting.push(i);
    }
  });
  const free = () => known.filter((k) => !used.has(k.anchor));
  const claim = (i: number, anchor: string) => {
    used.add(anchor);
    out[i].group_id = anchor;
    waiting = waiting.filter((w) => w !== i);
  };
  for (const i of [...waiting]) {
    const match = free().find((k) => same(k.group, out[i]));
    if (match) claim(i, match.anchor);
  }
  const refused = new Set<number>(); // turned down in step 2: another group of the save has the stored group's name
  for (const i of [...waiting]) {
    const fits = free().filter((k) => same(k.group, out[i], "label"));
    const rivals = waiting.filter((j) => same(out[j], out[i], "label"));
    if (fits.length === 1 && rivals.length === 1) {
      if (out.some((o, j) => j !== i && o.label === fits[0].group.label)) refused.add(i);
      else claim(i, fits[0].anchor);
    }
  }
  // changed figures; not for a refused group, and not when the figures are another unmatched stored group's (a name swap)
  for (const i of [...waiting]) {
    const fits = free().filter((k) => SAME.every((key) => k.group[key] === out[i][key]));
    const rivals = waiting.filter((j) => SAME.every((key) => out[j][key] === out[i][key]));
    const figuresOfAnother = free().some((k) => same(k.group, out[i], "label") && !fits.some((f) => f.anchor === k.anchor));
    if (fits.length === 1 && rivals.length === 1 && !refused.has(i) && !figuresOfAnother) claim(i, fits[0].anchor);
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
