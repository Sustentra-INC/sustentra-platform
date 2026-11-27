"use client";

import { createPortal } from "react-dom";
import { Fragment, useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

import type { EvidenceItem, FacilityOption } from "../types";
import { count } from "../utils/count";
import {
  buildSearchIndex,
  findDocuments,
  findFacilities,
  queryWords,
  type SearchDocument,
  type SearchFacility,
} from "../utils/searchIndex";
import { IconBuilding, IconClose, IconDocument, IconSearch } from "./icons";
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

/** The documents and facilities the app has loaded; search reads them, it fetches nothing. */
export interface SearchData {
  evidence: EvidenceItem[];
  facilities: FacilityOption[];
}

/** At most this many rows per group until "Show all". */
const CAP = { documents: 6, facilities: 5 } as const;

type GroupKey = "pages" | "documents" | "facilities";
type Row =
  | { key: string; kind: "page"; page: SearchPage }
  | { key: string; kind: "document"; doc: SearchDocument }
  | { key: string; kind: "facility"; facility: SearchFacility }
  | { key: string; kind: "more"; group: "documents" | "facilities"; total: number; next: string };
interface Group {
  key: GroupKey;
  title: string;
  count?: number;
  rows: Row[];
}

/** Search across the app: pages, then the loaded documents and facilities. */
export function SearchPanel({
  pages,
  data,
  onPick,
  onOpenDocument,
  onClose,
}: {
  pages: SearchPage[];
  data?: SearchData;
  onPick: (page: SearchPage) => void;
  onOpenDocument?: (documentId: string) => void;
  onClose: () => void;
}) {
  const id = useId();
  const listId = `${id}-list`;
  const input = useRef<HTMLInputElement>(null);
  const rows = useRef(new Map<string, HTMLDivElement>());
  const [query, setQuery] = useState("");
  const [active, setActive] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<GroupKey>>(() => new Set());
  // A facility picked from the results: the panel then lists only its documents.
  const [facility, setFacility] = useState<SearchFacility | null>(null);

  const evidence = data?.evidence;
  const facilities = data?.facilities;
  const index = useMemo(() => (evidence && facilities ? buildSearchIndex(evidence, facilities) : null), [evidence, facilities]);
  const q = query.trim().toLowerCase();
  const words = useMemo(() => queryWords(q), [q]);

  const groups = useMemo<Group[]>(() => {
    const capped = <T,>(group: "documents" | "facilities", all: T[], row: (item: T) => Row): Row[] => {
      const open = facility !== null || expanded.has(group) || all.length <= CAP[group];
      if (open) return all.map(row);
      const shown = all.slice(0, CAP[group]).map(row);
      return [...shown, { key: `more-${group}`, kind: "more", group, total: all.length, next: row(all[CAP[group]]).key }];
    };
    const docRow = (doc: SearchDocument): Row => ({ key: `doc-${doc.id}`, kind: "document", doc });
    const facRow = (f: SearchFacility): Row => ({ key: `fac-${f.id}`, kind: "facility", facility: f });

    if (facility && index) {
      const docs = findDocuments(index, q, facility.id);
      return docs.length ? [{ key: "documents", title: "Documents", count: docs.length, rows: docs.map(docRow) }] : [];
    }
    const out: Group[] = [];
    const pageMatches = q ? pages.filter((p) => p.label.toLowerCase().includes(q)) : pages;
    if (pageMatches.length) out.push({ key: "pages", title: "Pages", rows: pageMatches.map((page) => ({ key: `page-${page.id}`, kind: "page", page })) });
    // An empty query lists pages only: no wall of documents on open.
    if (q && index) {
      const docs = findDocuments(index, q);
      if (docs.length) out.push({ key: "documents", title: "Documents", count: docs.length, rows: capped("documents", docs, docRow) });
      const facs = findFacilities(index, q);
      if (facs.length) out.push({ key: "facilities", title: "Facilities", rows: capped("facilities", facs, facRow) });
    }
    return out;
  }, [pages, index, q, facility, expanded]);

  const flat = groups.flatMap((g) => g.rows);
  const enabled = flat.filter((r) => !(r.kind === "page" && r.page.disabled));
  // The highlight stays on its row while it is listed; otherwise it falls to the first open row.
  const current = enabled.find((r) => r.key === active) ?? enabled[0] ?? null;

  useEffect(() => {
    input.current?.focus();
  }, []);

  // Escape lifts a facility filter first, then closes. Re-bound each render to see the filter.
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.preventDefault();
      if (facility) clearFacility();
      else onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  useEffect(() => {
    if (current) rows.current.get(current.key)?.scrollIntoView?.({ block: "nearest" });
  }, [current]);

  function clearFacility() {
    setFacility(null);
    setActive(null);
    input.current?.focus();
  }

  function choose(row: Row) {
    if (row.kind === "page") {
      if (!row.page.disabled) onPick(row.page);
    } else if (row.kind === "document") {
      onOpenDocument?.(row.doc.id);
    } else if (row.kind === "facility") {
      setFacility(row.facility);
      setQuery("");
      setActive(null);
      input.current?.focus();
    } else {
      setExpanded((cur) => new Set(cur).add(row.group));
      // The highlight lands on the first row the group just revealed.
      setActive(row.next);
    }
  }

  const onInputKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      if (current) choose(current);
      return;
    }
    if (e.key === "Backspace" && facility && query === "") {
      e.preventDefault();
      clearFacility();
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
    setActive(next.key);
  };

  const rowProps = (row: Row, disabled = false) => {
    const on = current?.key === row.key;
    return {
      ref: (el: HTMLDivElement | null) => {
        if (el) rows.current.set(row.key, el);
        else rows.current.delete(row.key);
      },
      id: `${id}-opt-${row.key}`,
      role: "option",
      "aria-selected": on,
      "aria-disabled": disabled || undefined,
      // Keep focus in the field: a click opens the row, it does not move the caret.
      onMouseDown: (e: { preventDefault: () => void }) => e.preventDefault(),
      onMouseMove: () => !disabled && !on && setActive(row.key),
      onClick: () => !disabled && choose(row),
      on,
    };
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
          {facility ? (
            <span className="s1-searchpanel__chip">
              <span className="s1-searchpanel__chip-name">{facility.name}</span>
              <button type="button" aria-label={`Remove ${facility.name}`} onMouseDown={(e) => e.preventDefault()} onClick={clearFacility}>
                <IconClose size={12} aria-hidden />
              </button>
            </span>
          ) : null}
          <input
            ref={input}
            type="text"
            role="combobox"
            aria-label={facility ? `Search ${facility.name} documents` : "Search"}
            aria-expanded="true"
            aria-controls={listId}
            aria-autocomplete="list"
            aria-activedescendant={current ? `${id}-opt-${current.key}` : undefined}
            placeholder={facility ? undefined : "Search documents, facilities, pages"}
            autoComplete="off"
            spellCheck={false}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setActive(null);
              setExpanded(new Set());
            }}
            onKeyDown={onInputKey}
          />
          <button className="s1-searchpanel__esc" type="button" aria-label="Close search" onClick={onClose}>
            <KeyHint>Esc</KeyHint>
          </button>
        </div>
        <div className="s1-searchpanel__body">
          {groups.length ? (
            <div className="s1-searchpanel__list" id={listId} role="listbox" aria-label="Results">
              {groups.map((group) => (
                <div key={group.key} className="s1-searchpanel__grp" role="group" aria-labelledby={`${id}-${group.key}`}>
                  <div className="s1-searchpanel__group" id={`${id}-${group.key}`} role="presentation">
                    {group.title}
                    {group.count != null ? <> <span className="s1-searchpanel__count">{group.count}</span></> : null}
                  </div>
                  {group.rows.map((row) => (
                    <Fragment key={row.key}>{renderRow(row)}</Fragment>
                  ))}
                </div>
              ))}
            </div>
          ) : (
            <p className="s1-searchpanel__empty" role="status">
              {facility && !q ? `No documents for ${facility.name}` : <>No matches for &quot;{query.trim()}&quot;</>}
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

  function renderRow(row: Row) {
    const disabled = row.kind === "page" && Boolean(row.page.disabled);
    const { on, ...props } = rowProps(row, disabled);
    const cls = (extra = "") => `s1-searchpanel__option${extra}${on ? " is-active" : ""}${disabled ? " is-disabled" : ""}`;
    if (row.kind === "page") {
      return (
        <div {...props} className={cls()}>
          <span className="s1-searchpanel__icon" aria-hidden>
            {row.page.icon}
          </span>
          <span className="s1-searchpanel__label">
            <Match text={row.page.label} words={q ? [q] : []} />
          </span>
          {row.page.hint ? <span className="s1-searchpanel__hint">{row.page.hint}</span> : null}
        </div>
      );
    }
    if (row.kind === "document") {
      const meta = [row.doc.type, row.doc.facility, row.doc.period].filter(Boolean).join(" · ");
      return (
        <div {...props} className={cls(" s1-searchpanel__option--doc")} title={row.doc.fileName}>
          <span className="s1-searchpanel__icon" aria-hidden>
            <IconDocument size={18} />
          </span>
          <span className="s1-searchpanel__text">
            <span className="s1-searchpanel__label">
              <Match text={row.doc.fileName} words={words} />
            </span>
            <span className="s1-searchpanel__meta">{meta}</span>
          </span>
        </div>
      );
    }
    if (row.kind === "facility") {
      return (
        <div {...props} className={cls()}>
          <span className="s1-searchpanel__icon" aria-hidden>
            <IconBuilding size={18} />
          </span>
          <span className="s1-searchpanel__label">
            <Match text={row.facility.name} words={words} />
          </span>
          <span className="s1-searchpanel__hint s1-searchpanel__hint--xs">{count(row.facility.documents, "document")}</span>
        </div>
      );
    }
    return (
      <div {...props} className={cls(" s1-searchpanel__option--more")}>
        Show all {count(row.total, row.group === "documents" ? "document" : "facility", row.group === "documents" ? "documents" : "facilities")}
      </div>
    );
  }
}

/** The label with each typed word in the strong weight, wherever it first falls. */
function Match({ text, words }: { text: string; words: string[] }) {
  const lower = text.toLowerCase();
  const marks: Array<[number, number]> = [];
  for (const w of words) {
    const at = lower.indexOf(w);
    if (at >= 0) marks.push([at, at + w.length]);
  }
  if (!marks.length) return <>{text}</>;
  marks.sort((a, b) => a[0] - b[0]);
  const merged: Array<[number, number]> = [];
  for (const m of marks) {
    const last = merged[merged.length - 1];
    if (last && m[0] <= last[1]) last[1] = Math.max(last[1], m[1]);
    else merged.push([...m]);
  }
  const out: ReactNode[] = [];
  let pos = 0;
  merged.forEach(([s, e], i) => {
    if (s > pos) out.push(text.slice(pos, s));
    out.push(<strong key={i}>{text.slice(s, e)}</strong>);
    pos = e;
  });
  if (pos < text.length) out.push(text.slice(pos));
  return <>{out}</>;
}
