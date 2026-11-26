"use client";

import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { IconArrowRight, IconCalendar, IconChevronLeft, IconChevronRight } from "./icons";

export interface DateRangePickerProps {
  start: string;
  end: string;
  onChange: (start: string, end: string) => void;
  labelId?: string;
  showPresets?: boolean;
}

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];
const DOW_LABELS = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];

function toYMD(year: number, month: number, day: number): string {
  return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

function fmtDisplay(yyyyMmDd: string): string {
  const [y, m, d] = yyyyMmDd.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function countDays(start: string, end: string): number {
  const [sy, sm, sd] = start.split("-").map(Number);
  const [ey, em, ed] = end.split("-").map(Number);
  const a = new Date(sy, sm - 1, sd);
  const b = new Date(ey, em - 1, ed);
  return Math.round((b.getTime() - a.getTime()) / 86400000) + 1;
}

function getMonthGrid(year: number, month: number): (string | null)[] {
  const firstDow = new Date(year, month, 1).getDay();
  const cells: (string | null)[] = Array(firstDow).fill(null);
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const mo = String(month + 1).padStart(2, "0");
  for (let d = 1; d <= daysInMonth; d++) {
    cells.push(`${year}-${mo}-${String(d).padStart(2, "0")}`);
  }
  return cells;
}

function addMonths(year: number, month: number, delta: number): [number, number] {
  let m = month + delta;
  let y = year;
  while (m < 0) { m += 12; y--; }
  while (m > 11) { m -= 12; y++; }
  return [y, m];
}

function addDays(yyyyMmDd: string, delta: number): string {
  const [y, m, d] = yyyyMmDd.split("-").map(Number);
  const dt = new Date(y, m - 1, d);
  dt.setDate(dt.getDate() + delta);
  return toYMD(dt.getFullYear(), dt.getMonth() + 1, dt.getDate());
}

function getDow(yyyyMmDd: string): number {
  const [y, m, d] = yyyyMmDd.split("-").map(Number);
  return new Date(y, m - 1, d).getDay();
}

function getBandStyle(
  day: string,
  effStart: string | null,
  effEnd: string | null,
): React.CSSProperties {
  if (!effStart || !effEnd || effStart === effEnd) return {};

  const isStart = day === effStart;
  const isEnd = day === effEnd;
  const inRange = day > effStart && day < effEnd;
  const dow = getDow(day);

  if (isStart) {
    if (dow === 6) return {};
    return { background: "linear-gradient(90deg, transparent 50%, var(--accent-soft) 50%)" };
  }
  if (isEnd) {
    if (dow === 0) return {};
    return { background: "linear-gradient(90deg, var(--accent-soft) 50%, transparent 50%)" };
  }
  if (inRange) {
    const radius =
      dow === 0 ? "var(--r-pill) 0 0 var(--r-pill)"
      : dow === 6 ? "0 var(--r-pill) var(--r-pill) 0"
      : "0";
    return { background: "var(--accent-soft)", borderRadius: radius };
  }
  return {};
}

function getCircleClass(
  day: string,
  effStart: string | null,
  effEnd: string | null,
): string {
  if (day === effStart || day === effEnd) return " s1-drp__day-num--sel";
  return "";
}

export function DateRangePicker({
  start,
  end,
  onChange,
  labelId,
  showPresets = false,
}: DateRangePickerProps) {
  const uid = useId();
  const panelId = `${uid}-drp`;

  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  const [open, setOpen] = useState(false);
  const [place, setPlace] = useState<{ top: number; left: number; up: boolean } | null>(null);

  const [draftStart, setDraftStart] = useState<string | null>(null);
  const [draftEnd, setDraftEnd] = useState<string | null>(null);
  const [picking, setPicking] = useState<"start" | "end">("start");
  const [hovered, setHovered] = useState<string | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);

  const [viewYear, setViewYear] = useState(new Date().getFullYear());
  const [viewMonth, setViewMonth] = useState(new Date().getMonth());

  const [rightYear, rightMonth] = addMonths(viewYear, viewMonth, 1);

  // Effective ordered start/end for rendering (may include hover preview)
  let effStart: string | null = draftStart;
  let effEnd: string | null = draftEnd;
  if (picking === "end" && draftStart && hovered) {
    if (hovered >= draftStart) {
      effStart = draftStart;
      effEnd = hovered;
    } else {
      effStart = hovered;
      effEnd = draftStart;
    }
  } else if (draftStart && draftEnd) {
    effStart = draftStart <= draftEnd ? draftStart : draftEnd;
    effEnd = draftStart <= draftEnd ? draftEnd : draftStart;
  }

  // Positioning
  useLayoutEffect(() => {
    if (!open || !triggerRef.current) {
      setPlace(null);
      return;
    }
    const measure = () => {
      const box = triggerRef.current?.getBoundingClientRect();
      if (!box) return;
      const panelH = panelRef.current?.offsetHeight ?? 400;
      const panelW = Math.min(640, window.innerWidth * 0.92);
      const up = box.bottom + panelH + 8 > window.innerHeight && box.top - panelH - 8 > 0;
      const rawLeft = box.right - panelW;
      const left = Math.max(8, rawLeft);
      setPlace({ top: up ? box.top - panelH - 4 : box.bottom + 4, left, up });
    };
    measure();
    const frame = window.requestAnimationFrame(measure);
    window.addEventListener("scroll", measure, true);
    window.addEventListener("resize", measure);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("scroll", measure, true);
      window.removeEventListener("resize", measure);
    };
  }, [open]);

  // Click-outside
  useEffect(() => {
    if (!open) return;
    function onDown(e: PointerEvent) {
      const t = e.target as Node;
      if (panelRef.current?.contains(t) || triggerRef.current?.contains(t)) return;
      setOpen(false);
    }
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [open]);

  // Auto-focus panel
  useEffect(() => {
    if (open) {
      const id = setTimeout(() => panelRef.current?.focus(), 10);
      return () => clearTimeout(id);
    }
  }, [open]);

  function openPanel() {
    const yr = start ? parseInt(start.slice(0, 4)) : new Date().getFullYear();
    const mo = start ? parseInt(start.slice(5, 7)) - 1 : new Date().getMonth();
    setViewYear(yr);
    setViewMonth(mo);
    setDraftStart(start || null);
    setDraftEnd(end || null);
    setPicking("start");
    setHovered(null);
    setCursor(start || toYMD(yr, mo + 1, 1));
    setOpen(true);
  }

  function close() {
    setOpen(false);
    setHovered(null);
    triggerRef.current?.focus();
  }

  function handleApply() {
    if (draftStart && draftEnd) {
      const s = draftStart <= draftEnd ? draftStart : draftEnd;
      const e = draftStart <= draftEnd ? draftEnd : draftStart;
      onChange(s, e);
    }
    close();
  }

  function pickDay(day: string) {
    if (picking === "start") {
      setDraftStart(day);
      setDraftEnd(null);
      setPicking("end");
      setCursor(day);
    } else {
      setDraftEnd(day);
      setPicking("start");
      setCursor(day);
    }
  }

  function ensureDayVisible(day: string) {
    const cy = parseInt(day.slice(0, 4));
    const cm = parseInt(day.slice(5, 7)) - 1;
    const [ry, rm] = addMonths(viewYear, viewMonth, 1);
    const beforeLeft = cy < viewYear || (cy === viewYear && cm < viewMonth);
    const afterRight = cy > ry || (cy === ry && cm > rm);
    if (beforeLeft) {
      setViewYear(cy);
      setViewMonth(cm);
    } else if (afterRight) {
      const [ny, nm] = addMonths(cy, cm, -1);
      setViewYear(ny);
      setViewMonth(nm);
    }
  }

  function handlePanelKey(e: React.KeyboardEvent) {
    switch (e.key) {
      case "ArrowRight":
      case "ArrowDown": {
        e.preventDefault();
        const next = cursor ? addDays(cursor, e.key === "ArrowDown" ? 7 : 1) : toYMD(viewYear, viewMonth + 1, 1);
        setCursor(next);
        ensureDayVisible(next);
        break;
      }
      case "ArrowLeft":
      case "ArrowUp": {
        e.preventDefault();
        const prev = cursor ? addDays(cursor, e.key === "ArrowUp" ? -7 : -1) : toYMD(viewYear, viewMonth + 1, 1);
        setCursor(prev);
        ensureDayVisible(prev);
        break;
      }
      case "PageDown": {
        e.preventDefault();
        const [ny, nm] = addMonths(viewYear, viewMonth, 1);
        setViewYear(ny);
        setViewMonth(nm);
        if (cursor) {
          const [, , cd] = cursor.split("-").map(Number);
          const max = new Date(ny, nm + 1, 0).getDate();
          setCursor(toYMD(ny, nm + 1, Math.min(cd, max)));
        }
        break;
      }
      case "PageUp": {
        e.preventDefault();
        const [py, pm] = addMonths(viewYear, viewMonth, -1);
        setViewYear(py);
        setViewMonth(pm);
        if (cursor) {
          const [, , cd] = cursor.split("-").map(Number);
          const max = new Date(py, pm + 1, 0).getDate();
          setCursor(toYMD(py, pm + 1, Math.min(cd, max)));
        }
        break;
      }
      case "Enter":
      case " ":
        e.preventDefault();
        if (cursor) pickDay(cursor);
        break;
      case "Escape":
        e.preventDefault();
        close();
        break;
    }
  }

  function handleTriggerKey(e: React.KeyboardEvent) {
    if (!open && (e.key === "Enter" || e.key === " " || e.key === "ArrowDown")) {
      e.preventDefault();
      openPanel();
    } else if (open && e.key === "Escape") {
      e.preventDefault();
      close();
    }
  }

  function renderMonth(yr: number, mo: number, isLeft: boolean) {
    const cells = getMonthGrid(yr, mo);
    const prevDisabled = false; // could add min/max later

    return (
      <div className="s1-drp__month" key={`${yr}-${mo}`}>
        <div className="s1-drp__month-hd">
          {isLeft ? (
            <button
              type="button"
              className="s1-drp__nav"
              aria-label="Previous month"
              disabled={prevDisabled}
              onClick={(e) => {
                e.stopPropagation();
                const [ny, nm] = addMonths(viewYear, viewMonth, -1);
                setViewYear(ny);
                setViewMonth(nm);
              }}
            >
              <IconChevronLeft size={14} aria-hidden />
            </button>
          ) : (
            <span />
          )}
          <span className="s1-drp__month-name">
            {MONTH_NAMES[mo]} {yr}
          </span>
          {!isLeft ? (
            <button
              type="button"
              className="s1-drp__nav"
              aria-label="Next month"
              onClick={(e) => {
                e.stopPropagation();
                const [ny, nm] = addMonths(viewYear, viewMonth, 1);
                setViewYear(ny);
                setViewMonth(nm);
              }}
            >
              <IconChevronRight size={14} aria-hidden />
            </button>
          ) : (
            <span />
          )}
        </div>

        <div className="s1-drp__dow-row" aria-hidden="true">
          {DOW_LABELS.map((d) => (
            <span key={d} className="s1-drp__dow">{d}</span>
          ))}
        </div>

        <div className="s1-drp__grid" role="grid" aria-label={`${MONTH_NAMES[mo]} ${yr}`}>
          {cells.map((day, i) => {
            if (!day) {
              return <span key={`empty-${i}`} className="s1-drp__day-cell s1-drp__day-cell--empty" aria-hidden="true" />;
            }

            const bandStyle = getBandStyle(day, effStart, effEnd);
            const circleClass = getCircleClass(day, effStart, effEnd);
            const isCursor = day === cursor;
            const [, , dd] = day.split("-").map(Number);

            return (
              <span
                key={day}
                role="gridcell"
                aria-label={fmtDisplay(day)}
                className={`s1-drp__day-cell${isCursor ? " is-cursor" : ""}`}
                onClick={() => pickDay(day)}
                onMouseEnter={() => setHovered(day)}
                onMouseLeave={() => setHovered(null)}
              >
                <span className="s1-drp__day-band" style={bandStyle}>
                  <span className={`s1-drp__day-num${circleClass}${isCursor ? " is-cursor" : ""}`}>
                    {dd}
                  </span>
                </span>
              </span>
            );
          })}
        </div>
      </div>
    );
  }

  const hasSelection = !!(draftStart && draftEnd);
  const orderedStart = hasSelection && draftStart! <= draftEnd! ? draftStart! : draftEnd!;
  const orderedEnd = hasSelection && draftStart! <= draftEnd! ? draftEnd! : draftStart!;

  return (
    <div className="s1-drp">
      <button
        ref={triggerRef}
        type="button"
        className="s1-drp__trigger"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={panelId}
        aria-labelledby={labelId}
        onClick={() => (open ? close() : openPanel())}
        onKeyDown={handleTriggerKey}
      >
        <IconCalendar size={16} className="s1-drp__cal-icon" aria-hidden />
        <span className="s1-drp__date s1-drp__date--start">
          {start ? fmtDisplay(start) : "Start date"}
        </span>
        <IconArrowRight size={14} className="s1-drp__arrow" aria-hidden />
        <span className="s1-drp__date s1-drp__date--end">
          {end ? fmtDisplay(end) : "End date"}
        </span>
        {start && end ? (
          <span className="s1-drp__count">{countDays(start, end)} days</span>
        ) : null}
      </button>

      {open && place
        ? createPortal(
            <div
              ref={panelRef}
              id={panelId}
              role="dialog"
              aria-label="Choose reporting period"
              aria-modal="true"
              className="s1-drp__panel"
              tabIndex={-1}
              style={{ top: place.top, left: place.left }}
              onKeyDown={handlePanelKey}
            >
              {showPresets ? (
                <div className="s1-drp__presets">
                  {/* Presets — pending Vivian approval */}
                </div>
              ) : null}
              <div className="s1-drp__months">
                {renderMonth(viewYear, viewMonth, true)}
                {renderMonth(rightYear, rightMonth, false)}
              </div>
              <div className="s1-drp__footer">
                <span className="s1-drp__footer-label">
                  {hasSelection ? (
                    <>
                      <strong className="s1-drp__footer-range">
                        {fmtDisplay(orderedStart!)} to {fmtDisplay(orderedEnd!)}
                      </strong>
                      {" · "}
                      {countDays(orderedStart!, orderedEnd!)} days
                    </>
                  ) : draftStart ? (
                    "Select end date"
                  ) : (
                    "Select dates"
                  )}
                </span>
                <span className="s1-drp__footer-btns">
                  <button type="button" className="s1-button" onClick={close}>
                    Cancel
                  </button>
                  <button
                    type="button"
                    className="s1-button s1-button--pri"
                    onClick={handleApply}
                    disabled={!hasSelection}
                  >
                    Apply
                  </button>
                </span>
              </div>
            </div>,
            document.querySelector(".s1-app") ?? document.body,
          )
        : null}
    </div>
  );
}
