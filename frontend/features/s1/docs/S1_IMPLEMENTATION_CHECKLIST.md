# S1 Implementation Checklist

Use this checklist before opening S1 frontend work for review. The source of
truth is the S1 build spec plus the wireframe handoff; this file turns the most
failure-prone rules into implementation checks.

## Forbidden UX Patterns

Do not introduce:

- Confidence percentages
- Progress bars
- Completion indicators
- Green verification states
- `verified`
- `complete`
- `all clear`
- Warning terminology
- Any materiality, tCO2e, finding, disposition, or conclusion language

## State Rules

- Facility is never blank.
- Period is never blank.
- Missing values render as `not found`.
- Missing source location renders as `page location not available`.
- Blocked items always render a reason sentence.
- `auto-accepted` document type renders as muted text, not a chip.
- Fields found/expected renders as plain `n of m`; never color, threshold, or sort it as a problem bucket.
- Superseded documents stay visible.
- Unsupported backend capabilities render their intended absence instead of hiding the surface.

## Data Rules

- React components consume S1 view models, not raw backend DTOs.
- Raw `field_id` appears only inside the field resolver module.
- Components consume opaque `fieldKey`.
- Backend status fields are mapped in adapters before rendering.
- Audit actions are event-based.
- No persistence is enabled before the audit decision is confirmed.
- Fixture mode and backend mode are selected through one S1 data-mode accessor.
- Backend mode does not silently fall back to fixtures.
- Original uploaded documents remain viewable after refresh in backend mode.
- Backend gaps render degraded/dependency-blocked states instead of disappearing.

## Evidence Workspace Checks

- Desktop minimum is 1280px; no mobile collapse is required.
- Nav shows Evidence active and Register, Requests, Conclusion disabled with next-release markers.
- Needs-you counts are engagement-wide and do not change under filters.
- Active filter state states that the table is filtered while counts remain engagement-wide.
- Header select-all applies to the filtered set and says so.
- Selection clears when filters, grouping, or container state changes.
- Upload asks only for files.
- Facility assignment is inline and closed-list from engagement config.
- Period assignment is inline.
- Type accept/change UI exists, but save remains disabled or intent-only until audit persistence is confirmed.
- Completeness panel renders as dependency-blocked until in-scope field data exists.

## Extraction Review Checks

- Queue excludes computed, verifier-determined, and assigned fields before rendering.
- Default selected field is the first unreviewed field.
- Source pane follows selected field.
- Source pane never guesses page 1 when location is missing.
- Snippet text has enough room to be the verification surface.
- Manual entry is available anywhere a field value is empty.
- Correct value creates two audit intents: machine value and human correction.
- Human-keyed values are permanently distinguishable.

## Accessibility Checks

- `Tab` reaches every action.
- Tooltips open on hover and keyboard focus.
- Focus rings are visible.
- Up/down arrows move the selected row or field.
- `Enter` opens the selected primary action.
- `Space` toggles row checkboxes.
- `Esc` cancels inline edits.
- Loading uses skeleton rows at real row height, never a spinner over blank space.

## Definition-Of-Done Tests

- Blocked row without a reason fails.
- Unresolved facility and period never render blank.
- Filtered empty state differs from fresh empty state.
- Forbidden vocabulary does not appear in S1 UI copy.
- `field_id` usage is isolated to the resolver.
- Bulk action creates N audit intents.
- Correction creates two audit intents.
- Selection clears after filter/group/container-state changes.
- Missing source location renders `page location not available`.
- Backend mode smoke test: create project, refresh, project remains.
- Backend mode smoke test: upload document, refresh, document remains and opens.
- Backend mode smoke test: process document, refresh, extraction fields remain.
- Backend mode smoke test: correct value, refresh, correction remains.
