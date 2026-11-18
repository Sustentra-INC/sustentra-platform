import type { Ask, AskEvent, AskState } from "../types/requests";

/** For each state, the step that put the request there and how to name who took it. */
const STEP: Record<AskState, { kind: AskEvent["kind"]; label: string }> = {
  not_yet_sent: { kind: "raised", label: "Raised by" },
  requested: { kind: "sent", label: "Sent by" },
  resolved: { kind: "resolved", label: "Resolved by" },
  withdrawn: { kind: "withdrawn", label: "Withdrawn by" },
};

/** The latest step on a request and who took it, from the server's record:
 *  not_yet_sent "Raised by", requested "Sent by", resolved "Resolved by", withdrawn "Withdrawn by".
 *  Null when the record names no one. */
export function whoActed(ask: Ask): { label: string; at: string | null } | null {
  const step = STEP[ask.state];
  const event = [...ask.history].reverse().find((h) => h.kind === step.kind);

  let name: string | null | undefined;
  let at: string | null | undefined;
  if (event) {
    name = event.actorName;
    at = event.at;
  } else if (ask.state === "resolved") {
    name = ask.resolution?.by;
    at = ask.resolution?.at;
  } else if (ask.state === "not_yet_sent") {
    name = ask.raisedByName;
    at = ask.raisedAt;
  }

  if (!name) return null;
  return { label: `${step.label} ${name}`, at: at || null };
}
