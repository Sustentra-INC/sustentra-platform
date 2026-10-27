"use client";

import { BookOpen, FileSpreadsheet, FileText, Files, Info, MousePointerClick, type LucideIcon } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";

import type {
  DocumentSource,
  EvidenceSource,
  RecordsSource,
  ReferenceSource,
  SourceRef,
  WorkbookSource,
} from "../types/verificationResults";
import { formatQuantity } from "../utils/calculationChains";

/**
 * Verification results, right pane: the document behind an underlined input, opened
 * at the cell, line or row it was read from. Same frame as Extraction Review's source
 * pane. An input with no document shows how it was determined instead.
 */
export function VerificationSource({
  source,
  onOpenDocument,
}: {
  source: SourceRef | null;
  /** Live results: open a reviewed record's document where its values were read. */
  onOpenDocument?: (documentId: string) => void;
}) {
  // A document opened from a list of bills keeps the list to go back to.
  const [opened, setOpened] = useState<{ from: RecordsSource; doc: DocumentSource } | null>(null);
  const [shownFor, setShownFor] = useState<SourceRef | null>(source);
  if (shownFor !== source) {
    setShownFor(source);
    setOpened(null);
  }

  if (!source) {
    return (
      <div className="s1-xr-src-empty">
        <MousePointerClick className="s1-vw-ico s1-vw-src-empty__icon" aria-hidden />
        <p className="s1-muted">
          Any underlined input opens here at its cited location. When the selected input has no document, this pane shows
          its determination basis instead.
        </p>
      </div>
    );
  }
  if (opened) {
    return (
      <Frame icon={FileText} title={opened.doc.filename} meta={`p. ${opened.doc.page}`}>
        <button className="s1-linklike s1-vw-back" type="button" onClick={() => setOpened(null)}>
          ‹ {opened.from.title}
        </button>
        <DocumentView doc={opened.doc} />
      </Frame>
    );
  }
  switch (source.kind) {
    case "workbook":
      return (
        <Frame icon={FileSpreadsheet} title={source.filename} meta={`sheet ‘${source.sheet}’ · cell ${cellName(source)}`}>
          <WorkbookView source={source} />
        </Frame>
      );
    case "records":
      return (
        <Frame icon={Files} title={source.title} meta={`${source.items.length} documents`}>
          <RecordsView source={source} onOpen={(doc) => setOpened({ from: source, doc })} />
        </Frame>
      );
    case "document":
      return (
        <Frame icon={FileText} title={source.filename} meta={`p. ${source.page}`}>
          <DocumentView doc={source} />
        </Frame>
      );
    case "reference":
      return (
        <Frame icon={BookOpen} title={source.title} meta={source.citation}>
          <ReferenceView source={source} />
        </Frame>
      );
    case "basis":
      return (
        <Frame icon={Info} title={source.title} meta="Determination basis: no document">
          <p className="s1-vw-basis">{source.text}</p>
        </Frame>
      );
    case "evidence":
      return (
        <Frame
          icon={Files}
          title={source.title}
          meta={`${source.records.length} reviewed ${source.records.length === 1 ? "record" : "records"}`}
        >
          <EvidenceView source={source} onOpenDocument={onOpenDocument} />
        </Frame>
      );
  }
}

/**
 * Live results: the reviewed records an amount is summed from, as the recalculation counted
 * them (a bill crossing the reporting period counts its share). Each opens in Extraction
 * review, where the page shows the value it was read from.
 */
function EvidenceView({ source, onOpenDocument }: { source: EvidenceSource; onOpenDocument?: (documentId: string) => void }) {
  const prorated = source.records.some((r) => r.shareInPeriod !== undefined && r.shareInPeriod < 1);
  return (
    <div className="s1-vw-records">
      <table className="s1-vw-records__table">
        <thead>
          <tr>
            <th>Record</th>
            {prorated ? <th className="s1-vw-num">In period</th> : null}
            <th className="s1-vw-num">{source.unit}</th>
          </tr>
        </thead>
        <tbody>
          {source.records.map((record, i) => (
            <tr key={`${record.documentId}:${i}`}>
              <td>
                {onOpenDocument ? (
                  <button className="s1-vw-input" type="button" onClick={() => onOpenDocument(record.documentId)}>
                    {record.record}
                  </button>
                ) : (
                  record.record
                )}
                {record.serviceType ? <span className="s1-muted"> · {record.serviceType}</span> : null}
              </td>
              {prorated ? (
                <td className="s1-vw-num">
                  {record.shareInPeriod === undefined ? "" : `${Math.round(record.shareInPeriod * 100)}%`}
                </td>
              ) : null}
              <td className="s1-vw-num">
                {formatQuantity(record.quantity)}
                {record.unit !== source.unit ? ` ${record.unit}` : ""}
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td colSpan={prorated ? 2 : 1}>Total</td>
            <td className="s1-vw-num">{formatQuantity(source.total)}</td>
          </tr>
        </tfoot>
      </table>
      {onOpenDocument ? (
        <p className="s1-muted s1-vw-records__hint">Open a record to see the page and the value it was read from.</p>
      ) : null}
    </div>
  );
}

function Frame({ icon: Icon, title, meta, children }: { icon: LucideIcon; title: string; meta: string; children: ReactNode }) {
  return (
    <div className="s1-xr-src s1-vw-src">
      <div className="s1-xr-src-head s1-vw-src__head">
        <span className="s1-vw-src__icon">
          <Icon className="s1-vw-ico" aria-hidden />
        </span>
        <div>
          <div className="s1-xr-src-fn">{title}</div>
          <div className="s1-muted s1-vw-src-meta">{meta}</div>
        </div>
      </div>
      <div className="s1-xr-src-body">{children}</div>
    </div>
  );
}

function columnLetter(index: number): string {
  let n = index + 1;
  let letters = "";
  while (n > 0) {
    const rest = (n - 1) % 26;
    letters = String.fromCharCode(65 + rest) + letters;
    n = Math.floor((n - 1) / 26);
  }
  return letters;
}

/** "D4": the header is sheet row 1, so data row 0 is sheet row 2. */
function cellName(source: WorkbookSource): string {
  return `${columnLetter(source.target.column)}${source.target.row + 2}`;
}

function WorkbookView({ source }: { source: WorkbookSource }) {
  const target = useRef<HTMLTableCellElement | null>(null);
  useEffect(() => {
    target.current?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
  }, [source]);
  return (
    <div className="s1-xr-sheet">
      <div className="s1-xr-sheet__scroll s1-vw-sheet">
        <table className="s1-xr-sheet__table">
          <thead>
            <tr>
              <th className="s1-xr-sheet__corner" />
              {source.columns.map((_, i) => (
                <th key={i} className="s1-xr-sheet__colhead">{columnLetter(i)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr className="s1-xr-sheet__titlerow">
              <th className="s1-xr-sheet__rowhead">1</th>
              {source.columns.map((title) => (
                <td key={title} className="s1-xr-sheet__title">{title}</td>
              ))}
            </tr>
            {source.rows.map((row, r) => (
              <tr key={r}>
                <th className="s1-xr-sheet__rowhead">{r + 2}</th>
                {source.columns.map((_, c) => {
                  const hit = r === source.target.row && c === source.target.column;
                  return (
                    <td key={c} ref={hit ? target : undefined} className={hit ? "is-target" : ""} aria-current={hit ? "true" : undefined}>
                      {row[c] ?? ""}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function RecordsView({ source, onOpen }: { source: RecordsSource; onOpen: (doc: DocumentSource) => void }) {
  const total = source.items.reduce((sum, item) => sum + item.quantity, 0);
  return (
    <div className="s1-vw-records">
      {source.missingFrom ? (
        <p className="s1-vw-records__note">Marked: in the evidence, not in the client&rsquo;s reported total.</p>
      ) : null}
      <table className="s1-vw-records__table">
        <thead>
          <tr>
            <th>Period</th>
            <th>Document</th>
            <th className="s1-vw-num">{source.unit}</th>
          </tr>
        </thead>
        <tbody>
          {source.items.map((item) => {
            const missing = item.filename === source.missingFrom;
            return (
              <tr key={item.filename} className={missing ? "is-missing" : undefined}>
                <td>{item.period}</td>
                <td>
                  <button className="s1-vw-input" type="button" onClick={() => onOpen(item)}>
                    {item.filename}
                  </button>
                  {missing ? <div className="s1-vw-records__flag">Not in the reported total</div> : null}
                </td>
                <td className="s1-vw-num">{formatQuantity(item.quantity)}</td>
              </tr>
            );
          })}
        </tbody>
        <tfoot>
          <tr>
            <td colSpan={2}>Total</td>
            <td className="s1-vw-num">{formatQuantity(total)}</td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

function DocumentView({ doc }: { doc: DocumentSource }) {
  return (
    <div className="s1-xr-paper s1-vw-doc">
      <div className="s1-xr-paper__co">{doc.issuer}</div>
      <div className="s1-xr-paper__meta">
        {doc.facility} · {doc.period}
      </div>
      {doc.lines.map((line, i) => (
        <div
          key={line.label}
          className={`s1-xr-paper__row${i === doc.highlight ? " s1-vw-doc__hit" : ""}`}
          aria-current={i === doc.highlight ? "true" : undefined}
        >
          <span>{line.label}</span>
          <span>{line.value}</span>
        </div>
      ))}
    </div>
  );
}

function ReferenceView({ source }: { source: ReferenceSource }) {
  return (
    <div className="s1-xr-sheet__scroll">
      <table className="s1-xr-sheet__table s1-vw-ref">
        <thead>
          <tr>
            {source.columns.map((column, c) => (
              <th key={column} className={c === source.target.column ? "is-target-col" : undefined}>
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {source.rows.map((row, r) => (
            <tr key={r} className={r === source.target.row ? "is-target-row" : undefined}>
              {row.map((cell, c) => {
                const hit = r === source.target.row && c === source.target.column;
                return (
                  <td key={c} className={hit ? "is-target" : undefined} aria-current={hit ? "true" : undefined}>
                    {cell}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
