import { sanitizeMessages, type Block } from "../../../features/s1/assistant/sanitize";
import {
  ASSISTANT_MAX_BODY_BYTES,
  ASSISTANT_MAX_TOKENS,
  ASSISTANT_MODEL,
  ASSISTANT_TOOLS,
  PAGE_LABEL,
  systemPrompt,
} from "../../../features/s1/assistant/spec";

/**
 * The demo's assistant, server side: holds the Anthropic API key and forwards one step of
 * the conversation, streaming the answer back as newline-delimited JSON.
 *
 * Not a general proxy: the instructions, tools, model and token limit are fixed here; the
 * browser sends only the conversation (its text and the results of the tools it ran over
 * the demo data). Only on the demo (fixture data mode) and only with ANTHROPIC_API_KEY set.
 * Limits: a per-visitor rate and a daily cap per server instance; the hard ceiling is the
 * spend limit on the Anthropic workspace.
 */

export const runtime = "nodejs";
export const maxDuration = 60;

const PER_VISITOR = { windowMs: 10 * 60_000, steps: Number(process.env.ASSISTANT_VISITOR_STEPS ?? 60) };
const DAILY_STEPS = Number(process.env.ASSISTANT_DAILY_STEPS ?? 1500);

const visitors = new Map<string, number[]>();
let today = { date: "", steps: 0 };

function reply(status: number, message: string): Response {
  return Response.json({ error: message }, { status, headers: { "cache-control": "no-store" } });
}

function allow(visitor: string, now: number): string | null {
  const date = new Date(now).toISOString().slice(0, 10);
  if (today.date !== date) today = { date, steps: 0 };
  if (today.steps >= DAILY_STEPS) return "The demo assistant has answered all it can today. Try again tomorrow.";
  const recent = (visitors.get(visitor) ?? []).filter((t) => now - t < PER_VISITOR.windowMs);
  if (recent.length >= PER_VISITOR.steps) return "That's a lot of questions in a few minutes. Try again shortly.";
  recent.push(now);
  visitors.set(visitor, recent);
  if (visitors.size > 5000) visitors.clear();
  today.steps += 1;
  return null;
}

export async function POST(request: Request): Promise<Response> {
  if (process.env.NEXT_PUBLIC_S1_DATA_MODE !== "fixture") return reply(404, "Not found.");
  const key = process.env.ANTHROPIC_API_KEY;
  if (!key) return reply(503, "The assistant is not connected yet.");

  const raw = await request.text();
  if (raw.length > ASSISTANT_MAX_BODY_BYTES) return reply(413, "That conversation is too long. Start a new one.");
  let body: { page?: unknown; messages?: unknown };
  try {
    body = JSON.parse(raw);
  } catch {
    return reply(400, "Bad request.");
  }
  const messages = sanitizeMessages(body.messages);
  if (!messages) return reply(400, "Bad request.");
  const page = typeof body.page === "string" && PAGE_LABEL[body.page] ? body.page : null;

  const visitor = request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() || "unknown";
  const limited = allow(visitor, Date.now());
  if (limited) return reply(429, limited);

  const upstream = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: { "content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01" },
    body: JSON.stringify({
      model: process.env.ASSISTANT_MODEL || ASSISTANT_MODEL,
      max_tokens: ASSISTANT_MAX_TOKENS,
      stream: true,
      // The instructions and tools are the same every step: cached, they cost a fraction.
      system: [{ type: "text", text: systemPrompt(page), cache_control: { type: "ephemeral" } }],
      tools: ASSISTANT_TOOLS.map((tool, i) =>
        i === ASSISTANT_TOOLS.length - 1 ? { ...tool, cache_control: { type: "ephemeral" } } : tool
      ),
      messages,
    }),
  }).catch(() => null);

  if (!upstream || !upstream.ok || !upstream.body) {
    const status = upstream?.status ?? 0;
    console.error(`assistant: upstream ${status}`);
    return reply(status === 429 || status === 529 ? 503 : 502, "The assistant could not answer just now. Try again in a moment.");
  }
  return new Response(translate(upstream.body), {
    headers: { "content-type": "application/x-ndjson; charset=utf-8", "cache-control": "no-store" },
  });
}

/** Anthropic's event stream -> one JSON object per line: text deltas, tool starts, then the whole message. */
function translate(source: ReadableStream<Uint8Array>): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  const decoder = new TextDecoder();
  const blocks: (Block & { partial?: string })[] = [];
  let stopReason: string | null = null;
  let buffer = "";

  return new ReadableStream<Uint8Array>({
    async start(controller) {
      const emit = (event: Record<string, unknown>) => controller.enqueue(encoder.encode(`${JSON.stringify(event)}\n`));
      const reader = source.getReader();
      try {
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          let cut: number;
          while ((cut = buffer.indexOf("\n\n")) >= 0) {
            const frame = buffer.slice(0, cut);
            buffer = buffer.slice(cut + 2);
            const data = frame.split("\n").find((line) => line.startsWith("data:"))?.slice(5).trim();
            if (!data) continue;
            const event = JSON.parse(data) as Record<string, unknown>;
            const index = event.index as number;
            if (event.type === "content_block_start") {
              const block = event.content_block as Record<string, unknown>;
              if (block.type === "tool_use") {
                blocks[index] = { type: "tool_use", id: String(block.id), name: String(block.name), input: {}, partial: "" };
                emit({ t: "tool", name: block.name });
              } else if (block.type === "text") {
                blocks[index] = { type: "text", text: "" };
              }
            } else if (event.type === "content_block_delta") {
              const delta = event.delta as Record<string, unknown>;
              const block = blocks[index];
              if (delta.type === "text_delta" && block?.type === "text") {
                block.text += String(delta.text);
                emit({ t: "text", d: delta.text });
              } else if (delta.type === "input_json_delta" && block?.type === "tool_use") {
                block.partial = (block.partial ?? "") + String(delta.partial_json);
              }
            } else if (event.type === "content_block_stop") {
              const block = blocks[index];
              if (block?.type === "tool_use") {
                try {
                  block.input = block.partial ? JSON.parse(block.partial) : {};
                } catch {
                  block.input = {};
                }
                delete block.partial;
              }
            } else if (event.type === "message_delta") {
              stopReason = ((event.delta as Record<string, unknown>)?.stop_reason as string) ?? stopReason;
            } else if (event.type === "error") {
              emit({ t: "error", message: "The assistant stopped part-way. Try again." });
            }
          }
        }
        emit({ t: "done", stop_reason: stopReason, content: blocks.filter(Boolean) });
      } catch {
        emit({ t: "error", message: "The answer was cut off. Try again." });
      } finally {
        controller.close();
      }
    },
  });
}
