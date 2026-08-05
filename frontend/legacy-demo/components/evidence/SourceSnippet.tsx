interface SourceSnippetProps {
  snippet: string;
  location: string;
}

export function SourceSnippet({ snippet, location }: SourceSnippetProps) {
  return (
    <aside style={{ borderLeft: "4px solid #4d6", paddingLeft: 12 }}>
      <p style={{ marginBottom: 6 }}><strong>Source</strong>: {location}</p>
      <p style={{ margin: 0 }}>{snippet}</p>
    </aside>
  );
}

