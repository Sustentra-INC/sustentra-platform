"use client";

import { useEffect, useRef, useState } from "react";

import type { NavKey } from "./S1Chrome";

/**
 * Sustentra assistant — a small, integrated agent (bottom-right on every screen).
 * On open it briefs the key indicators of the current page; the input answers
 * questions from a curated knowledge base (offline demo, no backend call), so it
 * gives point-blank answers about the numbers, methodology and workflow.
 */

type Msg = { role: "assistant" | "user"; text: string };

const PAGE_BRIEF: Partial<Record<NavKey, { title: string; points: string[] }>> = {
  dashboard: {
    title: "This dashboard summarises the Cascade Provisions engagement.",
    points: [
      "Documents held 148 across 3 facilities; Values reviewed 34 / 46 (74% accepted).",
      "Open requests 3; Coverage ready 58% (34 of 59 checks).",
      "Verified emissions by category compares Scope 1 (stationary + mobile) and Scope 2 (location + market).",
      "The coverage donut and the phase tracker show how far the engagement has progressed.",
    ],
  },
  setup: {
    title: "Setup defines what the engagement covers.",
    points: [
      "Client, reporting period, regulation (California SB 253) and methodology (GHG Protocol).",
      "Three facilities: Tualatin Plant, Kent Cannery, Modesto Bottling.",
      "The in-scope field list is what makes the rest of the product finite.",
    ],
  },
  upload: {
    title: "Upload brings the client's documents in.",
    points: [
      "Each file becomes a row in the Evidence workspace as it is read.",
      "The prepared electricity invoice is the one already staged for the demo.",
    ],
  },
  evidence: {
    title: "The Evidence workspace is every document held.",
    points: [
      "Grouped by document type per facility; the group headers are collapsible.",
      "Each row shows facility, type, processing state (Extracted / Blocked / Extracting) and any issue.",
      "You can add a document to requests or open it in Extraction review.",
    ],
  },
  requests: {
    title: "Evidence requests are the open asks to the client.",
    points: [
      "3 open — 1 sent, 2 raised. They assemble into a single client email.",
      "Nothing is sent automatically; you copy the message or open it in your mail.",
    ],
  },
  coverage: {
    title: "Check coverage shows what can and cannot be checked.",
    points: [
      "34 inputs present, 12 missing, 8 not applicable, 5 out of scope.",
      "This is input readiness, not a pass/fail — rule evaluation is not wired yet.",
    ],
  },
  results: {
    title: "Verification results is the workpaper: reported vs recomputed.",
    points: [
      "Total emissions 13,540 tCO₂e; materiality threshold 677 tCO₂e (5%).",
      "Identified misstatement 179 tCO₂e; uncorrected exceptions 165 tCO₂e (below threshold).",
      "Open any row's ‘Show working’ to see the formula, emission factor with reference, extracted data and sources.",
      "Outcomes: Held (within tolerance), Exception (exceeds), Could not check (no recompute path).",
    ],
  },
  output: {
    title: "Output is the assurance deliverable.",
    points: [
      "An independent limited-assurance statement with verified emissions by scope.",
      "Plus the corrections register, evidence basis and sign-off.",
    ],
  },
};

const KB: { keys: string[]; answer: string }[] = [
  {
    keys: ["materiality", "misstatement", "threshold", "tolerance"],
    answer:
      "Materiality is the 5% threshold — 677 tCO₂e of the 13,540 tCO₂e total. Misstatements below it don't change the opinion. Right now identified misstatement is 179 tCO₂e (1.3%) and uncorrected exceptions are 165 tCO₂e (1.2%) — below the threshold. But 5 data points couldn't be checked yet, so the register isn't complete and the conclusion stays provisional.",
  },
  {
    keys: ["emission factor", "factor", "egrid", "epa", "kgco2e"],
    answer:
      "Location-based electricity uses 0.223 kgCO₂e/kWh (eGRID 2024, WECC/NWPP subregion). Natural gas uses 5.30 kgCO₂e/therm (EPA Emission Factors Hub, Mar 2024). Each factor and its source is shown under a row's ‘Show working’ on Verification results, next to the formula and the extracted data.",
  },
  {
    keys: ["scope 2", "location", "market", "location-based", "market-based"],
    answer:
      "Scope 2 is purchased electricity, always reported two ways: location-based uses the grid-average factor for the region (eGRID), while market-based uses supplier-specific or contractual factors. Here location-based is 3,910 tCO₂e and market-based 4,205 tCO₂e.",
  },
  {
    keys: ["scope 1", "combustion", "gas", "diesel", "refrigerant", "fugitive"],
    answer:
      "Scope 1 is direct emissions: stationary combustion (natural gas), mobile combustion (fleet diesel) and fugitive emissions (refrigerant). Only the stationary-gas path is recomputed today; the others read ‘could not check’ because the recompute path isn't built yet.",
  },
  {
    keys: ["coverage", "inputs present", "inputs missing", "checks"],
    answer:
      "Coverage shows what the evidence lets us check: 34 inputs present, 12 missing, 8 not applicable, 5 out of scope — 59 checks in total. It's input readiness, not a pass/fail; the rule engine isn't evaluating assertions yet, so a check with inputs present hasn't been ‘run’.",
  },
  {
    keys: ["held", "exception", "could not check", "outcome"],
    answer:
      "Held means the recompute landed within the 5% tolerance. Exception means it exceeded it — e.g. Kent Cannery natural gas recomputed 1,705 vs 1,540 reported, +10.7%. Could not check means there's no recompute path or the documentation is missing.",
  },
  {
    keys: ["highlight", "extraction", "document", "cross-check", "cross check", "source"],
    answer:
      "In Extraction review the document sits in the middle with the extracted figures highlighted. Clicking a highlight selects its value card on the right; each value can be Accepted, Corrected, or Added to requests. The highlighted 182,400 kWh, for example, ties straight to the electricity line on the invoice.",
  },
  {
    keys: ["cascade", "client", "who", "facilities", "facility"],
    answer:
      "Cascade Provisions Co. is the client under verification — a food producer with three facilities (Tualatin Plant, Kent Cannery, Modesto Bottling), reporting Scope 1 and Scope 2 under California SB 253 at limited assurance.",
  },
  {
    keys: ["sb 253", "sb253", "regulation", "law", "california"],
    answer:
      "California SB 253 (the Climate Corporate Data Accountability Act) requires large companies doing business in California to report Scope 1 and Scope 2 greenhouse-gas emissions with third-party assurance. That assurance engagement is what this workpaper supports.",
  },
  {
    keys: ["requests", "request", "email", "client ask"],
    answer:
      "3 requests are open — 1 sent, 2 raised. Requests are assembled into a single client email; nothing sends from the product. A problem that comes back becomes a new ask linked to the old one.",
  },
  {
    keys: ["assurance", "limited", "opinion", "conclusion", "statement"],
    answer:
      "This is a limited-assurance engagement: the opinion is negative-form — ‘nothing has come to our attention’ that the emissions are materially misstated. The draft statement, verified emissions by scope, and the corrections register are on the Output screen.",
  },
  {
    keys: ["reset", "start over", "restart"],
    answer: "Reset (top-right of the context bar, or the sidebar’s Collapse area) returns the demo to the very start.",
  },
];

function respond(question: string, page?: NavKey): string {
  const q = question.toLowerCase();
  let best: { score: number; answer: string } | null = null;
  for (const entry of KB) {
    const score = entry.keys.reduce((s, k) => (q.includes(k) ? s + k.length : s), 0);
    if (score > 0 && (!best || score > best.score)) best = { score, answer: entry.answer };
  }
  if (best) return best.answer;
  const brief = page ? PAGE_BRIEF[page] : undefined;
  return `I can explain the figures and methodology on this screen. Try asking about coverage, materiality, emission factors, Scope 1 vs Scope 2, or a specific outcome.${
    brief ? ` On this page: ${brief.points[0]}` : ""
  }`;
}

const SUGGESTIONS = ["Explain materiality", "What emission factor is used?", "What does coverage mean?"];

export function AssistantWidget({ page }: { page?: NavKey }) {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const bodyRef = useRef<HTMLDivElement>(null);

  // Brief the current page whenever the panel opens.
  useEffect(() => {
    if (!open) return;
    const brief = page ? PAGE_BRIEF[page] : undefined;
    const intro: Msg = {
      role: "assistant",
      text: brief
        ? `${brief.title}\n\n${brief.points.map((p) => `• ${p}`).join("\n")}\n\nAsk me anything about these numbers.`
        : "Hi — I'm the Sustentra assistant. Ask me about the numbers, the methodology, or the workflow on any screen.",
    };
    setMessages([intro]);
  }, [open, page]);

  useEffect(() => {
    bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight });
  }, [messages]);

  function send(text: string) {
    const t = text.trim();
    if (!t) return;
    setMessages((m) => [...m, { role: "user", text: t }, { role: "assistant", text: respond(t, page) }]);
    setInput("");
  }

  return (
    <>
      {open ? (
        <section className="s1-ai" role="dialog" aria-label="Sustentra assistant">
          <header className="s1-ai__head">
            <span className="s1-ai__brand">
              <img className="s1-ai__mark" src="/sustentra-mark.png" alt="" aria-hidden />
              Sustentra assistant
            </span>
            <button className="s1-ai__close" type="button" aria-label="Close" onClick={() => setOpen(false)}>
              ✕
            </button>
          </header>
          <div className="s1-ai__body" ref={bodyRef}>
            {messages.map((m, i) => (
              <div key={i} className={`s1-ai__msg s1-ai__msg--${m.role}`}>
                {m.text}
              </div>
            ))}
          </div>
          <div className="s1-ai__sugs">
            {SUGGESTIONS.map((s) => (
              <button key={s} className="s1-ai__sug" type="button" onClick={() => send(s)}>
                {s}
              </button>
            ))}
          </div>
          <form
            className="s1-ai__input"
            onSubmit={(e) => {
              e.preventDefault();
              send(input);
            }}
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask about this page…"
              aria-label="Ask the assistant"
            />
            <button className="s1-ai__send" type="submit" aria-label="Send">
              ↑
            </button>
          </form>
        </section>
      ) : null}
      <button
        className={`s1-ai-fab${open ? " is-open" : ""}`}
        type="button"
        aria-label={open ? "Close assistant" : "Open Sustentra assistant"}
        title="Sustentra assistant"
        onClick={() => setOpen((v) => !v)}
      >
        <img className="s1-ai-fab__mark" src="/sustentra-mark.png" alt="Sustentra" />
      </button>
    </>
  );
}
