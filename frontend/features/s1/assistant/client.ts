import type { Block, Message } from "./sanitize";
import { ASSISTANT_MAX_STEPS } from "./spec";
import { runAssistantTool, type AssistantData } from "./tools";

/** The assistant could not be reached (not connected, rate-limited, or down). */
export class AssistantUnavailable extends Error {
  constructor(
    readonly status: number,
    message: string
  ) {
    super(message);
  }
}

interface StepHandlers {
  onText?: (delta: string) => void;
  onTool?: (name: string) => void;
}

/** One step: the route streams the answer (or the next tool calls) back, line by line. */
export async function assistantStep(
  page: string | undefined,
  messages: Message[],
  handlers: StepHandlers,
  signal?: AbortSignal
): Promise<{ content: Block[]; stopReason: string | null }> {
  const response = await fetch("/api/assistant", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ page, messages }),
    signal,
  });
  if (!response.ok || !response.body) {
    const message = await response
      .json()
      .then((body: { error?: string }) => body.error)
      .catch(() => null);
    throw new AssistantUnavailable(response.status, message ?? "The assistant could not answer just now.");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: { content: Block[]; stopReason: string | null } | null = null;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let cut: number;
    while ((cut = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, cut).trim();
      buffer = buffer.slice(cut + 1);
      if (!line) continue;
      const event = JSON.parse(line) as { t: string; d?: string; name?: string; content?: Block[]; stop_reason?: string | null; message?: string };
      if (event.t === "text" && event.d) handlers.onText?.(event.d);
      else if (event.t === "tool" && event.name) handlers.onTool?.(event.name);
      else if (event.t === "error") throw new AssistantUnavailable(502, event.message ?? "The answer was cut off.");
      else if (event.t === "done") result = { content: event.content ?? [], stopReason: event.stop_reason ?? null };
    }
  }
  if (!result) throw new AssistantUnavailable(502, "The answer was cut off. Try again.");
  return result;
}

/** Earlier questions' tool results are summarized away, so a long chat stays small. */
function compact(history: Message[]): Message[] {
  return history.map((message) =>
    typeof message.content === "string"
      ? message
      : {
          ...message,
          content: message.content.map((block) =>
            block.type === "tool_result" ? { ...block, content: "(earlier lookup, omitted)" } : block
          ),
        }
  );
}

/**
 * Ask one question: the model looks things up (the browser runs each tool over `data`),
 * then answers. Returns the conversation with this question and its answer appended.
 */
export async function askAssistant(
  question: string,
  history: Message[],
  data: AssistantData,
  page: string | undefined,
  handlers: StepHandlers & { onStepStart?: () => void },
  signal?: AbortSignal
): Promise<{ history: Message[]; answer: string }> {
  let messages: Message[] = [...compact(history).slice(-16), { role: "user", content: question }];
  while (messages[0] && (messages[0].role !== "user" || typeof messages[0].content !== "string")) messages = messages.slice(1);
  for (let step = 0; step < ASSISTANT_MAX_STEPS; step += 1) {
    handlers.onStepStart?.();
    const { content, stopReason } = await assistantStep(page, messages, handlers, signal);
    messages = [...messages, { role: "assistant", content: content.length ? content : [{ type: "text", text: "…" }] }];
    const calls = content.filter((b): b is Extract<Block, { type: "tool_use" }> => b.type === "tool_use");
    if (stopReason !== "tool_use" || calls.length === 0) {
      const answer = content
        .filter((b): b is Extract<Block, { type: "text" }> => b.type === "text")
        .map((b) => b.text)
        .join("\n\n")
        .trim();
      return { history: messages, answer };
    }
    messages = [
      ...messages,
      {
        role: "user",
        content: calls.map((call) => ({
          type: "tool_result" as const,
          tool_use_id: call.id,
          content: runAssistantTool(call.name, call.input, data),
        })),
      },
    ];
  }
  // Out of steps: ask for the answer with what it has.
  messages = [...messages, { role: "user", content: "Answer now with what you have found." }];
  const { content } = await assistantStep(page, messages, handlers, signal);
  messages = [...messages, { role: "assistant", content }];
  const answer = content
    .filter((b): b is Extract<Block, { type: "text" }> => b.type === "text")
    .map((b) => b.text)
    .join("\n\n");
  return { history: messages, answer };
}
