import { Cpu, Sparkles, UserCheck } from "lucide-react";

/** Design standard section 7: who did it. Three sources, always words plus an icon. */
export type ProvenanceSource = "ai" | "system" | "human";

export type ProvenanceAction = "accepted" | "corrected" | "requested" | "adjusted" | "keyed" | "rejected" | "edited" | "examined" | "chosen" | "queued";

const ACTION_WORD: Record<ProvenanceAction, string> = {
  accepted: "Accepted",
  corrected: "Corrected",
  requested: "Requested",
  adjusted: "Adjusted",
  keyed: "Keyed",
  rejected: "Rejected",
  edited: "Edited",
  examined: "Examined",
  chosen: "Chosen",
  queued: "Added to requests",
};

const ICON = { ai: Sparkles, system: Cpu, human: UserCheck } as const;

/** The person's name, or "a reviewer" when there is none. An id is never shown. */
export function reviewerName(by?: string | null): string {
  const name = (by ?? "").trim();
  if (!name || /^[0-9a-f]{8}-[0-9a-f]{4}-/i.test(name) || /^(usr|user|u)[-_][\w-]+$/i.test(name)) return "a reviewer";
  return name;
}

function when(at?: string | null): string {
  if (!at) return "";
  const d = new Date(at);
  if (Number.isNaN(d.getTime())) return "";
  const sameDay = d.toDateString() === new Date().toDateString();
  return sameDay
    ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

/** The words of a label. An AI reading never reads "Accepted". */
export function provenanceText(p: { source: ProvenanceSource; action?: ProvenanceAction; by?: string | null; at?: string | null; detail?: string }): string {
  const tail = [when(p.at), p.detail].filter(Boolean).join(" · ");
  let head: string;
  if (p.source === "ai") head = "Read by AI";
  else if (p.source === "system") head = "Checked by system";
  else head = `${ACTION_WORD[p.action ?? "accepted"]} by ${reviewerName(p.by)}`;
  return tail ? `${head} · ${tail}` : head;
}

export function ProvenanceLabel({
  source,
  action,
  by,
  at,
  detail,
  className,
}: {
  source: ProvenanceSource;
  action?: ProvenanceAction;
  by?: string | null;
  at?: string | null;
  /** Extra words after the time: "was 42.31", "highlighted on page 3". */
  detail?: string;
  className?: string;
}) {
  const Icon = ICON[source];
  return (
    <span className={`s1-prov s1-prov--${source}${className ? ` ${className}` : ""}`} data-provenance={source}>
      <Icon className="s1-prov__icon" aria-hidden />
      <span>{provenanceText({ source, action, by, at, detail })}</span>
    </span>
  );
}
