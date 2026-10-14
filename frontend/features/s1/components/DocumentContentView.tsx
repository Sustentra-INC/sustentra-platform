"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { api, apiPath } from "../../../lib/api";
import type { PageMark } from "../types/review";
import { columnLetter, findInText } from "../utils/sourceAnchor";

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
      // The cell holding the value's text; the whole row when no single cell does.
      const column = row.cells.findIndex((cell) => cell !== null && findInText(cell, mark.rawText) !== null);
      add(
        column >= 0
          ? { key: `s0:r${anchor.row}:c${column}`, sheet: 0, row: anchor.row, column, range: null }
          : { key: `s0:r${anchor.row}`, sheet: 0, row: anchor.row, column: null, range: null },
        mark.id
      );
    } else if (content.kind === "lines" && anchor.kind === "line") {
      const text = content.lines[anchor.line - 1];
      if (text === undefined) continue;
      const range = findInLine(text, mark.rawText);
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
  // A sheet tab the reviewer opened, for the value selected at the time.
  const [sheetChoice, setSheetChoice] = useState<{ forId: string | null; sheet: number } | null>(null);
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
  const sheet = sheetChoice && sheetChoice.forId === selectedId ? sheetChoice.sheet : (selectedSpot?.sheet ?? 0);
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
            const whole = here.find((e) => e.spot.range === null);
            const ranged = here.filter((e) => e.spot.range !== null).sort((a, b) => a.spot.range![0] - b.spot.range![0]);
            return (
              <li key={line} className={`s1-cv__line${whole ? " s1-cv__line--marked" : ""}`} value={line}>
                {whole ? (
                  <button
                    type="button"
                    ref={markRef(whole.ids)}
                    className={markClass(stateOf(whole.ids), isSelected(whole.ids))}
                    title={labelOf(whole.ids)}
                    aria-label={`Select ${labelOf(whole.ids)}`}
                    onClick={() => onPickAmong?.(whole.ids)}
                  >
                    {text}
                  </button>
                ) : (
                  segments(text, ranged).map((part, i) =>
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
                  )
                )}
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

/** A Word table row or "Label<tab>value" line holds its value after the label, so look there
 *  first: "kWh" in "Total kWh Used<tab>96,000 kWh" is the unit, not the label's word. */
function findInLine(text: string, rawText: string | null | undefined): [number, number] | null {
  const tab = text.indexOf("\t");
  if (tab >= 0) {
    const after = findInText(text.slice(tab + 1), rawText);
    if (after) return [after[0] + tab + 1, after[1] + tab + 1];
  }
  return findInText(text, rawText);
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
