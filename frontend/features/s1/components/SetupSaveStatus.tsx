"use client";

/**
 * Where Setup says whether its edits are saved: once near the top (with the Save changes button) and once on
 * each section. Setup saves by itself shortly after typing stops; the button saves at once.
 */

export type SetupSection = "company" | "facilities" | "vehicles" | "team";

export interface SetupSaveInfo {
  state: "idle" | "saving" | "saved" | "error";
  savedAt: Date | null;
  /** Why a section's latest edit is not saved (the rest of the page is). */
  problems: Partial<Record<SetupSection, string>>;
  /** Why the whole save failed (for example the network), or null. */
  message: string | null;
  /** Saves what is waiting now; also the retry after a failure. */
  onSaveNow: () => void;
}

/** "2:41 PM": the time a save finished. */
export function savedTime(at: Date): string {
  return at.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
}

export interface SaveLine {
  kind: "saving" | "saved" | "error";
  text: string;
}

/** What one section (or, with no section, the page) says about its save, or null before anything changed. */
export function saveLine(info: SetupSaveInfo, section?: SetupSection): SaveLine | null {
  const sections = Object.values(info.problems).filter((p): p is string => Boolean(p));
  const reason = (section ? info.problems[section] : sections[0]) ?? (info.state === "error" ? info.message : null);
  if (reason) return { kind: "error", text: `Not saved: ${reason}` };
  if (info.state === "saving") return { kind: "saving", text: "Saving…" };
  if (info.state === "saved" && info.savedAt) return { kind: "saved", text: `Saved · ${savedTime(info.savedAt)}` };
  return null;
}

export function SaveStatus({ info, section }: { info: SetupSaveInfo | undefined; section?: SetupSection }) {
  if (!info) return null;
  const line = saveLine(info, section);
  if (!line) return null;
  return (
    <span
      className={`s1-setup-save s1-setup-save--${line.kind}`}
      aria-label={section ? undefined : "Setup save state"}
      role={line.kind === "error" ? "alert" : "status"}>
      {line.text}
      {line.kind === "error" ? (
        <>
          {" "}
          <button className="s1-linklike" type="button" onClick={info.onSaveNow}>
            Retry
          </button>
        </>
      ) : null}
    </span>
  );
}
