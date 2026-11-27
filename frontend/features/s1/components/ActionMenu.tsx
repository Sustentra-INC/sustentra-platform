"use client";

import { type ReactNode, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { IconMore } from "./icons";

export interface ActionMenuEntry {
  label: string;
  action: () => void;
  disabled?: boolean;
  danger?: boolean;
  /** Optional 16px icon shown to the left of the label. */
  icon?: ReactNode;
  /** Show a separator line before this item. */
  separator?: boolean;
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
      const width = menuRef.current?.offsetWidth ?? 250;
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

  // Close on outside click
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

  // Focus first enabled item when menu opens
  useEffect(() => {
    if (!isOpen || !menuRef.current) return;
    const frame = requestAnimationFrame(() => {
      const first = menuRef.current?.querySelector<HTMLButtonElement>('[role="menuitem"]:not(:disabled)');
      first?.focus();
    });
    return () => cancelAnimationFrame(frame);
  }, [isOpen]);

  function handleKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    const menu = e.currentTarget;
    const items = Array.from(menu.querySelectorAll<HTMLButtonElement>('[role="menuitem"]:not(:disabled)'));
    const idx = items.indexOf(document.activeElement as HTMLButtonElement);

    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        items[(idx + 1) % items.length]?.focus();
        break;
      case "ArrowUp":
        e.preventDefault();
        items[(idx - 1 + items.length) % items.length]?.focus();
        break;
      case "Home":
        e.preventDefault();
        items[0]?.focus();
        break;
      case "End":
        e.preventDefault();
        items[items.length - 1]?.focus();
        break;
      case "Escape":
        e.preventDefault();
        onOpenChange(false);
        triggerRef.current?.focus();
        break;
      case "Tab":
        onOpenChange(false);
        break;
    }
  }

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
        <IconMore size={18} aria-hidden />
      </button>
      {isOpen && place
        ? createPortal(
            <div
              className="s1-menu__panel s1-menu__panel--float"
              role="menu"
              ref={menuRef}
              onKeyDown={handleKeyDown}
              style={{ top: place.top, left: place.left, transformOrigin: place.up ? "bottom right" : "top right" }}
            >
              {entries.map((entry) => (
                <MenuEntry
                  key={entry.label}
                  entry={entry}
                  onActivate={() => {
                    entry.action();
                    onOpenChange(false);
                  }}
                />
              ))}
            </div>,
            document.querySelector(".s1-app") ?? document.body
          )
        : null}
    </div>
  );
}

function MenuEntry({ entry, onActivate }: { entry: ActionMenuEntry; onActivate: () => void }) {
  return (
    <>
      {entry.separator ? <hr className="s1-menu__sep" aria-hidden /> : null}
      <button
        className={`s1-menu__item${entry.danger ? " s1-menu__item--danger" : ""}`}
        type="button"
        role="menuitem"
        disabled={entry.disabled}
        onClick={onActivate}
      >
        {entry.icon ? <span className="s1-menu__item-icon" aria-hidden>{entry.icon}</span> : null}
        {entry.label}
      </button>
    </>
  );
}
