import { Cpu, FileText, Sparkles, UserCheck } from "lucide-react";

/** Design standard section 7: who did it. Three sources, always words plus an icon. */
export type ProvenanceSource = "ai" | "system" | "human";

export type ProvenanceAction = "accepted" | "corrected" | "requested" | "adjusted" | "keyed" | "rejected" | "edited" | "examined" | "chosen" | "queued" | "resolved" | "withdrawn" | "stated";

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
  resolved: "Resolved",
  withdrawn: "Withdrawn",
  stated: "Stated",
};

const ICON = { ai: Sparkles, system: Cpu, human: UserCheck } as const;

/** The person's name, or "a reviewer" when there is none. An id is never shown. */
export function reviewerName(by?: string | null): string {
  const name = (by ?? "").trim();
  if (!name || /^(a )?(reviewer|team member)$/i.test(name) || /^[0-9a-f]{8}-[0-9a-f]{4}-/i.test(name) || /^(usr|user|u)[-_][\w-]+$/i.test(name)) return "a reviewer";
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
export function provenanceText(p: { source: ProvenanceSource; action?: ProvenanceAction; by?: string | null; at?: string | null; detail?: string; read?: boolean }): string {
  const tail = [when(p.at), p.detail].filter(Boolean).join(" · ");
  let head: string;
  if (p.source === "ai") head = "Read by AI";
  else if (p.source === "system") head = p.read ? "Read by system rules" : "Checked by system";
  else if (p.action === "stated") head = "Stated by client";
  else head = `${ACTION_WORD[p.action ?? "accepted"]} by ${reviewerName(p.by)}`;
  return tail ? `${head} · ${tail}` : head;
}

export function ProvenanceLabel({
  source,
  action,
  by,
  at,
  detail,
  read,
  compact,
  className,
}: {
  source: ProvenanceSource;
  action?: ProvenanceAction;
  by?: string | null;
  at?: string | null;
  /** Extra words after the time: "was 42.31", "highlighted on page 3". */
  detail?: string;
  /** With source "system": the rules read it, nothing was checked ("Read by system rules"). */
  read?: boolean;
  /** For a table cell: the icon and the action's one word on one line, the full label in the tooltip and for screen readers. */
  compact?: boolean;
  className?: string;
}) {
  const Icon = source === "human" && action === "stated" ? FileText : ICON[source];
  const full = provenanceText({ source, action, by, at, detail, read });
  if (compact) {
    const word = source === "human" ? ACTION_WORD[action ?? "accepted"] : source === "ai" ? "AI" : "System";
    return (
      <span className={`s1-prov s1-prov--compact s1-prov--${source}${className ? ` ${className}` : ""}`} data-provenance={source} title={full} aria-label={full} role="img">
        <Icon className="s1-prov__icon" aria-hidden />
        <span aria-hidden>{word}</span>
      </span>
    );
  }
  return (
    <span className={`s1-prov s1-prov--${source}${className ? ` ${className}` : ""}`} data-provenance={source}>
      <Icon className="s1-prov__icon" aria-hidden />
      <span>{full}</span>
    </span>
  );
}
