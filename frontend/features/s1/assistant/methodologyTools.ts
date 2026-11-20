import { api } from "../../../lib/api";
import { runAssistantTool, type AssistantData } from "./tools";

/**
 * The assistant's two Methodology tools. They read the server (the same sign-in, organization and engagement
 * access as the Methodology page; another organization's engagement is a 404) and return its answer as it is:
 * the stored reason, quote, page and checks, built by the server from stored data. Read-only (GET).
 */

const MAX_RESULT_CHARS = 18_000;
const base = (data: AssistantData) => `/engagements/${encodeURIComponent(data.engagement.engagementId)}/methodology-assistant`;

const clip = (json: string) => (json.length > MAX_RESULT_CHARS ? `${json.slice(0, MAX_RESULT_CHARS)}\u2026 (cut: narrow the question)` : json);

export const METHODOLOGY_TOOLS = new Set(["explain_methodology_suggestion", "get_methodology_summary"]);

/** Runs any assistant tool: the Methodology tools over the API, the others over the data in the browser. */
export async function runAssistantToolAsync(name: string, input: Record<string, unknown>, data: AssistantData): Promise<string> {
  if (!METHODOLOGY_TOOLS.has(name)) return runAssistantTool(name, input, data);
  try {
    const query = new URLSearchParams();
    if (name === "explain_methodology_suggestion") {
      if (typeof input.question === "string") query.set("q", input.question.slice(0, 300));
      if (typeof input.field === "string") query.set("field", input.field.slice(0, 100));
      return clip(JSON.stringify(await api<unknown>(`${base(data)}/explain?${query}`)));
    }
    if (typeof input.document === "string") query.set("document", input.document.slice(0, 200));
    return clip(JSON.stringify(await api<unknown>(`${base(data)}/summary?${query}`)));
  } catch {
    return JSON.stringify({ error: "The methodology suggestions could not be read just now. Say so; do not guess." });
  }
}
