"use client";

import { FileUp, History, ListChecks, Scale, Search, Send, PenLine, X } from "lucide-react";
import { createPortal } from "react-dom";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import type { ActivityEntry } from "../utils/engagementActivity";

const KINDS: { key: ActivityEntry["kind"] | "all"; label: string }[] = [
  { key: "all", label: "All" },
  { key: "upload", label: "Uploads" },
  { key: "review", label: "Reviews" },
  { key: "document", label: "Document changes" },
  { key: "request", label: "Requests" },
  { key: "finding", label: "Findings" },
];

const ICON: Record<ActivityEntry["kind"], ReactNode> = {
  upload: <FileUp />,
  review: <ListChecks />,
  document: <PenLine />,
  request: <Send />,
  finding: <Scale />,
};

/** The engagement's activity log: who did what, and when, newest first. */
export function ActivityDrawer({ entries, onClose }: { entries: ActivityEntry[]; onClose: () => void }) {
  const [kind, setKind] = useState<ActivityEntry["kind"] | "all">("all");
  const [query, setQuery] = useState("");

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const counts = useMemo(() => {
    const map = new Map<string, number>([["all", entries.length]]);
    for (const entry of entries) map.set(entry.kind, (map.get(entry.kind) ?? 0) + 1);
    return map;
  }, [entries]);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return entries.filter(
      (entry) =>
        (kind === "all" || entry.kind === kind) &&
        (!q || entry.what.toLowerCase().includes(q) || entry.who.toLowerCase().includes(q))
    );
  }, [entries, kind, query]);

  const days = useMemo(() => {
    const groups: { day: string; entries: ActivityEntry[] }[] = [];
    for (const entry of shown.slice(0, 300)) {
      const day = dayLabel(entry.at);
      const last = groups[groups.length - 1];
      if (last && last.day === day) last.entries.push(entry);
      else groups.push({ day, entries: [entry] });
    }
    return groups;
  }, [shown]);

  return createPortal(
    <div className="s1-drawer-scrim" onPointerDown={(e) => e.target === e.currentTarget && onClose()}>
      <aside className="s1-actlog" role="dialog" aria-modal="true" aria-labelledby="s1-actlog-title">
        <div className="s1-actlog__head">
          <h2 id="s1-actlog-title">
            <History aria-hidden /> Activity log
          </h2>
          <button className="s1-updlg__close" type="button" aria-label="Close" onClick={onClose}>
            <X aria-hidden />
          </button>
        </div>
        <label className="s1-actlog__search">
          <Search aria-hidden />
          <input
            type="search"
            placeholder="Search by person or document"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <div className="s1-actlog__kinds" role="group" aria-label="Filter by change">
          {KINDS.filter((k) => k.key === "all" || counts.get(k.key)).map((k) => (
            <button
              key={k.key}
              className={`s1-actlog__kind${kind === k.key ? " is-on" : ""}`}
              type="button"
              aria-pressed={kind === k.key}
              onClick={() => setKind(k.key)}
            >
              {k.label} <span>{counts.get(k.key) ?? 0}</span>
            </button>
          ))}
        </div>
        <div className="s1-actlog__body">
          {days.length === 0 ? (
            <p className="s1-actlog__empty">Nothing recorded{query ? " matches that search" : " yet"}.</p>
          ) : (
            days.map((group) => (
              <section key={group.day} className="s1-actlog__day">
                <h3>{group.day}</h3>
                <ul>
                  {group.entries.map((entry, i) => (
                    <li key={`${entry.at}|${i}`} className={`s1-actlog__row s1-actlog__row--${entry.kind}`}>
                      <span className="s1-actlog__icon" aria-hidden>
                        {ICON[entry.kind]}
                      </span>
                      <span className="s1-actlog__what">
                        <strong>{entry.who}</strong> {entry.what}
                      </span>
                      <time className="s1-actlog__when" dateTime={entry.at}>
                        {timeLabel(entry.at)}
                      </time>
                    </li>
                  ))}
                </ul>
              </section>
            ))
          )}
        </div>
      </aside>
    </div>,
    document.querySelector(".s1-app") ?? document.body
  );
}

function dayLabel(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "Undated";
  return d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric", year: "numeric" });
}

function timeLabel(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}
