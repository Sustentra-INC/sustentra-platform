import { TOOL_NAMES } from "./spec";

/** The conversation as the assistant route accepts it: text, the model's tool calls, and tool results. */

const MAX_MESSAGES = 60;
const MAX_TEXT = 4000;

export type Block =
  | { type: "text"; text: string }
  | { type: "tool_use"; id: string; name: string; input: Record<string, unknown> }
  | { type: "tool_result"; tool_use_id: string; content: string };
export type Message = { role: "user" | "assistant"; content: string | Block[] };

/** The conversation, rebuilt from allowed fields only; null when anything is off. */
export function sanitizeMessages(raw: unknown): Message[] | null {
  if (!Array.isArray(raw) || raw.length === 0 || raw.length > MAX_MESSAGES) return null;
  const out: Message[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") return null;
    const { role, content } = item as { role?: unknown; content?: unknown };
    if (role !== "user" && role !== "assistant") return null;
    if (typeof content === "string") {
      if (!content.trim() || content.length > MAX_TEXT) return null;
      out.push({ role, content });
      continue;
    }
    if (!Array.isArray(content) || content.length === 0) return null;
    const blocks: Block[] = [];
    for (const block of content) {
      const b = block as Record<string, unknown>;
      if (b?.type === "text" && typeof b.text === "string" && b.text.length <= 20_000) {
        if (b.text.trim()) blocks.push({ type: "text", text: b.text });
      } else if (role === "assistant" && b?.type === "tool_use" && typeof b.id === "string" && typeof b.name === "string"
        && TOOL_NAMES.has(b.name) && b.input && typeof b.input === "object") {
        blocks.push({ type: "tool_use", id: b.id, name: b.name, input: b.input as Record<string, unknown> });
      } else if (role === "user" && b?.type === "tool_result" && typeof b.tool_use_id === "string" && typeof b.content === "string"
        && b.content.length <= 20_000) {
        blocks.push({ type: "tool_result", tool_use_id: b.tool_use_id, content: b.content });
      } else {
        return null;
      }
    }
    if (blocks.length) out.push({ role, content: blocks });
  }
  return out[0]?.role === "user" ? out : null;
}

