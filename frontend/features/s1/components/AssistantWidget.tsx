"use client";

import { useEffect, useRef, useState } from "react";

import type { NavKey } from "./S1Chrome";

/**
 * Sustentra assistant — a small, integrated agent (bottom-right on every screen).
 * On open it briefs the current page; the input answers questions from a curated
 * knowledge base (no backend call). The demo (fixture data) has briefs with the demo
 * engagement's figures; on live data (``live``) it explains how the product works
 * and never quotes a figure, because the figures are the engagement's own.
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

/** Live data: what each page does, without figures (the page itself shows them). */
const LIVE_BRIEF: Partial<Record<NavKey, { title: string; points: string[] }>> = {
  dashboard: {
    title: "The dashboard shows this engagement as it stands.",
    points: [
      "Documents held, values reviewed, open requests and checks ready come from the engagement's own records.",
      "Recalculated emissions by category use reviewed values only, on the EPA GHG Emission Factors Hub 2025.",
      "The phase tracker shows how far Setup, evidence intake, review and verification have got.",
    ],
  },
  setup: {
    title: "Setup defines what the engagement covers.",
    points: [
      "The reporting period decides what counts: a bill crossing it is prorated by days, one outside it is left out.",
      "Each facility can carry its address and eGRID subregion; bills are matched to facilities by name or address.",
      "The materiality threshold is the tolerance used on Verification results.",
    ],
  },
  upload: {
    title: "Upload brings the client's documents in.",
    points: [
      "PDFs, scans and photos, Word (.docx), Excel and CSV files, up to 25 MB each.",
      "Each file is read and classified (fuel bill, vehicle fuel, electricity bill, refrigerant service record), " +
        "then its values are extracted for review.",
      "A file that needs you (unreadable, or not a supported kind of evidence) says so in the list.",
    ],
  },
  evidence: {
    title: "The Evidence workspace is every document held.",
    points: [
      "Grouped by facility and document type, with what was read from each document.",
      "Set a document's facility or type, withdraw it, mark it as a duplicate or superseded: these decisions change what is counted.",
      "Open a document in Extraction review to accept, correct or enter its values.",
    ],
  },
  requests: {
    title: "Evidence requests are the asks to the client.",
    points: [
      "Each request records what is asked, who raised it and when.",
      "Nothing is sent from the product: copy the message or open it in your mail.",
    ],
  },
  coverage: {
    title: "Check coverage shows what the recalculation could and could not check.",
    points: [
      "Each row says whether its inputs are present, missing (and which), not applicable, or out of scope.",
      "It restates the recalculation's own result; nothing on it is assumed.",
    ],
  },
  results: {
    title: "Verification results compares each reported data point with its recalculated value.",
    points: [
      "Recalculation uses reviewed values only, following the equations in the GHG Required Data workbook.",
      "Held is within the materiality tolerance, Exception exceeds it, Could not check means a reported value, a review or an input is missing.",
      "Show working lists the formula, each input with its source document, and each factor with its EPA table and row.",
      "Recalculation inputs (at the top) takes grid regions, fuel choices, certificates, refrigerant GWPs and the reported values.",
    ],
  },
  output: {
    title: "Output is the draft working paper from the live results.",
    points: [
      "Download the whole workpaper as an Excel file: summary, data points, working, evidence, reviewed values, requests, findings and what was left out.",
      "It is not an assurance opinion; the conclusion is the verifier's.",
    ],
  },
};

const LIVE_KB: { keys: string[]; answer: string }[] = [
  {
    keys: ["materiality", "misstatement", "threshold", "tolerance"],
    answer:
      "The materiality threshold comes from Setup. Each reported data point is compared with its recalculated value: a difference within the threshold is Held, beyond it is an Exception. The tiles on Verification results add up the identified and uncorrected misstatement on the Scope 1 and Scope 2 (location-based) totals. While anything is awaiting review or an input, the conclusion stays provisional.",
  },
  {
    keys: ["emission factor", "factor", "egrid", "epa", "gwp"],
    answer:
      "Factors come from the EPA GHG Emission Factors Hub 2025: Table 1 for fuel burned on site, Table 2 for vehicle fuel, Table 6 (eGRID subregions) for electricity, and Tables 11 and 12 for GWPs (AR5 unless AR6 is chosen under Recalculation inputs). Show working names the table and row of every factor used.",
  },
  {
    keys: ["scope 2", "location", "market", "location-based", "market-based", "electricity", "certificate"],
    answer:
      "Scope 2 is purchased electricity, reported two ways. Location-based multiplies each facility's MWh by its eGRID subregion factor. Market-based first applies the renewable energy certificates entered under Recalculation inputs, then the same factors to the electricity they do not cover.",
  },
  {
    keys: ["scope 1", "combustion", "gas", "diesel", "fuel", "vehicle"],
    answer:
      "Scope 1 is direct emissions. Fuel burned on site and vehicle fuel are recalculated from reviewed bills and fuel records; refrigerants and fire-suppression gases from reviewed service records. Vehicle CH₄ and N₂O are added once you enter vehicle groups under Recalculation inputs: on-road vehicles by distance and model year, non-road equipment by the fuel it used. Process emissions are not recalculated yet.",
  },
  {
    keys: ["refrigerant", "fugitive", "hfc", "r-22", "r-410a", "fire suppression"],
    answer:
      "Refrigerant emissions use the simplified material balance once per refrigerant: (P_N − C_N) + P_S + (C_D − R_D), where P_S is refrigerant added when servicing, P_N and C_N are refrigerant charged into new equipment and its full charge, and C_D and R_D are the full charge of retired equipment and what was recovered. CFCs and HCFCs such as R-22 are listed but not counted in Scope 1. A refrigerant the EPA Hub does not list asks for its GWP.",
  },
  {
    keys: ["coverage", "inputs present", "inputs missing", "checks"],
    answer:
      "Check coverage shows, for each part of the recalculation, whether its inputs are present, missing (and which ones), not applicable, or out of scope. It restates the recalculation's own result.",
  },
  {
    keys: ["held", "exception", "could not check", "outcome", "out of scope"],
    answer:
      "Held: the recalculated value is within the materiality tolerance of the reported one. Exception: it is beyond it. Could not check: the reported value is not entered, a value is awaiting review, or an input is missing. Out of scope: not recalculated yet.",
  },
  {
    keys: ["highlight", "extraction", "document", "cross-check", "cross check", "source", "review", "accept"],
    answer:
      "In Extraction review each value shows where it was read on the page. Accept it, correct it, or enter it when the extractor did not find it. Only accepted or corrected values reach the numbers.",
  },
  {
    keys: ["period", "prorate", "prorated", "outside"],
    answer:
      "Only days inside the reporting period count: a bill that crosses it is prorated by days, and one entirely outside it is listed as left out instead of counted.",
  },
  {
    keys: ["withdraw", "duplicate", "supersede", "left out"],
    answer:
      "In the Evidence workspace you can withdraw a document, mark it as a duplicate, or say a newer one supersedes it. Those documents are left out of the numbers and listed with the reason under Recalculation inputs.",
  },
  {
    keys: ["requests", "request", "email", "client ask"],
    answer:
      "Requests are the asks to the client, each with who raised it and when. Nothing sends from the product: copy the message or open it in your mail.",
  },
  {
    keys: ["excel", "export", "download", "workpaper"],
    answer:
      "Output has the whole workpaper as an Excel download: summary, data points, working, evidence register, reviewed values, requests, findings, and what was left out.",
  },
  {
    keys: ["sb 253", "sb253", "regulation", "law", "california"],
    answer:
      "California SB 253 (the Climate Corporate Data Accountability Act) requires large companies doing business in California to report Scope 1 and Scope 2 greenhouse-gas emissions with third-party assurance. That assurance engagement is what this workpaper supports.",
  },
];

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

export function respond(question: string, page?: NavKey, live = false): string {
  const q = question.toLowerCase();
  let best: { score: number; answer: string } | null = null;
  for (const entry of live ? LIVE_KB : KB) {
    const score = entry.keys.reduce((s, k) => (q.includes(k) ? s + k.length : s), 0);
    if (score > 0 && (!best || score > best.score)) best = { score, answer: entry.answer };
  }
  if (best) return best.answer;
  const brief = page ? (live ? LIVE_BRIEF : PAGE_BRIEF)[page] : undefined;
  if (live) {
    return `I can explain how the figures on this screen are worked out. Try asking about materiality, emission factors, Scope 1 or Scope 2, refrigerants, coverage, or what an outcome means.${
      brief ? ` On this page: ${brief.points[0]}` : ""
    }`;
  }
  return `I can explain the figures and methodology on this screen. Try asking about coverage, materiality, emission factors, Scope 1 vs Scope 2, or a specific outcome.${
    brief ? ` On this page: ${brief.points[0]}` : ""
  }`;
}

const SUGGESTIONS = ["Explain materiality", "What emission factor is used?", "What does coverage mean?"];

/** ``live``: the app is on the engagement's real data, so answers explain methods, not demo figures. */
export function AssistantWidget({ page, live = false }: { page?: NavKey; live?: boolean }) {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const bodyRef = useRef<HTMLDivElement>(null);

  // Brief the current page whenever the panel opens (or the page changes while
  // open). Adjusting state during render on a key change, instead of in an
  // effect, avoids a cascading re-render (react-hooks/set-state-in-effect).
  const briefKey = open ? `open|${page ?? ""}` : "closed";
  const [shownBriefKey, setShownBriefKey] = useState(briefKey);
  if (briefKey !== shownBriefKey) {
    setShownBriefKey(briefKey);
    if (open) {
      const brief = page ? (live ? LIVE_BRIEF : PAGE_BRIEF)[page] : undefined;
      const intro: Msg = {
        role: "assistant",
        text: brief
          ? `${brief.title}\n\n${brief.points.map((p) => `• ${p}`).join("\n")}\n\nAsk me anything about ${live ? "how this works" : "these numbers"}.`
          : "Hi — I'm the Sustentra assistant. Ask me about the numbers, the methodology, or the workflow on any screen.",
      };
      setMessages([intro]);
    }
  }

  useEffect(() => {
    bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight });
  }, [messages]);

  function send(text: string) {
    const t = text.trim();
    if (!t) return;
    setMessages((m) => [...m, { role: "user", text: t }, { role: "assistant", text: respond(t, page, live) }]);
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
