import type { ReactNode } from "react";

/** A small keyboard key chip: ⌘K, Esc, Enter, ↑. */
export function KeyHint({ children, className }: { children: ReactNode; className?: string }) {
  return <kbd className={`s1-key${className ? ` ${className}` : ""}`}>{children}</kbd>;
}
