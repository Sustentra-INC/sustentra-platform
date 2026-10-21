"use client";

import { FileText, Hash, Scale, Send, ShieldCheck } from "lucide-react";
import { Fragment, type ReactNode } from "react";

/** A source the assistant cited, resolved to something the user recognizes. */
export interface ResolvedRef {
  kind: "doc" | "val" | "req" | "chk" | "ref";
  id: string;
  label: string;
  onOpen?: () => void;
}

const REF = /\[(doc|val|req|chk|ref):([^\]\s]+)\]/g;

const ICON: Record<ResolvedRef["kind"], ReactNode> = {
  doc: <FileText aria-hidden />,
  val: <Hash aria-hidden />,
  req: <Send aria-hidden />,
  chk: <ShieldCheck aria-hidden />,
  ref: <Scale aria-hidden />,
};

/**
 * The assistant's answer: paragraphs, bullet and numbered lists, **bold**, and each
 * citation ([doc:…], [val:…], …) as a chip that opens its source. A ref the data
 * cannot resolve is dropped rather than shown as a broken link.
 */
export function AnswerText({ text, resolve }: { text: string; resolve: (kind: ResolvedRef["kind"], id: string) => ResolvedRef | null }) {
  const blocks = text.trim().split(/\n{2,}/);
  return (
    <div className="s1-ai__answer">
      {blocks.map((block, i) => {
        const lines = block.split("\n");
        const bullets = lines.every((l) => /^\s*([-*•]|\d+[.)])\s+/.test(l));
        if (bullets) {
          const ordered = /^\s*\d/.test(lines[0]);
          const items = lines.map((l, j) => <li key={j}>{inline(l.replace(/^\s*([-*•]|\d+[.)])\s+/, ""), resolve)}</li>);
          return ordered ? <ol key={i}>{items}</ol> : <ul key={i}>{items}</ul>;
        }
        return (
          <p key={i}>
            {lines.map((l, j) => (
              <Fragment key={j}>
                {j > 0 ? <br /> : null}
                {inline(l.replace(/^#{1,4}\s+/, ""), resolve)}
              </Fragment>
            ))}
          </p>
        );
      })}
    </div>
  );
}

function inline(text: string, resolve: (kind: ResolvedRef["kind"], id: string) => ResolvedRef | null): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let key = 0;
  const seen = new Set<string>();
  for (const match of text.matchAll(REF)) {
    out.push(...bold(text.slice(last, match.index), key++));
    last = (match.index ?? 0) + match[0].length;
    const kind = match[1] as ResolvedRef["kind"];
    const ref = resolve(kind, match[2]);
    if (!ref || seen.has(`${kind}:${ref.id}`)) continue;
    seen.add(`${kind}:${ref.id}`);
    out.push(
      ref.onOpen ? (
        <button key={`r${key++}`} type="button" className={`s1-ai__ref s1-ai__ref--${kind}`} onClick={ref.onOpen} title={ref.label}>
          {ICON[kind]}
          <span>{ref.label}</span>
        </button>
      ) : (
        <span key={`r${key++}`} className={`s1-ai__ref s1-ai__ref--${kind}`} title={ref.label}>
          {ICON[kind]}
          <span>{ref.label}</span>
        </span>
      )
    );
  }
  out.push(...bold(text.slice(last), key++));
  return out;
}

function bold(text: string, key: number): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") && part.length > 4 ? (
      <strong key={`${key}-${i}`}>{part.slice(2, -2)}</strong>
    ) : (
      <Fragment key={`${key}-${i}`}>{part}</Fragment>
    )
  );
}
