interface PageHeaderProps {
  title: string;
  subtitle?: string;
}

export function PageHeader({ title, subtitle }: PageHeaderProps) {
  return (
    <header style={{ marginBottom: 16 }}>
      <h1 style={{ marginBottom: 4 }}>{title}</h1>
      {subtitle ? <p style={{ margin: 0, color: "#444" }}>{subtitle}</p> : null}
    </header>
  );
}

