# Sustentra design standard

**Updated Nov 25, 2026: UI redesign approved (Debo, Vivian). Font, type scale, colour and parts updated.**

One page of rules for every screen of the workpaper, written by hand or by an AI tool.
It comes from the design reviews with Vivian and Claire (October 2026). When a rule and a
screen disagree, the screen changes. When a rule is wrong, change it here first.

The tokens live in `frontend/features/s1/styles/sustentra-tokens.css`. The contract test
(`frontend/features/s1/tests/frontendContract.test.ts`) fails a build that breaks the type,
colour or spacing rules.

## 1. Every screen answers three questions

1. **Where am I?** The page title, and one line of context under it if needed.
2. **What needs my attention?** A summary at the top: counts and states, worst first.
3. **What do I do next?** One primary action per work area.

The screen must make sense with no tip, tour or tooltip open.

## 2. Type: one family, eight sizes, four weights

| Token | Size | Use |
|---|---|---|
| `--text-xs` | 11px | Group labels, badges |
| `--text-sm` | 12px | Labels, column headers, metadata, chips, timestamps, helper text, and the text inside form fields (inputs, selects, text areas) |
| `--text-base` | 13px | Secondary body text |
| `--text-md` | 14px | Body, table cells, buttons, values |
| `--text-title` | 16px | Card titles |
| `--text-lg` | 20px | Section titles, key figures |
| `--text-xl` | 26px | Page titles |
| `--text-display` | 30px | Key figures, big numbers on the page |

- **One family**: `--font-sans`, which resolves to **Inter** (loaded via `next/font/google`
  in `app/layout.tsx` and exposed as `--font-inter`). The full stack is
  `-apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", Inter, "Helvetica Neue", Arial, sans-serif`.
  No monospace in the interface. Digits that line up use tabular figures (`.s1-num`), in the
  same font.
- **Four weights**: `--weight-regular` (400) for content, `--weight-medium` (500) for nav,
  pills and buttons, `--weight-strong` (600) for titles, labels and emphasis,
  `--weight-bold` (700) for page titles and big numbers.
- **Hierarchy comes from placement, grouping, contrast (`--ink`, `--ink-2`, `--ink-3`) and
  weight, before size or colour.** A section title is `--text-md` in the strong weight, not
  an extra size: it matches the text in its fields in size and outranks it in weight.
- **The text in a field is smaller than the section title above it**: fields use `--text-sm`,
  so a form reads title, then label, then value. The contract test checks every input, select
  and text area rule.
- Uppercase only for column headers and small group labels, with 0.06em tracking and
  `--text-sm`.
- Exception: the demo's client documents (bills, letters, photos) look like the real thing.

## 3. Spacing

Use the spacing tokens only: `--sp-1` to `--sp-6` (about 4, 8, 12, 18, 26 and 40px as
rendered).

- **Spacing levels:**
  - inside a component: `--sp-2` or `--sp-3`;
  - between components: `--sp-4`;
  - between sections: `--sp-5`.
- Lay out siblings with `gap`, not margins.
- Table rows centre their content vertically.
- Numbers are right-aligned.

## 4. Colour means something

- **Text** uses the ink ramp: `--ink` (primary), `--ink-2` (secondary), `--ink-3` (labels).
- **Indigo** (`--brand-ink`, `#3A40C0`) is both brand and action. The nav, logo, primary
  buttons, links, focus rings and selected states all use it. Active and selected states are
  always indigo — never black.
- **Surfaces** are cool grey: `--sf-page` (#F3F4F8) for the app background, `--sf-card`
  (#FFFFFF) for cards and panels, `--sf-sunken` and `--sf-inset` for nested areas.
- **State colours** are only for state:

  | State | Colour |
  |---|---|
  | Blocking | red |
  | To review, open | amber |
  | Done, accepted | green |
  | Requested, in progress | indigo |
  | Cannot verify | slate |

  Never use them for decoration.
- **Not by colour alone:** colour is never the only signal. A state also has a word or an icon.

## 5. Reuse the parts

| Part | Rule |
|---|---|
| **Primary button** (`.s1-button--pri`) | Solid indigo (`--accent-solid`). One per work area. `--shadow-primary` on hover. |
| **Secondary button** (`.s1-button`) | Outline, quieter. |
| **Text button** | For Revert, Cancel, low-stakes links. |
| **Row menu** (`ActionMenu`, "⋯") | Everything else a row can do, including destructive actions (Withdraw). |
| **State chip** | Fully round pill (`--r-pill`), 6px coloured dot (`--dot-*`), soft tint background, matching dark text at `--text-sm` / `--weight-medium`. Short labels. Example: *● Requested*. |
| **Icons** | Solid two-tone: filled shape (`fill="currentColor"`) with second tone at `fill-opacity=".38"`. Default 18px. No outline icons inside tinted squares. |
| **Table** | Small uppercase headers in `--ink-3`, body-size cells. |
| **Panel** | `--shadow-card`, `--r-card` (14px) radius. A header with a title and, at most, a count or a red flag count. Groups fold from their header. |
| **InfoTip** (ⓘ) | For explanations. No paragraphs on the page. |
| **Change line** | A reversible change shows one line: *Adjusted by M. Osei · Oct 21, 3:57 PM · Revert*. |

Do not restyle a part for one screen. If it does not fit, change the part.

## 6. Show what the task needs, reveal the rest

Progressive disclosure: the current task's information is visible. History, records,
settings and long explanations open on request. Examples:
- in Extraction review, only the selected card opens to its record and actions;
- History lives in the row menu;
- explanations live behind the ⓘ.

## 7. Say who did it

Three sources of work, always labelled the same way, with words and an icon:

| Source | Label | Example |
|---|---|---|
| AI extraction | **Read by AI** | A value read from a bill |
| Automated check | **Checked by system** | A coverage check, a recalculation |
| Human review | **Accepted by M. Osei** (or Corrected, Requested, Adjusted) · time | The verifier's decision |

An AI reading is never shown as reviewed until a person accepts it.

## 8. Guidance: one pointer at a time

A small pulsing dot may point at an unfamiliar action, for example opening the source
evidence behind a figure.

- It is contextual: it appears beside the action, only where the action is.
- Only one dot shows at a time.
- It pulses three times, then rests.
- It is dismissible (×), and doing the action dismisses it too.
- Once dismissed, it never comes back for that user.
- Under reduced motion, it does not animate.

## 9. Words

- **Buttons** say what happens: *Accept*, *Send 3 requests*, *Resolve*.
- **Sentence case**, and the auditor's own terms: *data point*, *evidence*, *materiality*.
- **Errors** say what went wrong and what to do.

## 10. For AI-generated screens

Prompts for Emergent, Claude or any other tool include this file. A generated screen:
- uses the tokens and parts above, not new ones;
- passes `npm run lint`, `npm run typecheck` and the contract test before review.

## Where we are (25 November 2026)

- **Enforced by the contract test:**
  - type: one family (Inter / system stack), eight sizes, four weights, no monospace;
  - tokens only, no raw hex or px in component stylesheets;
  - stylesheets that parse.
- **In place:**
  - redesign tokens, font and design standard (MVP-262);
  - the shared row menu (Evidence, Coverage & requests);
  - state chips;
  - change lines with Revert (Methodology review);
  - progressive disclosure in Extraction review.
- **To build:**
  - component restyling against new tokens (next tickets);
  - the AI / system / human labels (section 7);
  - the guidance dot (section 8).
- **To update in their own tickets:** chart palette (`--chart-*`), document highlights
  (`--hl-*`), status marks (`--mark-*`).
