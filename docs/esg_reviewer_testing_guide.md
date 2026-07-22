# ESG Reviewer Testing Guide (S1 Backend)

This guide is for ESG and audit teammates who want to test the current backend behavior in plain terms.

## What The Current S1 Backend Does

Today, the backend supports a practical evidence-review workflow:

1. A document is uploaded.
2. The system reads the document and proposes candidate values.
3. A human reviewer evaluates each candidate.
4. Reviewer decisions are saved.
5. Approved evidence is produced from those decisions.

## What This Is (And Is Not)

- This is not yet a compliance judgment tool.
- This is not yet calculation, reconciliation, or gap analysis.
- This is an evidence extraction and human review workflow.
- The machine proposes values.
- The reviewer decides whether those values are acceptable.
- Approved evidence is the reviewed output.

## What Reviewers Should Evaluate

When reviewing machine candidates, focus on whether the proposal is usable and explainable:

- Is the proposed value correct for this document?
- Is the unit correct?
- Is the date or service period captured correctly?
- Does the source snippet clearly support the proposed value?
- Would an auditor understand where the value came from?

## What Reviewers Should Not Expect Yet

- Final compliance conclusions.
- Finished reconciliation and gap reports.
- Full downstream calculation outputs.
- Production-grade policy interpretation.

The current focus is extraction quality and review quality.

## How To Interpret Machine Candidates

A machine candidate is a suggestion, not a final answer.

Each candidate usually includes:

- Field name and display label.
- Extracted value (raw and normalized).
- Unit (if present).
- Confidence score.
- Source reference/snippet.

Practical reading rule:

- High confidence can still be wrong.
- Low confidence can still be useful.
- Source traceability is required for reviewer trust.

## Reviewer Decisions

For each candidate, choose one of:

- `accepted`: value is correct as proposed.
- `edited`: value is mostly right but needs changes.
- `rejected`: value is wrong and should not be used.
- `needs_more_evidence`: document does not provide enough support.

Approved evidence is produced from accepted/edited latest decisions.

## Tester Checklist

Use this checklist during reviews:

- Are the target fields reasonable for this evidence type?
- Is the extracted value correct?
- Is the unit correct?
- Is the service period correct?
- Is the source snippet useful?
- Would an auditor understand where the value came from?
- Should the candidate be accepted, rejected, edited, or marked needs_more_evidence?
- Are important fields missing?
- Are labels confusing?
- Is this document the right evidence type?

## Feedback Template

Use this template when sending feedback to engineering:

```text
Document name:
Evidence type:
Field:
Observed value:
Expected value:
Issue type:
  missing field / wrong value / wrong unit / wrong period / bad source snippet / confusing label / wrong document type / other
Notes:
```

## How To Give Useful Feedback To Engineering

Helpful feedback usually includes:

- The exact field and candidate that looked wrong.
- What you expected instead.
- Why the source snippet was enough or not enough.
- Whether this appears as a one-off or repeated pattern.

Avoid private data in feedback whenever possible. Prefer synthetic or masked examples.
