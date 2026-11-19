"use client";

import { useState } from "react";

import type { VehicleTypeOption } from "../api/recalculation";
import type { EngagementConfig } from "../types";
import { InfoTip } from "./InfoTip";
import { draftProblem, draftsFrom, settingsFrom, VehicleGroupsFieldset, withSavedIds, type VehicleGroupDraft } from "./VehicleGroupsFieldset";

/** The API takes at most this many vehicle groups. */
export const MAX_VEHICLE_GROUPS = 200;

const REMOVE_NOTE =
  "Any documents on this group's line move to Unassigned supporting evidence. They stay in the engagement, and you can place them again.";

/** What a group is called on Evidence: its name, else its vehicle type and fuel. */
function shownName(d: VehicleGroupDraft): string {
  return d.label.trim() || `${d.vehicleType} (${d.factorFuel})`;
}

/** The name compared ignoring case and spacing. */
function sameName(d: VehicleGroupDraft): string {
  return shownName(d).split(/\s+/).join(" ").toLowerCase();
}

/**
 * Setup's Vehicle groups: the same data as Recalculation inputs on Verification results
 * (settings.recalculation.vehicle_groups), so a group added here is a group there. Mobile
 * documents land on a group's line on Evidence. The groups are saved with the engagement once
 * every group is complete; until then the page says so.
 */
export function SetupVehicleGroups({
  engagement,
  onChange,
  fuels,
  types,
}: {
  engagement: EngagementConfig;
  onChange: (next: EngagementConfig) => void;
  fuels: string[];
  types: VehicleTypeOption[];
}) {
  const [typed, setDrafts] = useState<VehicleGroupDraft[]>(() => draftsFrom(engagement.recalculation?.vehicle_groups));
  // A group added here has no id until the save answers: show it with the id the server gave, so a rename keeps the line.
  const drafts = withSavedIds(typed, engagement.recalculation?.vehicle_groups);
  const unfinished = drafts.filter((d) => draftProblem(d, types) !== null).length;

  function change(next: VehicleGroupDraft[]) {
    setDrafts(next);
    if (next.every((d) => draftProblem(d, types) === null)) {
      onChange({ ...engagement, recalculation: { ...(engagement.recalculation ?? {}), vehicle_groups: settingsFrom(next, types) } });
    }
  }

  const counts = new Map<string, number>();
  for (const d of drafts) counts.set(sameName(d), (counts.get(sameName(d)) ?? 0) + 1);
  // One message per shared name, however many groups share it.
  const shared = drafts.filter((d, i) => (counts.get(sameName(d)) ?? 0) > 1 && drafts.findIndex((e) => sameName(e) === sameName(d)) === i);

  return (
    <div className="s1-setup-card">
      <h2>
        Vehicle groups
        <InfoTip label="Vehicle groups">
          A fleet document lands on a group&apos;s line when only one group uses its fuel. With several groups on one
          fuel, place the document by hand on Evidence. A group keeps its line when you rename it or change the other
          groups. Removing a group removes its line, and documents you placed on it go to Unassigned supporting evidence.
        </InfoTip>
      </h2>
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
      {shared.map((d) => (
        <p key={sameName(d)} className="s1-rc__error" role="status">
          More than one group is called &quot;{shownName(d)}&quot;. Give each its own name, so you can tell their lines apart.
        </p>
      ))}
      {unfinished ? (
        <p className="s1-rc__error" role="status">
          Not saved yet. Finish or remove the vehicle groups marked above.
        </p>
      ) : null}
    </div>
  );
}
