# Print And Greyscale QA

Subsystem 1 states must remain readable when printed or viewed in greyscale.
State meaning must come from text, structure, borders, and placement, not color
alone.

## Manual QA Checklist

- Evidence Workspace populated table prints with all state labels visible.
- Blocked row prints `Blocked` and its halt reason sentence.
- Unresolved facility prints `Unresolved` and `Assign facility`.
- Unresolved period prints `Unresolved` and `Assign period`.
- Type review band prints `open` and its reason sentence.
- `auto-accepted` prints as muted/plain text, not a state chip.
- Supportive evidence cards print as cards below the table.
- Completeness panel prints its dependency-blocked frame and dependency text.
- Fresh empty state prints `No evidence yet` and expected-document list.
- Filtered empty state prints `No documents match this filter`, total documents,
  and `Clear filter`.
- Extraction Review prints field labels, provisional identifiers, snippets, and
  `page location not available` when source location is absent.

## CSS Expectations

- Print mode removes decorative shadows.
- State indicators keep text labels and borders.
- Not-applicable indicators use dashed borders.
- Page background prints as white.
- Workpaper text remains black or greyscale.
