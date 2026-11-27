"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import type { TraceSourceRef } from "../../api/calcTrace";

/**
 * A dotted-underlined value that opens its source beside it (the same look and behaviour as the panel's
 * SourceNote). The trigger is a button, so Tab reaches it and Enter or Space opens it; Escape, a click
 * elsewhere or a scroll closes it. A source the trace does not carry says "Not available".
 */

const REFERENCE_KIND = (citation: string): string => {
  if (/egrid/i.test(citation)) return "eGRID";
  if (/ipcc|\bAR[4-6]\b/i.test(citation)) return "IPCC assessment report";
  if (/\bEPA\b|\bHub\b/i.test(citation)) return "EPA Hub table";
  return "Reference entry";
};

function openable(source: TraceSourceRef | undefined): source is TraceSourceRef & { document_id: string } {
  return Boolean(source && (source.kind === "document" || source.kind === "workbook_cell") && source.document_id);
}

function SourceBody({ source, side }: { source: TraceSourceRef | undefined; side: "company" | "recomputed" }) {
  if (!source) {
    return (
      <>
        <p className="s1-cp-pop__kind">{side === "company" ? "Company-reported" : "Recomputed"}</p>
        <p className="s1-muted">Source: Not available</p>
      </>
    );
  }
  switch (source.kind) {
    case "document":
      return (
        <>
          <p className="s1-cp-pop__kind">Document</p>
          <p>{source.file_name ?? source.document_id ?? "Not available"}</p>
          <p className="s1-muted">Page: {source.page ?? "Not available"}</p>
          {source.quote ? <p className="s1-muted">“{source.quote}”</p> : null}
        </>
      );
    case "workbook_cell":
      return (
        <>
          <p className="s1-cp-pop__kind">Company-prepared workbook · cell {source.cell ?? "Not available"}</p>
          <p>{source.file_name ?? "Not available"}</p>
          {source.sheet ? <p className="s1-muted">Sheet: {source.sheet}</p> : null}
          {source.quote ? <p className="s1-muted">“{source.quote}”</p> : null}
        </>
      );
    case "reference": {
      const citation = source.citation ?? source.dataset ?? "";
      return (
        <>
          <p className="s1-cp-pop__kind">{REFERENCE_KIND(citation)}</p>
          <p>Citation: {citation || "Not available"}</p>
        </>
      );
    }
    case "methodology":
      return (
        <>
          <p className="s1-cp-pop__kind">Methodology review</p>
          <p>{source.label ?? source.field ?? "Not available"}</p>
        </>
      );
    case "entered":
      return (
        <>
          <p className="s1-cp-pop__kind">Entered input</p>
          <p>Entered by {source.by ?? "Not available"}</p>
          {source.reason ? <p className="s1-muted">{source.reason}</p> : null}
        </>
      );
    case "derived":
      return (
        <>
          <p className="s1-cp-pop__kind">Derived</p>
          <p className="s1-muted">{source.from?.length ? `From ${source.from.length} value${source.from.length === 1 ? "" : "s"} on the line.` : "Calculated from other values."}</p>
        </>
      );
    default:
      return <p className="s1-muted">Source: Not available</p>;
  }
}

export function TraceSourceNote({
  label,
  source,
  side = "recomputed",
  onOpenDocument,
}: {
  label: string;
  source?: TraceSourceRef;
  /** Which row the value sits on; it names a source the trace does not carry. */
  side?: "company" | "recomputed";
  /** "Open in Evidence →" is shown for a document or workbook source when this is given. */
  onOpenDocument?: (documentId: string, valueId?: string) => void;
}) {
  const [at, setAt] = useState<{ top: number; left: number } | null>(null);
  const button = useRef<HTMLButtonElement>(null);
  const pop = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!at) return;
    const close = () => setAt(null);
    const onDown = (e: PointerEvent) => {
      const target = e.target as Node;
      if (!button.current?.contains(target) && !pop.current?.contains(target)) close();
    };
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key !== "Escape") return;
      close();
      button.current?.focus();
    };
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    window.addEventListener("scroll", close, true);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", close, true);
    };
  }, [at]);

  function toggle() {
    if (at) return setAt(null);
    const rect = button.current?.getBoundingClientRect();
    setAt({ top: rect ? rect.bottom + window.scrollY : 0, left: rect ? rect.left + window.scrollX : 0 });
  }

  return (
    <>
      <button ref={button} className="s1-cp-src" type="button" aria-expanded={Boolean(at)} onClick={toggle}>
        {label}
      </button>
      {at
        ? createPortal(
            <div ref={pop} className="s1-cp-pop" role="dialog" aria-label={`Source of ${label}`} style={{ top: at.top, left: at.left }}>
              <SourceBody source={source} side={side} />
              {onOpenDocument && openable(source) ? (
                <button
                  className="s1-cp-pop__open"
                  type="button"
                  onClick={() => {
                    setAt(null);
                    onOpenDocument(source.document_id, source.candidate_id);
                  }}
                >
                  Open in Evidence →
                </button>
              ) : null}
            </div>,
            document.body,
          )
        : null}
    </>
  );
}
