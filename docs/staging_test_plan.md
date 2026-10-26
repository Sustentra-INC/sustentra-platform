# Staging test plan

A hand test of `https://staging.sustentra.com` before a release to production. It walks
one engagement from sign-in to the Excel workpaper. Run it after every cutover or release
candidate, and record the date, the build (`/api/health` → `version`) and the result in the
release issue.

- **Sample files:** use the ones in `frontend/public/__demo_upload__/` (electricity, steam,
  fleet fuel card, refrigerant log, diesel CSV, Word bill) and
  `local-samples/claire-workbook-demo/`.
- **Mark each step** pass, fail (with what you saw), or blocked.

## 0. Before you start

1. `https://staging.sustentra.com/api/health` shows `"status":"ok"` and the commit you expect.
2. On the staging host, `grep S1_STORE /opt/sustentra/.env` shows `postgres+jsonl`, after
   the cutover (`docs/s1_store_cutover.md`).

## 1. Sign in and session

1. Open `/org/<slug>`. You are sent to that organization's sign-in page.
2. Wrong password → a generic error that doesn't say whether the email exists.
3. Right password → the code step. A wrong code is refused; the right code signs you in.
4. Browser Back after signing in doesn't return to the code step.
5. Reload any page: you stay signed in. Sign out: protected pages send you back to sign-in.

## 2. Setup

1. Create an engagement: client, reporting period, regulation, methodology, data scope,
   assurance level, materiality.
2. Add three facilities with addresses (the ZIP code picks the eGRID subregion).
3. Reload: everything you entered is still there.

## 3. Upload

1. Upload one PDF bill: it appears with a reading status, then values.
2. Upload several at once: a PDF, a Word file, a CSV and a scan or photo.
3. Upload a file that isn't a document (for example a `.zip`): a clear refusal, no crash.
4. Upload the same file twice: it is flagged as a duplicate.

## 4. Evidence

1. Each document sits under its facility and type, with the right count.
2. Change a document's type or facility: it is read again, and the change sticks after a reload.
3. Add a note and reload: the note is kept.
4. Open a document: the preview loads. Download: the file is identical to the one uploaded.

## 5. Extraction review

1. Each value shows its source, and the figure is highlighted on the document.
2. Accept a value: its state changes and the counts update.
3. Correct a value with a reason: the new value is used and the old one is kept.
4. Request a value: it shows up in Requests.
5. Reload: every decision is kept.

## 6. Coverage & requests

1. Missing data points show up as "Inputs missing", with a Request button.
2. Create a request, edit it, send it: it gets a request number and the state "Requested".
3. Resolve one request; withdraw another with a reason.
4. Reload: states and numbers are kept.

## 7. Verification results

1. Scope 1 and Scope 2 totals appear, recalculated from the accepted values.
2. Enter a reported value: the difference and "% of materiality" update.
3. Open a line: the calculation steps and the factors with their sources are shown.

## 8. Output

1. Export the Excel workpaper. It opens. The roll-up shows mass per gas and CO₂e per
   category, with a "Counted as 0" column. The totals match Verification results.

## 9. Access between organizations

1. A second organization's user can't see this engagement: its URL answers "not found".
2. A provider admin can read it but can't upload or review.

## 10. After a redeploy

1. Redeploy the same build, or wait for the next one. Everything from steps 2–8 is still there.
