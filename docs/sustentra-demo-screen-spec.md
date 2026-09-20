# Sustentra — Verification Workspace: Full Screen Specification

A complete, screen-by-screen description of the Sustentra S1 verification platform
(the NY Climate Week demo build). Written so it can be handed to a design tool
(Claude Designer, Figma AI, etc.) to reproduce or restyle the product faithfully.

Sustentra is a GHG (greenhouse-gas) **emissions verification** platform. The user is
a **verifier** (a third-party assurance professional, e.g. from "Meridian Assurance")
checking a **client's** reported emissions (the demo client is **Cascade Provisions
Co.**) against a regulation (e.g. California SB 253). The product is a **workpaper**:
a document read for hours, dense but calm, never flashy.

The app is a single-page flow of **8 screens** reached from a persistent left rail and
a top tab bar. It runs entirely on fixtures (no live backend) for the demo.

---

## 1. Global design system

### 1.1 Brand & tone
- **Product name:** Sustentra. Logo is a deep-indigo wordmark "SUSTENTRA" preceded by
  an interlocking-loops mark (three linked rounded shapes). Always on transparent /
  light ground.
- **Voice:** precise, plain, honest. No hype, no emoji, no em dashes. States are named
  for what they *mean* in an assurance engagement, never decorative.

### 1.2 Color tokens (light theme; warm paper + baby-blue accent)
| Token | Hex | Use |
| --- | --- | --- |
| `--sf-page` | `#FBFAF6` | app background (warm off-white) |
| `--sf-card` | `#FFFFFF` | cards, tables, panels |
| `--sf-sunken` | `#F7F5EF` | nested / recessed areas, group header rows |
| `--sf-inset` | `#EFEDE4` | code, quoted statute text |
| `--ink` | `#23231F` | primary text |
| `--ink-2` | `#57564F` | secondary text |
| `--ink-3` | `#8A897F` | labels, metadata, column headers |
| `--line` | `#E0DDD3` | default hairline |
| `--line-strong` | `#C9C5B8` | emphasized border |
| `--brand-ink` | `#282870` | Sustentra indigo — the logo only |
| `--accent-solid` | `#3D83C7` | baby-blue solid: primary buttons, submit |
| `--accent` | `#2C6FB3` | links, icons, active labels on paper |
| `--accent-strong` | `#24588F` | hover / pressed |
| `--accent-soft` | `#EAF3FC` | active tab / selected chip tint |
| `--accent-softer` | `#F4F8FD` | row hover tint |
| `--accent-line` | `#BFDBF4` | border on a tinted surface |

**Engagement-state colors** (semantic; each carries a text label too, never color alone):
| State | fg / bg / line | Meaning |
| --- | --- | --- |
| Blocking | `#A32D2D` / `#FBEAEA` / `#E8C4C4` | prevents conclusion (red) |
| Open | `#8A5108` / `#FAEFDC` / `#EBD5AC` | needs action, not blocking (amber) |
| Resolved | `#3B6D11` / `#EDF4E2` / `#CFE0B4` | done / verified (green) |
| Active | `#185FA5` / `#E8F1FB` / `#C3DAF2` | in progress (blue) |
| Unverifiable | `#4E5D6C` / `#EDF1F4` / `#D0D8DF` | checked, can't be verified from evidence (slate) — **not** a failure |
| Not applicable | `#8A897F` / transparent / `#D6D3C8` dashed | absence of obligation (muted, dashed, never a filled chip) |

### 1.3 Typography
- **UI / body:** IBM Plex Sans (self-hosted). Weights 400 / 500 / 600.
- **IDs, numbers, timestamps, coordinates:** IBM Plex Mono, tabular figures.
- Scale: screen title `1.5rem` (600, tight tracking), section `1.15–1.25rem`,
  body `0.95rem`, small `0.86rem`, label/column-head `0.76rem` uppercase with
  `0.04em` tracking. Line-height 1.5 (tight) / 1.7 (body).

### 1.4 Shape, spacing, motion
- Radius: cards `0.75rem`, inputs/chips `0.5rem`, pills `999px`.
- Spacing scale (rem): 0.25 / 0.6 / 0.95 / 1.4 / 2 / 3 / 4. Generous gutters; the app
  breathes — never edge-to-edge, never cramped.
- Borders are hairlines (`1px solid var(--line)`); shadows are barely-there
  (`0 0.06rem 0.18rem rgba(40,40,112,0.05)`). It is a document, not a neon app.
- **Motion:** one ease-out curve `cubic-bezier(0.23,1,0.32,1)`, ~160ms. Every clickable
  element presses in (`scale(0.96)` on `:active`) and lifts 1px on hover. Popover menus
  scale in from their trigger (`transform-origin: top right`, 150ms). All gated on
  `prefers-reduced-motion`.
- **Icons:** thin stroked line-icons (SVG, `currentColor`, ~1.7 stroke, rounded caps).
  Never emoji, never filled.

### 1.5 App chrome (present on every screen except the sign-in gate)
Two-column layout: **persistent left rail** + **main column** (top tab bar + screen).

**Left rail (`~240px`, sticky, warm sunken ground):**
1. Sustentra logo (top).
2. Stacked label/value rows, each a tiny uppercase `--ink-3` label over its value:
   Client · Engagement ID (mono) · Reporting period · Regulation · Assurance level ·
   Boundary approach · Scope boundary · Aggregate uncorrected magnitude.
3. **Glossary** (text link → opens glossary overlay).
4. **Reset workspace** (demo-only, bottom; confirms then clears the session to the start).

**Top tab bar (pill tabs, sticky, in a white rounded bar with a faint shadow):**
`Setup · Upload · Evidence · Requests · Check coverage · Verification results · Output`.
Inactive = muted text ghost pill; **active = baby-blue tinted pill** (`--accent-soft`
bg, `--accent-strong` text, thin accent ring). Hover = warm sunken bg. On mobile the
bar scrolls horizontally.

### 1.6 Sign-in gate (demo entry, shown before the app)
Centered card on the warm page:
- Sustentra logo.
- Heading **"Sign in"**, sub **"Verification workspace"**.
- Email field (pre-filled `m.osei@meridian-assurance.com`) and Password field
  (pre-filled, masked).
- **"Sign in"** button — full-width, baby-blue solid. One click enters the app
  (cosmetic only; validates nothing).
- Footer row: "Keep me signed in" · "Forgot password?" (inert link).
No demo markers or hedging copy — it presents as the real product sign-in.

### 1.7 Responsive / mobile (≤ 48rem)
Rail collapses to a compact horizontal summary strip at the top (logo + first few
facts). Tab bar scrolls sideways. Stat boxes, filter chips and form grids stack to one
column. Tables scroll **inside their own box** so the page itself never scrolls
sideways. Tap targets ≥ 2.75rem.

---

## 2. Screen 0 — Setup

**Purpose:** define what the engagement covers. Everything downstream (facility columns,
filters, request recipients) reads from here.

**Layout:** screen title **"Setup"** + one-line subtitle
("What this engagement covers. Facilities feed the Evidence Workspace; the client
contact and team feed Evidence Requests."), then a stack of bordered white cards.

**Cards & fields:**
- **Engagement** card — a 2-column grid:
  - *Company name* (text input, e.g. "Cascade Provisions Co.")
  - *Reporting period* (two native date inputs: start / end)
  - *Regulation* (dropdown; e.g. "California Senate Bill 253: Climate Corporate Data
    Accountability Act (California, USA)", or "New York Part 253 (New York, USA)")
  - *Methodology* (dropdown; e.g. "GHG Protocol Corporate Standard")
- **Facilities** card — subtitle "Entered manually…". A list of rows, each: facility
  **name** input + mono `facility-id` on the right + **Remove** link. Below: **"Add
  facility"** full-width button (adds an empty row).
- **Client contact** card — recipient for all Evidence Requests (name / email).
- **Engagement team** card — team members (name / login / role).
- **In-scope field list** (placeholder) — a table of methodology fields with a
  status chip "Field list pending · placeholder rows"; columns include requirement
  level and completeness status ("None" / "Pending" when absent).

**Buttons / actions:** Add facility (append row) · Remove (delete row) · each dropdown
and input writes straight to engagement config (and persists). No explicit "save".

---

## 3. Screen 1 — Upload

**Purpose:** bring the client's documents in. Each file becomes a row in the Evidence
Workspace as it "uploads".

**Layout:** title **"Upload evidence"** + subtitle ("Add the client's documents as they
were sent.").

**Regions (in order):**
1. **Prepared sample card** (demo hero trigger; only until the sample is added): a
   white card with a red "PDF" glyph, the filename `kent_electricity_feb_2025.pdf`,
   sub "From the client · ready to add", and a baby-blue **"Upload invoice"** button.
2. **Scripted analysis panel** (replaces the card while the beat plays): filename +
   stage headline that cycles **"Uploading…" → "Analyzing document…" → "Opening
   extraction review…"**, an animated progress bar, a "Recognized · Electricity bill"
   line, and a checklist that fills in ("Electricity consumed — 182,400 kWh", "Peak
   demand", "Billing period"). After ~3.5s it navigates to Extraction Review with the
   highlight pre-authored on the value.
3. **Drop zone** — a dashed band "Or drop your own files" + sub, with **"Choose files"**
   and **"Choose folder"** buttons (native file pickers; drag-and-drop supported).
4. **"This upload"** batch list — rows of `filename` + a processing chip
   (Uploading / Extracting / Extracted / Blocked), with a "View in Evidence Workspace"
   link.

---

## 4. Screen 2 — Evidence Workspace

**Purpose:** the operational table of every document held. Triage type/facility, see
processing state, raise requests, add notes.

**Header block:**
- `H1` client name (e.g. "Cascade Provisions Co."), a **"⚙ Edit setup"** gear pill
  (→ Setup), and muted "Since your last visit: N new".
- **Three stat boxes** (top-right), each a bordered tile with a big number + label,
  and each a toggle filter: **Needs you** (number in accent blue), **Arrived since
  last visit** (neutral), **Blocked** (number in red). Clicking one filters the table;
  the active tile fills with its tint.

**Facility filter strip:** a row of rounded chips, each `facility name` + a count
badge — one per facility, plus "Multiple facilities", "No facility", "Not yet known".
Click to filter; active chip fills baby-blue.

**Table** (rounded surface, uppercase column heads, accent row-hover), grouped by
document type with sunken group-header rows ("ELECTRICITY BILL (40)"). Columns:
1. **Document** — filename as a baby-blue link (→ Extraction Review) + mono
   "Uploaded · date" (or "Answered request N · date").
2. **Facility** — if resolved: name + "from accepted value"; if multiple/none: label;
   **if unresolved: an inline dropdown ("Choose facility")** shown directly, no click.
3. **Document type** — resolved type as text; **if unconfirmed: an inline dropdown
   ("Choose type")** with a small "not confirmed yet" caption. No click to reveal.
4. **Processing state** — a state chip (Extracting = blue, Extracted = green,
   Blocked = red) + a reason line under blocked rows.
5. **Issue** — issue text in red (e.g. "Scan is unreadable · no extractable text on
   any page.", "Period outside reporting year"), or muted **"None"**.
6. **Add to requests** — "Add to requests" link, or a state label
   ("Requested · request 1", "Resolved") linking to the Requests screen.
7. **Notes** — the latest note (text + mono author·date) and a **"+ Note"** ghost pill;
   when empty, just the "+ Note" pill. Clicking opens an inline input (Enter saves).
8. **Row menu** — a square "⋯" icon button opening an origin-aware popover: Open ·
   Set type · Set facility · Add note · Mark duplicate · Mark supersedes ·
   Answers a request · Withdraw · History.

**States:** withdrawn rows are muted with a "Withdrawn" indicator. Expanding History
shows a per-document record log.

---

## 5. Screen 3 — Extraction Review (the hero)

**Purpose:** confirm the machine's read of each value against the source document, with
the exact figure highlighted on the page.

**Layout:** a full-height **three-pane** panel (rounded, bordered):
- **Left — node tree** (`~16rem`): facilities → document types (e.g. "Kent Cannery →
  Electricity bill 7"). Selecting a node loads its values. Counts header shows
  "To review / Accepted / Corrected / Requested".
- **Middle — value cards** (flexible width): one card per extracted value. Each card:
  - The **value large** (e.g. **"182,400"**) + unit ("kWh"), tabular figures.
  - A **scope chip** ("Scope 2 · location-based" / "market-based") that stays on one line.
  - A record line: "System read · 182,400 kWh · from the invoice · time".
  - Three actions: **Accept** (confirms number/unit/field/facility/period; on the demo
    invoice, disabled with a tooltip if not yet reviewed), **Correct** (opens a
    correction form; disabled with a tooltip where not applicable), **Add to requests**
    (raises a client ask carrying the value + document name).
- **Right — source pane** (`~25rem`): page navigation ("page 1 of 1") and the **rendered
  document**. For the demo invoice this is an inline SVG of a realistic electricity bill
  ("Pacific Grid Electric", Cascade / Kent Cannery, Feb 2025) with a **yellow highlight
  box** drawn exactly over the figure ("182,400 kWh"). Selecting a value moves the
  highlight to that value's coordinates.

**Verifier judgment (Accept/Correct/requests) persists across navigation.**

---

## 6. Screen 4 — Evidence Requests

**Purpose:** every open ask to the client, assembled into one email and resolved by
hand. Nothing sends itself; nothing resolves itself.

**Header:** client name + "Setup" link + "Since your last visit: N resolved · N raised",
then three count filters (**Not yet sent**, **Requested**, **Resolved**) and a
**"Request by email (N)"** button (enabled once selectable asks are checked).

**Body:** two columns —
- **Left — type filter chips** (vertical): Missing document · Replace document ·
  Missing data · Clarify · Confirm or restate, each with a count. Toggle to filter.
- **Right — main:** a toolbar (Facility dropdown · State dropdown · Search box · Clear
  filter) over the table.

**Table** (8 columns): checkbox (select sendable) · **Item** (label + "follow-up"
tag) · **Type** · **Facility · period** · **What is needed** (inline-editable input on
not-yet-sent rows) · **Raised from** (link "value" / "document · p.N" → opens source) ·
**Raised by** (name + mono date) · **State** (label + inline actions: Resolve /
Withdraw / Raise follow-up / Record). Rows are tinted by state (not-yet-sent = light
red, requested = amber, resolved / withdrawn = struck-through muted). Row tints never
carry meaning without the state label present.

**Sub-rows:** Resolve opens an inline box (optional link + note); Withdraw opens a box
(required reason); Record expands the ask's history log.

**Request-by-email panel** (right-side drawer): "Nothing is sent from here." Fields:
To (read-only client email) · Subject · Opening (textarea) · Closing (textarea) · a
live **preview** of the assembled message (grouped by facility, documents before
questions, no internal IDs). Actions: **Copy message** · **Open in mail** (mailto) ·
**Mark as sent** (baby-blue; marks the asks as requested under a new request number) ·
Cancel. A toast confirms.

Below the table, a muted **"Deferred (per the spec) — not built"** list names
out-of-scope items (due dates, chase, client login, real sending, the needed-items grid).

---

## 7. Screen 5 — Check Coverage

**Purpose:** honestly state what the system *can* and *cannot* check with the evidence
held. The rule engine does not evaluate assertions yet, so this shows **input
readiness only** — never that a rule "ran".

**Header:** a **shield line-icon** (accent) + `H1` "Check coverage" + subtitle.

**Summary strip:** four **status tiles**, each a bordered tile = a toned icon chip +
big count + label:
- **Inputs missing** — amber alert-circle icon.
- **Not applicable** — grey minus-circle icon.
- **Out of scope** — slate ban / slash-circle icon.
- **Inputs present** — green check-circle icon.

**Banner:** an info-icon note — "Rule evaluation is not yet implemented. This shows
*input readiness* only: whether a rule's data points have accepted values, not whether
the rule's assertion held. A rule with inputs present has not been run."

**Table**, grouped by status (group header row carries the status line-icon + count).
Columns: **Rule** (mono id, e.g. `COV-GAS-COMPLETE`) · **What it checks** (assertion
sentence) · **Data points it applies to** (list) · **Status** (state chip **with its
line-icon**) · **Reason** (plain explanation). Columns are proportional; fits with no
sideways scroll.

---

## 8. Screen 6 — Verification Results

**Purpose:** every data point — what was reported, what recompute found, and the
verifier's position on each. Recompute is partial and rule evaluation isn't
implemented, so outcomes are honest about that.

**Header:** `H1` "Verification results" + subtitle, then two count tiles
(**Results**, **Findings**).

**Banner:** "Recompute is partial and rule evaluation is not implemented. Only Scope 1
stationary combustion is recomputed today; other rows say why they were not. Check
outcomes reflect that: most read 'could not check'. Examination state and next action
are yours to set."

**Table**, grouped by section. Columns: **Data point** · **Reported** (client's value) ·
**Recomputed / Expected** (value, or "not recomputed · reason") · **Delta** (mono, or
"None") · **Check outcome** — a state chip: **Held** (green, within tolerance),
**Exception** (red, exceeds tolerance), **Could not check** (**slate**, no recompute /
rule path), **Out of scope** (muted) · **Examination state** (a small select the
verifier sets: Not examined / …) · **Next action** (a "Register finding" link that opens
a finding form: sentence + cause + magnitude, default "n/a").

**Findings section:** any registered findings, each with a state chip and details.

---

## 9. Screen 7 — Output

**Purpose:** the assurance deliverable (report / register export). Currently a stub.

**Layout:** a single wide card explaining what Output will assemble (the verification
statement, the corrections register, the evidence index) and that it is not built yet.
No destructive actions.

---

## 10. The demo hero path (scripted, offline)

1. **Sign-in gate** → one click (pre-filled) enters the app on **Setup**.
2. **Setup** shows Cascade Provisions Co., three facilities (Tualatin Plant, Kent
   Cannery, Modesto Bottling), CA SB 253, GHG Protocol.
3. **Upload** → click **"Upload invoice"** on the prepared card.
4. A scripted beat plays: **"Analyzing document…"** with a progress bar and values
   ticking in (no vendor named).
5. Auto-navigates to **Extraction Review** with the **Pacific Grid Electric invoice**
   rendered and the **yellow highlight on "182,400 kWh"**.
6. (Optional continuation) **Requests** → assemble the client email; **Verification
   results** → the outcomes table.
7. **Reset workspace** (rail) returns everything to the start for the next run.

Everything works offline after first load and survives reload (state persists locally;
a fresh visitor gets clean fixtures).

---

## 11. Design guardrails (do / don't)

- **Do** keep the warm-paper ground and the single baby-blue accent; keep engagement-state
  colors semantic and always paired with a text label.
- **Do** keep it calm and document-like: hairlines, minimal shadow, generous spacing,
  tabular numbers, mono for IDs.
- **Do** use thin stroked line-icons (enterprise style; Lucide / Phosphor are good free
  matches for the "Oracle / Okta" look).
- **Don't** use em dashes, emoji, gradients, heavy shadows, or more than one accent hue.
- **Don't** let color carry meaning alone; don't turn "Not applicable" into a filled chip;
  don't render "Unverifiable" in a red family (it is not a failure).
