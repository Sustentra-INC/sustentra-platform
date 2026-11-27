"use client";

import { createPortal } from "react-dom";
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

import type { ActivityEntry } from "../utils/engagementActivity";
import { avatarTone, initials } from "../utils/personAvatar";
import { CountBadge } from "./CountBadge";
import { IconActivity, IconAlert, IconCheck, IconChecklist, IconClose, IconCompose, IconSearch, IconSend, IconUpload } from "./icons";

type KindKey = ActivityEntry["kind"] | "all";

const KINDS: { key: KindKey; label: string }[] = [
  { key: "all", label: "All" },
  { key: "upload", label: "Uploads" },
  { key: "review", label: "Reviews" },
  { key: "document", label: "Document changes" },
  { key: "request", label: "Requests" },
  { key: "finding", label: "Findings" },
  { key: "methodology", label: "Methodology" },
];

const BADGE_ICON: Record<ActivityEntry["kind"], ReactNode> = {
  upload: <IconUpload size={11} />,
  review: <IconCheck size={11} />,
  document: <IconCompose size={11} />,
  request: <IconSend size={11} />,
  finding: <IconAlert size={11} />,
  methodology: <IconChecklist size={11} />,
};

/** The newest entries shown; older ones are not listed. */
const CAP = 300;

/** The engagement's activity log: who did what, and when, newest first. */
export function ActivityDrawer({
  entries,
  onClose,
  you,
}: {
  entries: ActivityEntry[];
  onClose: () => void;
  /** The signed-in person's name, for the initial on entries recorded as "You". */
  you?: string | null;
}) {
  const [kind, setKind] = useState<KindKey>("all");
  const [query, setQuery] = useState("");
  const id = useId();
  const search = useRef<HTMLInputElement>(null);
  const kindsRow = useRef<HTMLDivElement>(null);
  const tabs = useRef(new Map<KindKey, HTMLButtonElement>());
  const [cut, setCut] = useState({ start: false, end: false });
  // Taken at first render: the button that opened the log gets focus back when it closes.
  const opener = useRef(typeof document === "undefined" ? null : document.activeElement);
  const restoreTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    // React's dev double-run remounts at once: cancel the hand-back its cleanup scheduled.
    if (restoreTimer.current !== null) {
      clearTimeout(restoreTimer.current);
      restoreTimer.current = null;
    }
    search.current?.focus();
    return () => {
      restoreTimer.current = setTimeout(() => {
        restoreTimer.current = null;
        const el = opener.current;
        if (el instanceof HTMLElement && el.isConnected) el.focus();
      });
    };
  }, []);

  const counts = useMemo(() => {
    const map = new Map<string, number>([["all", entries.length]]);
    for (const entry of entries) map.set(entry.kind, (map.get(entry.kind) ?? 0) + 1);
    return map;
  }, [entries]);
  const visibleKinds = KINDS.filter((k) => k.key === "all" || counts.get(k.key));

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
    for (const entry of shown.slice(0, CAP)) {
      const day = dayLabel(entry.at);
      const last = groups[groups.length - 1];
      if (last && last.day === day) last.entries.push(entry);
      else groups.push({ day, entries: [entry] });
    }
    return groups;
  }, [shown]);

  // The kind row scrolls sideways when it does not fit; a soft fade marks each cut edge.
  const measure = () => {
    const row = kindsRow.current;
    if (!row) return;
    // A few pixels of slack: the track's own padding is not hidden content.
    const slack = 8;
    const start = row.scrollLeft > slack;
    const end = row.scrollLeft + row.clientWidth < row.scrollWidth - slack;
    setCut((c) => (c.start === start && c.end === end ? c : { start, end }));
  };
  useEffect(() => {
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  });
  useEffect(() => {
    tabs.current.get(kind)?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [kind]);

  const onTabKey = (e: KeyboardEvent<HTMLButtonElement>) => {
    const keys = visibleKinds.map((k) => k.key);
    const at = keys.indexOf(kind);
    const next =
      e.key === "ArrowRight" ? keys[(at + 1) % keys.length]
      : e.key === "ArrowLeft" ? keys[(at - 1 + keys.length) % keys.length]
      : e.key === "Home" ? keys[0]
      : e.key === "End" ? keys[keys.length - 1]
      : null;
    if (!next) return;
    e.preventDefault();
    setKind(next);
    tabs.current.get(next)?.focus();
  };

  return createPortal(
    <div className="s1-drawer-scrim" onPointerDown={(e) => e.target === e.currentTarget && onClose()}>
      <aside className="s1-actlog" role="dialog" aria-modal="true" aria-labelledby="s1-actlog-title">
        <div className="s1-actlog__top">
          <div className="s1-actlog__head">
            <span className="s1-actlog__head-icon" aria-hidden>
              <IconActivity size={20} />
            </span>
            <h2 id="s1-actlog-title">Activity log</h2>
            <button className="s1-button s1-button--icon" type="button" aria-label="Close" onClick={onClose}>
              <IconClose size={15} aria-hidden />
            </button>
          </div>
          <label className="s1-search s1-actlog__search">
            <IconSearch size={15} aria-hidden />
            <input
              ref={search}
              type="search"
              placeholder="Search by person or document"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
          <div
            ref={kindsRow}
            className={`s1-ws-factabs s1-ws-factabs--seg s1-actlog__kinds${cut.start ? " is-cut-start" : ""}${cut.end ? " is-cut-end" : ""}`}
            role="tablist"
            aria-label="Filter by change"
            onScroll={measure}
          >
            {visibleKinds.map((k) => {
              const on = kind === k.key;
              return (
                <button
                  key={k.key}
                  ref={(el) => {
                    if (el) tabs.current.set(k.key, el);
                    else tabs.current.delete(k.key);
                  }}
                  id={`${id}-tab-${k.key}`}
                  className={`s1-ws-factab${on ? " is-on" : ""}`}
                  type="button"
                  role="tab"
                  aria-selected={on}
                  aria-controls={`${id}-panel`}
                  tabIndex={on ? 0 : -1}
                  onClick={() => setKind(k.key)}
                  onKeyDown={onTabKey}
                >
                  {k.label} <CountBadge variant={on ? "indigo" : "neutral"}>{counts.get(k.key) ?? 0}</CountBadge>
                </button>
              );
            })}
          </div>
        </div>
        <div className="s1-actlog__body" id={`${id}-panel`} role="tabpanel" aria-labelledby={`${id}-tab-${kind}`}>
          {days.length === 0 ? (
            <p className="s1-actlog__empty">Nothing recorded{query ? " matches that search" : " yet"}.</p>
          ) : (
            days.map((group) => (
              <section key={group.day} className="s1-actlog__day">
                <h3>
                  <span>{group.day}</span>
                  <span className="s1-actlog__daycount">{group.entries.length}</span>
                </h3>
                <ul>
                  {group.entries.map((entry, i) => (
                    <li key={`${entry.at}|${i}`} className={`s1-actlog__row s1-actlog__row--${entry.kind}`}>
                      <Avatar who={entry.who} kind={entry.kind} you={you} />
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
          {shown.length > CAP ? <p className="s1-actlog__cap">Showing the latest {CAP}.</p> : null}
        </div>
      </aside>
    </div>,
    document.querySelector(".s1-app") ?? document.body
  );
}

/** The person's initials on their usual tone, with a small badge for the kind of change. */
function Avatar({ who, kind, you }: { who: string; kind: ActivityEntry["kind"]; you?: string | null }) {
  const isYou = who === "You";
  const text = isYou ? (you?.trim()[0]?.toUpperCase() ?? "Y") : initials(who);
  return (
    <span className="s1-actlog__avatar" aria-hidden>
      <span className={`s1-team-avatar s1-team-avatar--md ${isYou ? "s1-team-avatar--you" : `s1-team-avatar--${avatarTone(who)}`}`}>{text}</span>
      <span className={`s1-actlog__badge s1-actlog__badge--${kind}`}>{BADGE_ICON[kind]}</span>
    </span>
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
