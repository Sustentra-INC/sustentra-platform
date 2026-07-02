"use client";

import { useState } from "react";

import { AssistantMessage } from "./AssistantMessage";

export function AssistantChat() {
  const [messages, setMessages] = useState<Array<{ role: "user" | "assistant"; content: string }>>([
    { role: "assistant", content: "Assistant shell ready for future backend integration." }
  ]);
  const [input, setInput] = useState("");

  const handleSend = () => {
    if (!input.trim()) {
      return;
    }

    setMessages((prev) => [
      ...prev,
      { role: "user", content: input },
      { role: "assistant", content: "Placeholder response." }
    ]);
    setInput("");
  };

  return (
    <section>
      <div style={{ marginBottom: 12 }}>
        {messages.map((message, index) => (
          <AssistantMessage key={`${message.role}-${index}`} role={message.role} content={message.content} />
        ))}
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="Ask a question"
          style={{ flex: 1, padding: 8 }}
        />
        <button onClick={handleSend} type="button">
          Send
        </button>
      </div>
    </section>
  );
}

