interface AssistantMessageProps {
  role: "user" | "assistant";
  content: string;
}

export function AssistantMessage({ role, content }: AssistantMessageProps) {
  return (
    <div style={{ marginBottom: 8 }}>
      <strong>{role === "user" ? "You" : "Assistant"}:</strong> {content}
    </div>
  );
}

