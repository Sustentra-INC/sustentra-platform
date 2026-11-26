"use client";

import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { IconCheck, IconChevronDown, IconSearch } from "./icons";

export interface DropdownOption {
  value: string;
  label: string;
  description?: string;
  disabled?: boolean;
}

interface DropdownProps {
  value: string;
  onChange: (value: string) => void;
  options: DropdownOption[];
  labelId?: string;
  placeholder?: string;
  searchable?: boolean;
  disabled?: boolean;
  name?: string;
}

export function Dropdown({
  value,
  onChange,
  options,
  labelId,
  placeholder = "Choose…",
  searchable = false,
  disabled = false,
  name,
}: DropdownProps) {
  const uid = useId();
  const panelId = `${uid}-panel`;

  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [highlighted, setHighlighted] = useState(-1);
  const [place, setPlace] = useState<{ top: number; left: number; width: number; up: boolean } | null>(null);

  const selected = options.find((o) => o.value === value);
  const hasDesc = !!selected?.description;

  const filtered =
    searchable && search
      ? options.filter((o) => o.label.toLowerCase().includes(search.toLowerCase()))
      : options;

  // Positioning — same pattern as ActionMenu
  useLayoutEffect(() => {
    if (!open || !triggerRef.current) {
      setPlace(null);
      return;
    }
    const measure = () => {
      const box = triggerRef.current?.getBoundingClientRect();
      if (!box) return;
      const panelH = panelRef.current?.offsetHeight ?? 320;
      const up = box.bottom + panelH + 8 > window.innerHeight && box.top - panelH - 8 > 0;
      setPlace({ top: up ? box.top - panelH - 4 : box.bottom + 4, left: box.left, width: box.width, up });
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

  // Click-outside — same pattern as ActionMenu
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

  // Auto-focus search when panel opens (no state updates here — resets happen in open/close handlers)
  useEffect(() => {
    if (open && searchable) {
      const id = setTimeout(() => searchRef.current?.focus(), 10);
      return () => clearTimeout(id);
    }
  }, [open, searchable]);

  function openPanel(initialHighlight?: number) {
    setOpen(true);
    setSearch("");
    setHighlighted(initialHighlight ?? -1);
  }

  function close() {
    setOpen(false);
    setSearch("");
    setHighlighted(-1);
    triggerRef.current?.focus();
  }

  function pick(opt: DropdownOption) {
    if (opt.disabled) return;
    onChange(opt.value);
    close();
  }

  function handleNav(e: React.KeyboardEvent) {
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        setHighlighted((h) => {
          let n = h + 1;
          while (n < filtered.length && filtered[n].disabled) n++;
          return n < filtered.length ? n : h;
        });
        break;
      case "ArrowUp":
        e.preventDefault();
        setHighlighted((h) => {
          let n = h - 1;
          while (n >= 0 && filtered[n].disabled) n--;
          return n >= 0 ? n : h;
        });
        break;
      case "Home":
        e.preventDefault();
        setHighlighted(filtered.findIndex((o) => !o.disabled));
        break;
      case "End": {
        e.preventDefault();
        let last = -1;
        for (let i = filtered.length - 1; i >= 0; i--) {
          if (!filtered[i].disabled) { last = i; break; }
        }
        setHighlighted(last);
        break;
      }
      case "Enter":
        e.preventDefault();
        if (highlighted >= 0 && highlighted < filtered.length) pick(filtered[highlighted]);
        break;
      case "Escape":
        e.preventDefault();
        close();
        break;
      case "Tab":
        setOpen(false);
        break;
    }
  }

  function handleTriggerKeyDown(e: React.KeyboardEvent) {
    if (!open) {
      if (e.key === "Enter" || e.key === " " || e.key === "ArrowDown") {
        e.preventDefault();
        const idx = filtered.findIndex((o) => o.value === value);
        openPanel(e.key === "ArrowDown" ? (idx >= 0 ? idx : 0) : undefined);
      } else if (!searchable && e.key.length === 1 && /[a-zA-Z0-9]/i.test(e.key)) {
        const ch = e.key.toLowerCase();
        const idx = filtered.findIndex((o) => o.label.toLowerCase().startsWith(ch));
        if (idx >= 0) openPanel(idx);
      }
    } else {
      handleNav(e);
    }
  }

  return (
    <div className={`s1-dd${open ? " s1-dd--open" : ""}${disabled ? " s1-dd--disabled" : ""}`}>
      {name ? <input type="hidden" name={name} value={value} /> : null}
      <button
        ref={triggerRef}
        type="button"
        className={`s1-dd__trigger${hasDesc ? " s1-dd__trigger--desc" : ""}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={panelId}
        aria-labelledby={labelId}
        disabled={disabled}
        onClick={() => (open ? close() : openPanel())}
        onKeyDown={handleTriggerKeyDown}
      >
        <span className="s1-dd__label">
          {selected ? (
            <>
              <span className="s1-dd__primary">{selected.label}</span>
              {selected.description ? (
                <span className="s1-dd__secondary">{selected.description}</span>
              ) : null}
            </>
          ) : (
            <span className="s1-dd__placeholder">{placeholder}</span>
          )}
        </span>
        <IconChevronDown size={16} className="s1-dd__chevron" aria-hidden />
      </button>

      {open && place
        ? createPortal(
            <div
              ref={panelRef}
              id={panelId}
              className="s1-dd__panel"
              role="listbox"
              aria-labelledby={labelId}
              style={{
                top: place.top,
                left: place.left,
                width: place.width,
                transformOrigin: place.up ? "bottom center" : "top center",
              }}
            >
              {searchable ? (
                <div className="s1-dd__search-row">
                  <IconSearch size={16} className="s1-dd__search-icon" aria-hidden />
                  <input
                    ref={searchRef}
                    className="s1-dd__search"
                    type="text"
                    placeholder="Search…"
                    value={search}
                    onChange={(e) => { setSearch(e.target.value); setHighlighted(e.target.value ? 0 : -1); }}
                    onKeyDown={handleNav}
                  />
                </div>
              ) : null}
              <div className="s1-dd__list">
                {filtered.map((opt, i) => (
                  <div
                    key={opt.value}
                    className={[
                      "s1-dd__option",
                      opt.value === value ? "is-selected" : "",
                      highlighted === i ? "is-active" : "",
                      opt.disabled ? "is-disabled" : "",
                    ]
                      .filter(Boolean)
                      .join(" ")}
                    role="option"
                    aria-selected={opt.value === value}
                    aria-disabled={opt.disabled}
                    onClick={() => pick(opt)}
                    onMouseEnter={() => !opt.disabled && setHighlighted(i)}
                  >
                    <span className="s1-dd__opt-body">
                      <span className="s1-dd__opt-primary">{opt.label}</span>
                      {opt.description ? (
                        <span className="s1-dd__opt-secondary">{opt.description}</span>
                      ) : null}
                    </span>
                    {opt.value === value ? (
                      <IconCheck size={16} className="s1-dd__check" aria-hidden />
                    ) : null}
                  </div>
                ))}
                {filtered.length === 0 ? (
                  <div className="s1-dd__empty">No matches</div>
                ) : null}
              </div>
            </div>,
            document.querySelector(".s1-app") ?? document.body
          )
        : null}
    </div>
  );
}
