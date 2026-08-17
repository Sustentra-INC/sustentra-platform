# S2 Frontend Implementation Plan

Branch: `s2-ui`

This plan follows `S2_Handoff(08_13)/S2_Frontend_Build_Spec_v1.md`, the component inventory,
the supplied Meridian fixture, `FRONTEND_CONSTRAINTS.md`, and the v3.4 wireframe HTML in the
handoff folder.

## Wave 0 - Contract Reconciliation

Record these as active documentation issues before coding around them:

- Component count mismatch: the build spec says 14 new components, while the inventory gives 15
  contracts. Build all inventory contracts.
- `TechniqueSelector` mismatch: the build spec requires a named `TechniqueSelector`, but the
  inventory folds selection behavior into `ExaminationRecord`. Build `TechniqueSelector` as a
  named component used by `ExaminationRecord`.
- Container-state mismatch: the spec says eight states, while copy/starter/inventory/wireframe
  include `complete`. Treat S2 `ContainerState` as a 9-value contract.
- Fixture-count mismatch: README says 175 requirements, 8 findings, 3 requests, 8 documents;
  build spec says 187 requirements, 14 findings, 4 requests, 31 documents. Use supplied
  `starter/meridian.ts` as source of truth. Do not synthesize extra records just to satisfy the
  conflicting count.
- Wireframe filename mismatch: README names `Sustentra_S2_Wireframes_v3_4.html`, but the provided
  file is `Sustentra_S2_Wireframes_v1(08_13).html` and labels itself v3.4. Use that file as the
  normative wireframe unless replaced.
- Copy mismatch: the wireframe includes some text/classes that conflict with the spec's banned
  vocabulary. Use the wireframe for visual/layout intent, but obey explicit S2 copy restrictions
  and route all rendered state text through S2 copy constants.

## Wave 1 - Foundations

Create the S2 feature area under `frontend/features/s2/`:

- `types/`: supplied starter types as baseline, extended only where needed.
- `constants/` or `copy/`: `s2.ts` copy constants. No UI state string should live elsewhere.
- `fixtures/`: supplied Meridian fixture, plus fixture selectors/modes.
- `components/`: all named component contracts.
- `adapters/`: backend-to-S2 vocabulary normalization. No backend status prose reaches React.
- `persistence/`: one `persist(entity, payload)` boundary for write shapes.
- `utils/`: `resolveId(entity, id)`, `getInventory()`, `getLastSeen()`, `setLastSeen()`.
- `tests/`: unit/component/contract tests.

Foundation guardrails:

- Components do not parse identifiers.
- `Field_ID`, line IDs, document IDs, and finding IDs are opaque.
- Unknown enum values render loudly with raw value, blocking color, dashed border, and title.
- Rows are fixed at 44px and do not grow; overflow truncates with `title`.
- Numerals use tabular figures.
- Keyboard focus uses `:focus-visible`.
- Reuse/import S1 primitives where they satisfy the S2 contract. Wrap/extend rather than silently
  rebuilding shared primitives.
- Backend status vocabulary maps through an adapter before display.
- When persistence is not durable, render one S2 engagement-level dependency-blocked notice. Do
  not repeat persistence-blocked notices per row or per control.

## Wave 1 - Components

Build all inventory contracts plus the missing named `TechniqueSelector`:

- `StateChip`
- `InventoryLineRow`
- `RequirementRow`
- `CalculationStrip`
- `CoverageGrid`
- `ExaminationRecord`
- `TechniqueSelector`
- `PersonSlot`
- `ProgressBar`
- `FindingRow`
- `AskCard`
- `RequestRow`
- `DocumentRow`
- `ProcedureRow`
- `ChangeItem`
- `ContainerState`

Each component is incomplete until these are implemented and tested:

- declared prop contract
- unknown-value behavior
- hover behavior
- focus behavior
- keyboard behavior where specified
- ARIA announcement from the inventory

## Wave 1 - Container States

Support all 9 container-state values:

- `populated`
- `emptyNothingReported`
- `emptyNothingExamined`
- `emptyFiltered`
- `loading`
- `error`
- `degraded`
- `blocked`
- `complete`

Fixture modes should make each reachable:

- `meridian`
- `meridian-empty`
- `meridian-none-examined`
- `meridian-filtered-empty`
- `meridian-loading`
- `meridian-error`
- `meridian-degraded`
- `meridian-blocked`
- `meridian-complete`

## Wave 2 - Spine

Build:

1. Reported Inventory
2. Inventory Line
3. Examine

Examine modes:

- evidence held
- partially held
- no evidence

Critical invariant: a no-evidence requirement stays inline on `RequirementRow`; it does not
navigate to Examine.

## Wave 3 - Outbound Loop

Build:

- Request Builder
- request preview modal only
- Open Requests
- Findings
- inline Raise Finding panel

Write-shaped actions go through `persist(entity, payload)`. They should either work in memory or
state why persistence is unavailable through the one engagement-level dependency-blocked notice.
`AskCard` must reject client-facing wording containing a `Field_ID`/internal identifier.

## Wave 4 - Periphery

Build:

- Documents
- Since-you-were-last-here slide-over
- first-year Analytical Procedures
- Check Coverage

Slide-over requirements:

- 420px right slide-over over scrim
- auto-opens once per session
- re-openable from header counter
- four collapsible groups
- `localStorage` access only through `getLastSeen()` / `setLastSeen()`
- focus returns to the header counter on close

## Validation

Unit/component tests:

- copy centralized
- rendered UI copy obeys the banned vocabulary list
- backend DTO fields, fixture internals, comments, and translation adapters may contain backend
  source terminology only when it cannot leak into rendered copy
- unknown enums render loudly
- ID opacity
- fixed row geometry/truncation
- ARIA contracts
- finding dedupe key is `fieldId + type + summary`
- `TechniqueSelector` exists as a named component
- `ContainerState` supports all 9 values
- one dependency-blocked notice renders at engagement level when writes are in-memory/non-durable

Object lifecycle tests:

- examination re-record retains the prior entry
- note revision is versioned
- finding withdrawal never deletes the row and drops it from counts
- request withdrawal retains the record
- failed request send preserves the draft
- failed assignment rolls back optimistic state

Fixture Playwright:

- all 11 surfaces reachable
- all modes reachable
- all 31 actions either work or explain dependency
- exact Meridian checks from build spec section 13
- request builder preview contains no `Field_ID`
- change slide-over auto-opens once and then only from header counter

Live subset:

- Check Coverage renders all 89 live rules, including those emitting no finding
- two consecutive live runs do not duplicate platform finding rows
