/**
 * The Sustentra assistant: what it is told, and the tools it may call. Shared by the
 * server route (which holds the API key and sends these to the model, fixed, so the
 * route is never a general-purpose proxy) and the browser (which runs the tools over
 * the engagement data the signed-in user already sees).
 *
 * Retrieval, not training: nothing is learned from an engagement. Each question, the
 * model looks up what it needs through read-only tools and cites what it used.
 */

export const ASSISTANT_MODEL = "claude-sonnet-5-5";
/** Per step: an answer, or the next tool calls. */
export const ASSISTANT_MAX_TOKENS = 1200;
/** Tool rounds per question before the browser stops and asks for an answer. */
export const ASSISTANT_MAX_STEPS = 6;
/** The largest request body the route accepts (the conversation, tool results included). */
export const ASSISTANT_MAX_BODY_BYTES = 400_000;

export const PAGE_LABEL: Record<string, string> = {
  dashboard: "Dashboard",
  setup: "Setup",
  upload: "Upload",
  evidence: "Evidence",
  requests: "Coverage & requests",
  coverage: "Coverage & requests",
  methodology: "Methodology review",
  results: "Verification results",
  output: "Output",
};

export function systemPrompt(page: string | null): string {
  const where = page && PAGE_LABEL[page] ? `The user is on the ${PAGE_LABEL[page]} screen.` : "";
  return [
    "You are the Sustentra assistant, inside Sustentra, a workspace for greenhouse-gas (GHG) verification auditors.",
    "Auditors use it to check a company's Scope 1 and Scope 2 emissions against the evidence (bills, invoices, logs,",
    "the client's inventory workbook) and to issue a limited-assurance statement, for example under California SB 253",
    "with ISO 14064-3. The users are compliance professionals: plain language, short answers, no filler.",
    "",
    "How to answer:",
    "- Look things up with the tools before answering anything about this engagement. Never invent a figure,",
    "  a document, a facility or a status. If the tools do not have it, say what is missing.",
    "- Cite every figure, document, request or check you rely on, right after it, with the ref the tool gave you,",
    "  in square brackets: [doc:ID], [val:ID], [req:ID], [chk:ID]. Use refs exactly as given; never make one up.",
    "- Use lookup_reference for regulations, methods and how Sustentra works; cite it as [ref:TOPIC].",
    "- You read; you never decide. Accepting, correcting or requesting a value, raising a finding and signing off",
    "  are the auditor's calls. You may suggest what to look at, and draft text (a request to the client, a note)",
    "  for the auditor to edit and send themselves.",
    "- Do not call anything verified, complete, confirmed or all clear before the statement is issued. Say",
    "  reviewed, accepted, inputs present, provisional.",
    "- Keep answers under about 150 words unless asked for more. Use short paragraphs or a short list.",
    "  Numbers: thousands separators, units, tCO2e for emissions.",
    "- Decline requests unrelated to this engagement or GHG verification, in one sentence.",
    "",
    where,
  ]
    .join("\n")
    .trim();
}

export interface ToolSpec {
  name: string;
  description: string;
  input_schema: { type: "object"; properties: Record<string, unknown>; required?: string[] };
}

const text = (description: string) => ({ type: "string", description });

export const ASSISTANT_TOOLS: ToolSpec[] = [
  {
    name: "get_engagement",
    description:
      "The engagement: client, reporting period, regulation, method, scope, assurance level and standard, " +
      "materiality threshold, facilities with addresses, engagement team, and the progress figures on the dashboard.",
    input_schema: { type: "object", properties: {} },
  },
  {
    name: "search_documents",
    description:
      "Documents held for the engagement, with type, facility, period, processing state, issues, notes, " +
      "who uploaded each and when. Filter by free text (file name, type, facility), facility, type or status. " +
      "Status is one of: extracted, blocked, extracting, needs_you, withdrawn.",
    input_schema: {
      type: "object",
      properties: {
        query: text("Words to match in the file name, type or facility."),
        facility: text("Facility name, e.g. Kent Cannery."),
        type: text("Document type, e.g. Natural gas bill."),
        status: text("extracted | blocked | extracting | needs_you | withdrawn"),
      },
    },
  },
  {
    name: "get_values",
    description:
      "Values read from the documents: what each is, the value and unit, scope, period, facility, the page it " +
      "came from, its review state (to_review, accepted, corrected, requested) and its record (who did what). " +
      "Filter by document id, facility, free text (e.g. 'natural gas', 'R-404A') or review state.",
    input_schema: {
      type: "object",
      properties: {
        document_id: text("A document id from search_documents (the part after doc:)."),
        facility: text("Facility name."),
        query: text("Words to match in what the value is, its document or its period."),
        review_state: text("to_review | accepted | corrected | requested"),
      },
    },
  },
  {
    name: "get_coverage",
    description:
      "What can and cannot be checked with the evidence held: each check, the data points it covers, its status " +
      "(inputs_present, inputs_missing, not_applicable, out_of_scope) and the reason. Status is input readiness, " +
      "not a pass or fail.",
    input_schema: { type: "object", properties: {} },
  },
  {
    name: "get_requests",
    description: "Requests to the client: the item, type, what is needed, state (not_yet_sent, requested, resolved, withdrawn) and history.",
    input_schema: { type: "object", properties: { state: text("Optional state filter.") } },
  },
  {
    name: "get_results",
    description:
      "Verification results: per box (Scope 1, Scope 2 location-based, Scope 2 market-based, biogenic) each " +
      "reported line with reported and recomputed tCO2e, the difference, share and % material, and per facility " +
      "the cause of any difference and whether it was examined.",
    input_schema: { type: "object", properties: {} },
  },
  {
    name: "get_activity",
    description: "The engagement's activity log, newest first: uploads, reviews, document changes, requests and findings.",
    input_schema: { type: "object", properties: { limit: { type: "number", description: "How many entries (default 25)." } } },
  },
  {
    name: "lookup_reference",
    description:
      "Reference material on regulations, methods and how Sustentra works. Topics: sb253, ghg_protocol_scopes, " +
      "scope2_methods, materiality, limited_assurance, emission_factors, refrigerants, coverage, review_states, " +
      "requests, sustentra_workflow.",
    input_schema: { type: "object", properties: { topic: text("One of the topics listed.") }, required: ["topic"] },
  },
];

export const TOOL_NAMES = new Set(ASSISTANT_TOOLS.map((tool) => tool.name));

/** What the browser shows while a tool runs. */
export const TOOL_ACTIVITY: Record<string, string> = {
  get_engagement: "Reading the engagement",
  search_documents: "Searching the documents",
  get_values: "Reading the values",
  get_coverage: "Checking coverage",
  get_requests: "Reading the requests",
  get_results: "Reading the verification results",
  get_activity: "Reading the activity log",
  lookup_reference: "Looking up the reference",
};
