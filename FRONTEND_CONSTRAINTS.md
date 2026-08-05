# Front-end constraints

**Read this before generating any UI for Sustentra.** It is short on purpose.

This file exists because Sustentra deliberately rejects several patterns that are
industry-standard everywhere else. A coding assistant reaching for a sensible
default will reach for exactly the ones we have ruled out. Everything below has a
reason attached — the reasons matter more than the rules, because a pattern you
have not seen before is still wrong if it breaks the same thing.

Owner: Claire Qiu. If a rule blocks something you need to build, raise it. Do not
work around it.

Synced to *Sustentra Front-End White Book* v1.4 (30 July 2026). Where this file and
the white book disagree, the white book is right and this file is stale — say so.

---

## What this product is

An ESG/GHG assurance practitioner brings a client's evidence package, and the
product carries them from that package to a defensible signed conclusion. The
user is a professional auditor under time pressure and professional-liability
exposure. Their output is an opinion they put their name on.

The interface is a **workpaper**, not a dashboard and not an AI tool. Every screen
either helps the reviewer reach a defensible conclusion or it is overhead.

---

## The seven hard rules

### 1. Confidence is a band, never a number

Render `auto-accepted` / `needs review` / `cannot determine`. Never surface a raw
score, percentage, or progress bar of model certainty. The underlying score is
retained in the audit trail.

Two independent reasons. A probability is uninterpretable to a reviewer and
becomes a liability in a signed engagement record. And our own extraction data
says the scores are not discriminative — wrong values have scored 0.85, identical
to correct ones.

Where you would have shown a low score, show **the reason** instead: which anchor
failed to match, which source was unavailable. A stated reason is defensible; a
number is not.

### 2. Five field states, not two

| State | Meaning | Action available |
|---|---|---|
| Populated | Value extracted or determined | Review, correct, judge |
| Missing — requestable | Empty, `Value_Origin = extracted` | Raise a client request |
| Missing — not requestable | Empty, `Value_Origin` is `computed` or `verifier_determined` | **None.** No document can ever supply this |
| System key | `Value_Origin = assigned` — an identifier the platform issues, not a value anyone reports | **None.** Never a gap, never requestable, never editable |
| Not applicable | Non-null `Condition` evaluating false | **None.** Not a gap |

`assigned` covers 42 rows (31 in Scope 1, 11 in Scope 2). They are structural keys.
Rendering them as populated data invites a reviewer to check them against a
document; rendering them as missing raises 42 phantom gaps. They need their own
treatment.

Rule `CX-01`: the request action must be suppressed on `computed` and
`verifier_determined` fields. **54** fields across the schemas (9 GEN, 31 S1, 14
S2) can never have a source document. If you offer a request on one, the tracker
loops `open → requested` forever because the document cannot exist. This is
documented as the single most likely production bug in the system.

Rule `CX-12`: a conditional row whose condition is false is **not applicable, not
missing**. Do not raise a gap, do not render it as empty.

### 3. Two numbers, always

Schema fields hold what the **company reported**. The system's recomputation is a
verification rule. The difference between them is the finding.

Any reconciliation view shows reported, re-derived, and the delta. Never one
number labelled as the answer — there is no correct choice of which one to show,
because they are different claims.

`Calculation_Role = computed_output` means the field sits at the output position
in a formula. It does **not** mean the system computed it; almost every such row
carries `Value_Origin = extracted`.

### 4. Magnitude carries its basis

Three values, and the distinction must survive everywhere magnitude appears —
register, queue, finding detail, misstatement summary:

- **measured** — plain
- **estimated** — followed by an `est.` marker
- **not quantifiable** — the literal words, in muted italic. Never a dash, never
  zero, never blank

These aggregate against one materiality threshold, so a reader has to see which is
which. A blank reads as zero and understates the engagement.

### 5. One indicator, one dimension

Status in this product is four separate axes:

| Dimension | Question | Attaches to |
|---|---|---|
| Processing state | What has the system done? | Evidence item / extraction |
| Review state | What has a human done? | Finding |
| Failure cause | What went wrong? | Finding |
| Impact | Magnitude / readiness / disposition | Finding |

Do not build a single status chip that blends them. `Blocked` is a processing
state, `Needs review` is a review state, `Material` is an impact — a label mixing
them is not a contract between UI and backend, it is a vocabulary list, and both
sides will drift.

If a row is too dense, that is a layout problem. Solve it as one.

### 6. Unverifiable is not failure

Some checks cannot be proven from any client document — global non-double-issuance
of RECs is the standard example. These are honest scope boundaries.

`--state-unverifiable` must never render in the same family as
`--state-blocking`. If it does, reviewers learn to dismiss red, and every real
finding loses its force.

Same treatment for anything the system does not evaluate at all: presentation
assertions, boundary completeness beyond the declared inventory, internal control
adequacy. These carry a persistent "not system-verified" label. Do not bury it in
settings.

### 7. Key on Field_ID

Components, deep links, gap references and test fixtures key on `Field_ID`. Never
on field name, label, or row position. Field_IDs are immutable and never reused
precisely so that things can point at them.

Format is `{BLOCK}-{NNN}` for the general layer and `{SCOPE}-{CAT}-{NNN}` for
scope schemas — `GEN-020`, `ORG-010`, `S1-STC-010`, `S2-EFS-050`. **The
identifiers in the 07/20 low-fi wireframes are placeholders and do not match the
schema.** Do not build against them.

---

## Vocabulary — these words are not interchangeable

| Term | Means |
|---|---|
| **Document typing** | Detecting what a file *is* — utility bill, contractual instrument, workbook |
| **Classification** | Reserved for *scope* classification: Scope 1/2/3, and within Scope 2, location- vs market-based |
| **Gap** | User-facing label for an open finding. Not a separate object |
| **Finding** | The object carrying review state, failure cause, impact, disposition |
| **Request** | Engagement-level client ask. Many-to-many with findings — one request bundles gaps across several review items |
| **Main evidence** | Extractable, system-verifiable, links to specific Field_IDs |
| **Supportive evidence** | Enters the workpaper, no extraction expected, links to a coarse review area |
| **Type review** | The classifier's confidence against the vocabulary threshold |
| **Fields extracted** | How many required fields were found inside a typed document |

The last two are different checks and were previously conflated. A file can be
confidently typed and still fail to yield every field — `auto-accepted` beside
`3 of 5` is not a contradiction.

---

## Subsystem 1 — what the evidence screens must get right

The current build target. Beyond the rules above:

- **Every file row carries facility and period.** Evidence is inherently facility
  × period, the coverage matrix depends on that resolution, and a reviewer must be
  able to scan for a missing month.
- **Type review and fields extracted are separate columns.** Never merged, never
  averaged into one health indicator.
- **Bulk operations are required, not optional.** Real engagements run to hundreds
  of documents across facilities and periods. Group by facility, period, or
  document type; multi-select; bulk accept. A flat list of 400 rows is unusable.
  Bulk accept writes one audit-trail entry per item, never one for the batch.
- **Duplicates, superseded versions and conflicting values need surfaces.** Two
  bills for the same facility and period; a resubmitted corrected workbook; a bill
  saying 40,000 kWh where the workbook says 42,000. The last is described in the
  system architecture as arguably the most important gap in the whole system.
- **Where a missing field goes is decided at the Completeness Gate, not here.**
  Show `3 of 5`. Do not preview whether the missing two become a retry, an
  evidence gap, or an extraction failure.
- **Extraction review pairs the value with its source.** Extracted field beside
  the highlighted location in the document. The source snippet is the reliable
  part of our extraction output — design the review around verifying it, not
  around trusting a score.

---

## States that must exist on every screen

Not optional, and not a later polish pass. In an assurance product the difference
between *checked and passed*, *checked and failed*, *could not check*, and *not
applicable* is the entire value proposition.

- Populated
- Empty — nothing yet (a fresh engagement is the most common state anyone sees)
- Empty — nothing applicable (renders differently from the above; they mean
  opposite things)
- Loading
- Error / degraded — the pipeline is down, OCR failed, a rule could not evaluate
- Provisional — result not final until the register is complete
- Dependency-blocked — designed, but the backend for it does not exist yet

---

## When you are unsure

Ask. Do not infer a convention from a neighbouring screen, and do not adopt a
pattern because it is common elsewhere — the patterns this product rejects are
common precisely because they are the defaults.

An invented convention becomes permanent within a week, and nobody remembers it
was invented.
