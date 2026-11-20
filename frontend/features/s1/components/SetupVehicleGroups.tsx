"use client";

import { useEffect, useRef, useState } from "react";

import type { VehicleTypeOption } from "../api/recalculation";
import type { EngagementConfig, VehicleGroupSetting } from "../types";
import { InfoTip } from "./InfoTip";
import { SaveStatus, type SetupSaveInfo } from "./SetupSaveStatus";
import {
  draftProblem,
  draftsFrom,
  isBlankDraft,
  settingsFrom,
  VehicleGroupsFieldset,
  withSavedIds,
  type VehicleGroupDraft,
} from "./VehicleGroupsFieldset";

/** The API takes at most this many vehicle groups. */
export const MAX_VEHICLE_GROUPS = 200;

const REMOVE_NOTE =
  "Any documents on this group's line move to Unassigned supporting evidence. They stay in the engagement, and you can place them again.";

/** What a group is called on Evidence: its name, else its vehicle type and fuel. Empty until it has either. */
function shownName(d: VehicleGroupDraft): string {
  const label = d.label.trim();
  if (label) return label;
  if (!d.vehicleType) return "";
  return d.factorFuel ? `${d.vehicleType} (${d.factorFuel})` : d.vehicleType;
}

/** The name compared ignoring case and spacing. */
function sameName(d: VehicleGroupDraft): string {
  return shownName(d).split(/\s+/).join(" ").toLowerCase();
}

/** The groups as text with keys in a fixed order (the server hands keys back in its own order), for comparing. */
const canonical = (groups: VehicleGroupSetting[]) =>
  JSON.stringify(groups.map((g) => Object.fromEntries(Object.entries(g).sort(([a], [b]) => (a < b ? -1 : 1)))));

/** The same with each group's id left out, for telling whether the groups changed apart from the ids the server gave. */
const withoutIds = (groups: VehicleGroupSetting[]) => canonical(groups.map(({ group_id: _id, ...rest }) => (void _id, rest)));

/** Drafts kept for an engagement while the user is on another page, so a group still being filled in is there on return. */
const keptDrafts = new Map<string, { drafts: VehicleGroupDraft[]; lastSaved: Map<string, VehicleGroupSetting>; groups: string }>();

/** Forgets the drafts kept for engagements (a test starts each case clean). */
export function forgetKeptVehicleDrafts(): void {
  keptDrafts.clear();
}

/**
 * Setup's Vehicle groups: the same data as Recalculation inputs on Verification results
 * (settings.recalculation.vehicle_groups), so a group added here is a group there. Mobile
 * documents land on a group's line on Evidence. A group is saved once it is complete. A row nobody has touched is
 * ignored; a group still being filled in is left out of the save (or, if it was saved before, keeps its last saved
 * settings), so it never stops the rest of Setup from saving, and the section says what is not saved.
 */
export function SetupVehicleGroups({
  engagement,
  onChange,
  fuels,
  types,
  save,
  onProblem,
}: {
  engagement: EngagementConfig;
  onChange: (next: EngagementConfig) => void;
  fuels: string[];
  types: VehicleTypeOption[];
  save?: SetupSaveInfo;
  /** Says why some groups are not saved (null when all are), so the page can show it at the top too. */
  onProblem?: (problem: string | null) => void;
}) {
  const savedGroups = engagement.recalculation?.vehicle_groups;
  const kept = keptDrafts.get(engagement.engagementId);
  const resume = kept && kept.groups === withoutIds(savedGroups ?? []) ? kept : null;
  const [typed, setDrafts] = useState<VehicleGroupDraft[]>(() => resume?.drafts ?? draftsFrom(savedGroups));
  // The last complete settings of each row: what a row that is half-edited again keeps being saved as.
  const lastSaved = useRef<Map<string, VehicleGroupSetting>>(
    resume?.lastSaved ?? new Map(typed.flatMap((d, i) => (d.uid && savedGroups?.[i] ? [[d.uid, savedGroups[i]] as const] : [])))
  );
  // A group added here has no id until the save answers: show it with the id the server gave, so a rename keeps the line.
  // ids of groups removed in this session: a group added later never takes one of them
  const [removed, setRemoved] = useState<string[]>([]);
  const drafts = withSavedIds(typed, engagement.recalculation?.vehicle_groups, removed);
  const unfinished = drafts.filter((d) => !isBlankDraft(d, fuels) && draftProblem(d, types) !== null).length;
  const problem = unfinished
    ? `${unfinished === 1 ? "1 vehicle group is" : `${unfinished} vehicle groups are`} unfinished. Finish or remove ${unfinished === 1 ? "it" : "them"}; the rest of Setup is saved.`
    : null;
  useEffect(() => {
    onProblem?.(problem);
    return () => onProblem?.(null);
  }, [problem, onProblem]);

  function change(next: VehicleGroupDraft[]) {
    const kept = new Set(next.map((d) => d.groupId));
    const gone = drafts.map((d) => d.groupId).filter((id): id is string => Boolean(id) && !kept.has(id));
    if (gone.length) setRemoved((current) => [...current, ...gone]);
    setDrafts(next);
    // Each row is saved as it is when complete; a row still being filled in keeps its last complete settings (so a
    // saved group is never dropped by a half-finished edit) or, if it never had any, is left out.
    const groups = next.flatMap((d): VehicleGroupSetting[] => {
      if (isBlankDraft(d, fuels)) return [];
      if (draftProblem(d, types) === null) {
        const [setting] = settingsFrom([d], types);
        if (d.uid) lastSaved.current.set(d.uid, setting);
        return [setting];
      }
      const before = d.uid ? lastSaved.current.get(d.uid) : undefined;
      if (!before) return [];
      return [d.groupId ? { ...before, group_id: d.groupId } : before];
    });
    keptDrafts.set(engagement.engagementId, { drafts: next, lastSaved: lastSaved.current, groups: withoutIds(groups) });
    if (canonical(groups) !== canonical(savedGroups ?? [])) {
      onChange({ ...engagement, recalculation: { ...(engagement.recalculation ?? {}), vehicle_groups: groups } });
    }
  }

  // A row nobody has touched, or one with no name yet, is not compared.
  const named = drafts.filter((d) => !isBlankDraft(d, fuels) && shownName(d));
  const counts = new Map<string, number>();
  for (const d of named) counts.set(sameName(d), (counts.get(sameName(d)) ?? 0) + 1);
  // One message per shared name, however many groups share it.
  const shared = named.filter((d, i) => (counts.get(sameName(d)) ?? 0) > 1 && named.findIndex((e) => sameName(e) === sameName(d)) === i);

  return (
    <div className="s1-setup-card">
      <div className="s1-setup-card__head">
      <h2>
        Vehicle groups
        <InfoTip label="Vehicle groups">
          A fleet document lands on a group&apos;s line when only one group uses its fuel. With several groups on one
          fuel, place the document by hand on Evidence. A group keeps its line when you rename it or change the other
          groups. Removing a group removes its line, and documents you placed on it go to Unassigned supporting evidence.
        </InfoTip>
      </h2>
      <SaveStatus info={save} section="vehicles" />
      </div>
      <VehicleGroupsFieldset
        drafts={drafts}
        fuels={fuels}
        types={types}
        asks={[]}
        onChange={change}
        confirmRemove={REMOVE_NOTE}
        maxGroups={MAX_VEHICLE_GROUPS}
        heading={false}
      />
      {problem && !save ? (
        <p className="s1-rc__error" role="status">
          Not saved: {problem}
        </p>
      ) : null}
      {shared.map((d) => (
        <p key={sameName(d)} className="s1-rc__error" role="status">
          More than one group is called &quot;{shownName(d)}&quot;. Give each its own name, so you can tell their lines apart.
        </p>
      ))}
    </div>
  );
}
