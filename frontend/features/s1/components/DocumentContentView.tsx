"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { api, apiPath } from "../../../lib/api";
import type { PageMark } from "../types/review";
import { columnLetter, findTokens, lineParts, sameText } from "../utils/sourceAnchor";

/**
 * A workbook, CSV, Word or text file as the parsers read it, with every extracted value
 * marked where it was read: a cell in a grid, or the words in a line. These files have no
 * page to outline a value on, so their content is drawn instead (GET /documents/{id}/content).
 *
 * Clicking a mark selects its value; a spot holding several values (a date range read as
 * both the start and the end) selects the next of them on each click. The selected value is
 * scrolled into view.
 */
export interface SheetContent {
  name: string | null;
  columns: number;
  rows: { number: number | null; cells: (string | null)[] }[];
}

export type DocumentContent =
  | { kind: "sheets"; sheets: SheetContent[]; truncated: boolean }
  | { kind: "lines"; lines: string[]; truncated: boolean };

/** A mark resolved to its spot in the content. */
interface Spot {
  key: string;
  sheet: number;
  row: number | null; // sheets: the row number; lines: the 1-based line
  column: number | null; // sheets: 0-based column; null marks the whole row
  range: [number, number] | null; // lines: the characters, or null for the whole line
}

/** Where each mark sits in the content; marks whose spot is not in it are left out. */
export function placeMarks(content: DocumentContent, marks: PageMark[]): Map<string, { spot: Spot; ids: string[] }> {
  const spots = new Map<string, { spot: Spot; ids: string[] }>();
  const add = (spot: Spot, id: string) => {
    const at = spots.get(spot.key);
    if (at) at.ids.push(id);
    else spots.set(spot.key, { spot, ids: [id] });
  };
  for (const mark of marks) {
    const anchor = mark.anchor;
    if (!anchor) continue;
    if (content.kind === "sheets" && anchor.kind === "cell") {
      const sheet = content.sheets.findIndex((s) => s.name === anchor.sheet);
      if (sheet < 0) continue;
      add({ key: `s${sheet}:r${anchor.row}:c${anchor.column}`, sheet, row: anchor.row, column: anchor.column, range: null }, mark.id);
    } else if (content.kind === "sheets" && anchor.kind === "row") {
      const row = content.sheets[0]?.rows.find((r) => r.number === anchor.row);
      if (!row) continue;
      // The column the extractor recorded; else the one cell whose text is the value (never a
      // cell that merely contains it, like "0" inside a date); else the whole row.
      const column = anchor.column ?? onlyCell(row.cells, mark.rawText);
      add(
        column >= 0
          ? { key: `s0:r${anchor.row}:c${column}`, sheet: 0, row: anchor.row, column, range: null }
          : { key: `s0:r${anchor.row}`, sheet: 0, row: anchor.row, column: null, range: null },
        mark.id
      );
    } else if (content.kind === "lines" && anchor.kind === "line") {
      const text = content.lines[anchor.line - 1];
      if (text === undefined) continue;
      const range = findInLine(text, mark.rawText, anchor.part);
      add(
        { key: range ? `l${anchor.line}:${range[0]}-${range[1]}` : `l${anchor.line}`, sheet: 0, row: anchor.line, column: null, range },
        mark.id
      );
    }
  }
  return spots;
}

export function DocumentContentView({
  documentId,
  marks,
  selectedId,
  onPickAmong,
}: {
  documentId: string;
  marks: PageMark[];
  selectedId: string | null;
  onPickAmong?: (ids: string[]) => void;
}) {
  const [content, setContent] = useState<DocumentContent | null>(null);
  const [failed, setFailed] = useState(false);
  // A sheet tab the reviewer opened; forgotten as soon as another value is selected, so the
  // selected value's own sheet always opens.
  const [sheetChoice, setSheetChoice] = useState<{ forId: string | null; sheet: number | null }>({
    forId: selectedId,
    sheet: null,
  });
  if (sheetChoice.forId !== selectedId) setSheetChoice({ forId: selectedId, sheet: null });
  const selectedRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    let live = true;
    api<DocumentContent>(`/documents/${encodeURIComponent(documentId)}/content`)
      .then((body) => {
        if (live) setContent(body);
      })
      .catch(() => {
        if (live) setFailed(true);
      });
    return () => {
      live = false;
    };
  }, [documentId]);

  const spots = useMemo(
    () => (content ? placeMarks(content, marks) : new Map<string, { spot: Spot; ids: string[] }>()),
    [content, marks]
  );
  const selectedSpot = useMemo(() => {
    for (const entry of spots.values()) if (selectedId && entry.ids.includes(selectedId)) return entry.spot;
    return null;
  }, [spots, selectedId]);
  const stateOf = (ids: string[]) => marks.find((m) => m.id === ids[0])?.reviewState ?? "to_review";
  const labelOf = (ids: string[]) =>
    ids.map((id) => marks.find((m) => m.id === id)?.label).filter(Boolean).join(" · ");

  // The selected value's sheet opens unless the reviewer picked another tab for it.
  const sheet = (sheetChoice.forId === selectedId ? sheetChoice.sheet : null) ?? selectedSpot?.sheet ?? 0;
  useEffect(() => {
    selectedRef.current?.scrollIntoView({ block: "center", inline: "nearest", behavior: "smooth" });
  }, [selectedSpot, content, sheet]);

  if (failed) {
    return (
      <div className="s1-xr-fallback">
        This file cannot be shown here.{" "}
        <a href={apiPath(`/documents/${encodeURIComponent(documentId)}/download`)}>Download it</a> to check the value.
      </div>
    );
  }
  if (!content) return <p className="s1-muted">Opening the file…</p>;

  const isSelected = (ids: string[]) => selectedId !== null && ids.includes(selectedId);
  const markRef = (ids: string[]) =>
    isSelected(ids)
      ? (node: HTMLElement | null) => {
          selectedRef.current = node;
        }
      : undefined;

  if (content.kind === "lines") {
    return (
      <div className="s1-cv">
        <ol className="s1-cv__lines">
          {content.lines.map((text, index) => {
            const line = index + 1;
            const here = Array.from(spots.values()).filter((e) => e.spot.row === line);
            // A value whose text is not on the line (a masked card number) is marked on the line
            // number, so the values that are on the line keep their own marks.
            const whole = here.find((e) => e.spot.range === null);
            const ranged = here.filter((e) => e.spot.range !== null).sort((a, b) => a.spot.range![0] - b.spot.range![0]);
            return (
              <li key={line} className="s1-cv__line">
                {whole ? (
                  <button
                    type="button"
                    ref={markRef(whole.ids)}
                    className={`${markClass(stateOf(whole.ids), isSelected(whole.ids))} s1-cv__lineno`}
                    title={labelOf(whole.ids)}
                    aria-label={`Select ${labelOf(whole.ids)}`}
                    onClick={() => onPickAmong?.(whole.ids)}
                  >
                    {line}
                  </button>
                ) : (
                  <span className="s1-cv__lineno s1-muted" aria-hidden>
                    {line}
                  </span>
                )}
                <span className="s1-cv__text">
                  {segments(text, ranged).map((part, i) =>
                    part.entry ? (
                      <button
                        key={i}
                        type="button"
                        ref={markRef(part.entry.ids)}
                        className={markClass(stateOf(part.entry.ids), isSelected(part.entry.ids))}
                        title={labelOf(part.entry.ids)}
                        aria-label={`Select ${labelOf(part.entry.ids)}`}
                        onClick={() => onPickAmong?.(part.entry!.ids)}
                      >
                        {part.text}
                      </button>
                    ) : (
                      <span key={i}>{part.text}</span>
                    )
                  )}
                </span>
              </li>
            );
          })}
        </ol>
        {content.truncated ? <p className="s1-muted s1-cv__note">Only the start of a long file is shown.</p> : null}
      </div>
    );
  }

  const current = content.sheets[sheet];
  if (!current) return <p className="s1-muted">The file has no content to show.</p>;
  const columns = Array.from({ length: Math.max(current.columns, 1) }, (_, i) => i);
  return (
    <div className="s1-cv">
      {content.sheets.length > 1 ? (
        <div className="s1-cv__tabs" role="tablist" aria-label="Sheets">
          {content.sheets.map((s, i) => (
            <button
              key={i}
              type="button"
              role="tab"
              aria-selected={i === sheet}
              className={`s1-cv__tab${i === sheet ? " s1-cv__tab--on" : ""}`}
              onClick={() => setSheetChoice({ forId: selectedId, sheet: i })}
            >
              {s.name ?? `Sheet ${i + 1}`}
            </button>
          ))}
        </div>
      ) : null}
      <div className="s1-cv__scroll">
        <table className="s1-cv__grid">
          <thead>
            <tr>
              <th className="s1-cv__corner" />
              {columns.map((c) => (
                <th key={c} scope="col" className="s1-cv__colhead">
                  {columnLetter(c)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {current.rows.map((row, r) => {
              const rowSpot = row.number !== null ? spots.get(`s${sheet}:r${row.number}`) : undefined;
              return (
                <tr key={`${row.number ?? "x"}-${r}`} className={rowSpot ? "s1-cv__row--marked" : undefined}>
                  <th scope="row" className="s1-cv__rowhead">
                    {rowSpot ? (
                      <button
                        type="button"
                        ref={markRef(rowSpot.ids)}
                        className={markClass(stateOf(rowSpot.ids), isSelected(rowSpot.ids))}
                        title={labelOf(rowSpot.ids)}
                        aria-label={`Select ${labelOf(rowSpot.ids)}`}
                        onClick={() => onPickAmong?.(rowSpot.ids)}
                      >
                        {row.number}
                      </button>
                    ) : (
                      row.number
                    )}
                  </th>
                  {columns.map((c) => {
                    const text = row.cells[c] ?? "";
                    const entry = row.number !== null ? spots.get(`s${sheet}:r${row.number}:c${c}`) : undefined;
                    return (
                      <td key={c} className={entry ? "s1-cv__cell--marked" : undefined}>
                        {entry ? (
                          <button
                            type="button"
                            ref={markRef(entry.ids)}
                            className={markClass(stateOf(entry.ids), isSelected(entry.ids))}
                            title={labelOf(entry.ids)}
                            aria-label={`Select ${labelOf(entry.ids)}`}
                            onClick={() => onPickAmong?.(entry.ids)}
                          >
                            {text}
                          </button>
                        ) : (
                          text
                        )}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {content.truncated ? <p className="s1-muted s1-cv__note">Only the start of a large file is shown.</p> : null}
    </div>
  );
}

/** The one cell whose whole text is the value, or -1 (none, or more than one). */
function onlyCell(cells: (string | null)[], rawText: string | null | undefined): number {
  const matches = cells.flatMap((cell, i) => (cell !== null && sameText(cell, rawText) ? [i] : []));
  return matches.length === 1 ? matches[0] : -1;
}

/**
 * Where a value sits in its line. The extractor says which part of the line it read (parts
 * split on tabs, 2+ spaces or pipes): the value is looked for in that part, and the whole part
 * is marked if its words differ. Without a part, a label's word is skipped: the value comes
 * after the last tab, else after a ":" or "=", else it is the last match ("kWh" in "Total kWh
 * Used: 96,000 kWh" is the unit, not the label).
 */
function findInLine(text: string, rawText: string | null | undefined, part?: number): [number, number] | null {
  const span = part !== undefined ? lineParts(text).get(part) : undefined;
  if (span) {
    const inPart = findTokens(text.slice(span[0], span[1]), rawText);
    const pick = inPart[inPart.length - 1];
    return pick ? [pick[0] + span[0], pick[1] + span[0]] : span;
  }
  const found = findTokens(text, rawText);
  if (!found.length) return null;
  const tab = text.lastIndexOf("\t");
  const label = tab >= 0 ? tab : Math.max(text.indexOf(":"), text.indexOf("="));
  return found.find(([start]) => label >= 0 && start > label) ?? found[found.length - 1];
}

function markClass(state: PageMark["reviewState"], selected: boolean): string {
  return `s1-cv__mark s1-cv__mark--${state}${selected ? " s1-cv__mark--selected" : ""}`;
}

/** A line cut into plain text and marked ranges. Overlapping marks become one mark holding
 *  all their values, so each stays selectable from the document. */
function segments(
  text: string,
  ranged: { spot: Spot; ids: string[] }[]
): { text: string; entry: { spot: Spot; ids: string[] } | null }[] {
  const merged: { start: number; end: number; entry: { spot: Spot; ids: string[] } }[] = [];
  for (const entry of ranged) {
    const [start, end] = entry.spot.range!;
    const last = merged[merged.length - 1];
    if (last && start < last.end) {
      last.end = Math.max(last.end, end);
      last.entry = { spot: last.entry.spot, ids: [...last.entry.ids, ...entry.ids] };
    } else {
      merged.push({ start, end, entry });
    }
  }
  const parts: { text: string; entry: { spot: Spot; ids: string[] } | null }[] = [];
  let at = 0;
  for (const { start, end, entry } of merged) {
    if (start > at) parts.push({ text: text.slice(at, start), entry: null });
    parts.push({ text: text.slice(start, end), entry });
    at = end;
  }
  if (at < text.length) parts.push({ text: text.slice(at), entry: null });
  return parts;
}
