"use client";

import { createPortal } from "react-dom";
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

import { IconSearch } from "./icons";
import { KeyHint } from "./KeyHint";

export interface SearchPage {
  id: string;
  label: string;
  icon: ReactNode;
  /** Muted text on the right, e.g. the sidebar group. */
  hint?: string;
  /** Shown muted and skipped by the arrow keys. */
  disabled?: boolean;
}

/** Search across the app. For now it finds pages: the sidebar's items, in sidebar order. */
export function SearchPanel({
  pages,
  onPick,
  onClose,
}: {
  pages: SearchPage[];
  onPick: (page: SearchPage) => void;
  onClose: () => void;
}) {
  const id = useId();
  const listId = `${id}-list`;
  const groupId = `${id}-pages`;
  const input = useRef<HTMLInputElement>(null);
  const rows = useRef(new Map<string, HTMLDivElement>());
  const [query, setQuery] = useState("");
  const [active, setActive] = useState<string | null>(null);

  const q = query.trim().toLowerCase();
  const shown = useMemo(() => (q ? pages.filter((p) => p.label.toLowerCase().includes(q)) : pages), [pages, q]);
  const enabled = shown.filter((p) => !p.disabled);
  // The highlight stays on its row while it is listed; otherwise it falls to the first open row.
  const current = enabled.find((p) => p.id === active) ?? enabled[0] ?? null;

  useEffect(() => {
    input.current?.focus();
  }, []);

  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    if (current) rows.current.get(current.id)?.scrollIntoView?.({ block: "nearest" });
  }, [current]);

  const onInputKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      if (current) onPick(current);
      return;
    }
    if (!enabled.length) return;
    const at = current ? enabled.indexOf(current) : -1;
    const next =
      e.key === "ArrowDown" ? enabled[(at + 1) % enabled.length]
      : e.key === "ArrowUp" ? enabled[(at - 1 + enabled.length) % enabled.length]
      : e.key === "Home" ? enabled[0]
      : e.key === "End" ? enabled[enabled.length - 1]
      : null;
    if (!next) return;
    e.preventDefault();
    setActive(next.id);
  };

  return createPortal(
    <div
      className="s1-modal-scrim s1-modal-scrim--search"
      onPointerDown={(e) => {
        if (e.target !== e.currentTarget) return;
        // No mousedown after this, so the page under the scrim does not take the focus handed back.
        e.preventDefault();
        onClose();
      }}
    >
      <div className="s1-searchpanel" role="dialog" aria-modal="true" aria-label="Search">
        <div className="s1-searchpanel__field">
          <IconSearch size={18} aria-hidden />
          <input
            ref={input}
            type="text"
            role="combobox"
            aria-label="Search"
            aria-expanded="true"
            aria-controls={listId}
            aria-autocomplete="list"
            aria-activedescendant={current ? `${id}-opt-${current.id}` : undefined}
            placeholder="Search documents, facilities, pages"
            autoComplete="off"
            spellCheck={false}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setActive(null);
            }}
            onKeyDown={onInputKey}
          />
          <button className="s1-searchpanel__esc" type="button" aria-label="Close search" onClick={onClose}>
            <KeyHint>Esc</KeyHint>
          </button>
        </div>
        <div className="s1-searchpanel__body">
          {shown.length ? (
            <>
              <div className="s1-searchpanel__group" id={groupId}>
                Pages
              </div>
              <div className="s1-searchpanel__list" id={listId} role="listbox" aria-labelledby={groupId}>
                {shown.map((page) => {
                  const on = current?.id === page.id;
                  return (
                    <div
                      key={page.id}
                      ref={(el) => {
                        if (el) rows.current.set(page.id, el);
                        else rows.current.delete(page.id);
                      }}
                      id={`${id}-opt-${page.id}`}
                      className={`s1-searchpanel__option${on ? " is-active" : ""}${page.disabled ? " is-disabled" : ""}`}
                      role="option"
                      aria-selected={on}
                      aria-disabled={page.disabled || undefined}
                      // Keep focus in the field: a click opens the page, it does not move the caret.
                      onMouseDown={(e) => e.preventDefault()}
                      onMouseMove={() => !page.disabled && !on && setActive(page.id)}
                      onClick={() => !page.disabled && onPick(page)}
                    >
                      <span className="s1-searchpanel__icon" aria-hidden>
                        {page.icon}
                      </span>
                      <span className="s1-searchpanel__label">
                        <Match text={page.label} query={q} />
                      </span>
                      {page.hint ? <span className="s1-searchpanel__hint">{page.hint}</span> : null}
                    </div>
                  );
                })}
              </div>
            </>
          ) : (
            <p className="s1-searchpanel__empty" role="status">
              No matches for &quot;{query.trim()}&quot;
            </p>
          )}
        </div>
        <div className="s1-searchpanel__foot" aria-hidden>
          <KeyHint>↑</KeyHint>
          <KeyHint>↓</KeyHint> to move · <KeyHint>Enter</KeyHint> to open · <KeyHint>Esc</KeyHint> to close
        </div>
      </div>
    </div>,
    document.querySelector(".s1-app") ?? document.body
  );
}

/** The label with the typed text in the strong weight, wherever it falls. */
function Match({ text, query }: { text: string; query: string }) {
  const at = query ? text.toLowerCase().indexOf(query) : -1;
  if (at < 0) return <>{text}</>;
  return (
    <>
      {text.slice(0, at)}
      <strong>{text.slice(at, at + query.length)}</strong>
      {text.slice(at + query.length)}
    </>
  );
}
