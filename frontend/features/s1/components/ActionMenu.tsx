"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

export interface ActionMenuEntry {
  label: string;
  action: () => void;
  disabled?: boolean;
}

/**
 * A row's "⋯" menu. It floats above the page (portaled into the app), so no card or
 * scrolling table can cut it off; near the bottom of the window it opens upwards.
 */
export function ActionMenu({
  label,
  entries,
  isOpen,
  onOpenChange,
}: {
  /** The trigger's accessible name, e.g. "Actions for kent_gas_sep_2025.pdf". */
  label: string;
  entries: ActionMenuEntry[];
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  // Where the floating menu opens: under the button, or above it near the bottom of the window.
  const [place, setPlace] = useState<{ top: number; left: number; up: boolean } | null>(null);
  useLayoutEffect(() => {
    if (!isOpen || !triggerRef.current) {
      setPlace(null);
      return;
    }
    const measure = () => {
      const box = triggerRef.current?.getBoundingClientRect();
      if (!box) return;
      const height = menuRef.current?.offsetHeight ?? 320;
      const width = menuRef.current?.offsetWidth ?? 208;
      const up = box.bottom + height + 8 > window.innerHeight && box.top - height - 8 > 0;
      setPlace({ top: up ? box.top - height - 4 : box.bottom + 4, left: Math.max(8, box.right - width), up });
    };
    measure();
    const frame = window.requestAnimationFrame(measure); // again once the menu has its size
    window.addEventListener("scroll", measure, true);
    window.addEventListener("resize", measure);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("scroll", measure, true);
      window.removeEventListener("resize", measure);
    };
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    function onDown(e: PointerEvent) {
      const t = e.target as Node;
      if (menuRef.current?.contains(t) || triggerRef.current?.contains(t)) return;
      onOpenChange(false);
    }
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [isOpen, onOpenChange]);

  return (
    <div className="s1-menu">
      <button
        ref={triggerRef}
        className="s1-button s1-button--icon"
        type="button"
        aria-haspopup="menu"
        aria-expanded={isOpen}
        aria-label={label}
        onClick={() => onOpenChange(!isOpen)}
      >
        ⋯
      </button>
      {isOpen && place
        ? createPortal(
            <div
              className="s1-menu__panel s1-menu__panel--float"
              role="menu"
              ref={menuRef}
              style={{ top: place.top, left: place.left, transformOrigin: place.up ? "bottom right" : "top right" }}
            >
              {entries.map((entry) => (
                <button
                  key={entry.label}
                  className="s1-menu__item"
                  type="button"
                  role="menuitem"
                  disabled={entry.disabled}
                  onClick={() => {
                    entry.action();
                    onOpenChange(false);
                  }}
                >
                  {entry.label}
                </button>
              ))}
            </div>,
            document.querySelector(".s1-app") ?? document.body
          )
        : null}
    </div>
  );
}
