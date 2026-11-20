"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  getUnreadCount,
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  type AppNotification,
} from "./tasksApi";

/** The unread count is asked for again this often. No websockets: a minute is soon enough for a task. */
export const POLL_MS = 60_000;

function ago(iso: string, now: number = Date.now()): string {
  const minutes = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60_000));
  if (Number.isNaN(minutes)) return "";
  if (minutes < 1) return "Just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

/**
 * The bell in the app header: unread count, and a list of the latest notifications. Clicking one
 * marks it read and opens what it points at.
 */
export function NotificationBell({
  orgId,
  tasksHref,
  pollMs = POLL_MS,
  onNavigate = (href: string) => window.location.assign(href),
}: {
  orgId: string;
  /** Where "My tasks" and a notification without a link go. */
  tasksHref: string;
  pollMs?: number;
  onNavigate?: (href: string) => void;
}) {
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<AppNotification[] | null>(null);
  const [failed, setFailed] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let active = true;
    const poll = () => {
      getUnreadCount(orgId)
        .then((result) => active && setUnread(result.unread_count))
        .catch(() => {
          // A missed poll is not worth a message: the next one will do.
        });
    };
    poll();
    const timer = window.setInterval(() => {
      if (!document.hidden) poll();
    }, pollMs);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [orgId, pollMs]);

  const loadList = useCallback(async () => {
    try {
      const result = await listNotifications(orgId, { limit: 10 });
      setItems(result.items);
      setUnread(result.unread_count);
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [orgId]);

  useEffect(() => {
    if (!open) return;
    function onDown(e: PointerEvent) {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next) void loadList();
  };

  const openOne = async (item: AppNotification) => {
    try {
      await markNotificationRead(orgId, item.id);
    } catch {
      // Opening it matters more than the read mark.
    }
    setOpen(false);
    onNavigate(item.link ?? tasksHref);
  };

  const readAll = async () => {
    try {
      await markAllNotificationsRead(orgId);
      setItems((all) => (all ? all.map((n) => ({ ...n, read_at: n.read_at ?? new Date().toISOString() })) : all));
      setUnread(0);
    } catch {
      setFailed(true);
    }
  };

  return (
    <div className="s1-bell" ref={rootRef}>
      <button
        className="s1-bell__button"
        type="button"
        aria-haspopup="true"
        aria-expanded={open}
        aria-label={unread > 0 ? `Notifications, ${unread} unread` : "Notifications"}
        onClick={toggle}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M6 9a6 6 0 1 1 12 0c0 6 2.5 7.5 2.5 7.5h-17S6 15 6 9Z" />
          <path d="M10 20a2 2 0 0 0 4 0" />
        </svg>
        {unread > 0 ? <span className="s1-bell__count" aria-hidden="true">{unread > 99 ? "99+" : unread}</span> : null}
      </button>
      {open ? (
        <div className="s1-bell__panel" role="region" aria-label="Notifications">
          <div className="s1-bell__head">
            <span className="s1-bell__title">Notifications</span>
            <button className="s1-linklike" type="button" disabled={unread === 0} onClick={() => void readAll()}>
              Mark all as read
            </button>
          </div>
          {failed ? (
            <p className="s1-muted s1-bell__empty" role="alert">
              Could not load notifications. Try again in a moment.
            </p>
          ) : items === null ? (
            <p className="s1-muted s1-bell__empty">Loading…</p>
          ) : items.length === 0 ? (
            <p className="s1-muted s1-bell__empty">Nothing yet. Tasks assigned to you appear here.</p>
          ) : (
            <ul className="s1-bell__list">
              {items.map((item) => (
                <li key={item.id}>
                  <button
                    className={`s1-bell__item${item.read_at ? "" : " is-unread"}`}
                    type="button"
                    onClick={() => void openOne(item)}
                  >
                    <span className="s1-bell__text">{item.title}</span>
                    <span className="s1-muted s1-bell__when">
                      {item.read_at ? "" : "Unread · "}
                      {ago(item.created_at)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <div className="s1-bell__foot">
            <a className="s1-linklike" href={tasksHref}>
              My tasks
            </a>
          </div>
        </div>
      ) : null}
    </div>
  );
}
