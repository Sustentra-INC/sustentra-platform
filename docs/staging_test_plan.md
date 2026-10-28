# Staging test plan

A hand test of `https://staging.sustentra.com` before a release to production. It walks
one engagement from sign-in to the Excel workpaper. Run it after every cutover or release
candidate, and record the date, the build (`/api/health` → `version`) and the result in the
release issue.

- **Sample files:** the ones listed below. They are all in the repository, so every tester
  uses the same files.
- **Mark each step** pass, fail (with what you saw), or blocked.

## Sample files

Paths are from the repository root.

| Sample | File |
|---|---|
| Text PDF bill (natural gas) | `s1-test-suite/stationary_combustion/documents/SC-01_lakeshore_gas_single_meter_therms.pdf` |
| Second text PDF (fleet fuel card) | `s1-test-suite/mobile_combustion/documents/MF-01_northline_fleet_card_statement.pdf` |
| Word bill (natural gas) | `s1-test-suite/raw_documents/docx/EV-NG-2023-001.docx` |
| CSV log (diesel deliveries) | `parser_reliability_test_set/raw_documents/csv/CSV-DIESEL-001.csv` |
| Excel log (monthly natural gas use) | `parser_reliability_test_set/raw_documents/excel/XLSX-NG-001.xlsx` |
| Photo of a bill (electricity) | `backend/tests/services/data/textract_regression/electric_bill_photo.png` |
| PDF with no text layer (scan) | `s1-test-suite/stationary_combustion/documents/SC-08_scanned_bill_no_text_layer.pdf` |

The SC and MF PDFs can be rebuilt if they go missing:
`python scripts/generate_stationary_combustion_samples.py` (SC-01, SC-08) and
`python scripts/generate_mobile_combustion_samples.py` (MF-01).

Files that can't be read aren't kept in the repository. Make them from the repository root
before step 3 (macOS):

```bash
mkdir -p /tmp/qa
zip -j /tmp/qa/qa_archive.zip parser_reliability_test_set/raw_documents/csv/CSV-DIESEL-001.csv
cp s1-test-suite/raw_documents/docx/EV-NG-2023-001.docx /tmp/qa/old-bill.doc
cp parser_reliability_test_set/raw_documents/excel/XLSX-NG-001.xlsx /tmp/qa/legacy.xls
sips -s format gif backend/tests/services/data/textract_regression/electric_bill_photo.png --out /tmp/qa/bill-photo.gif
sips -s format heic backend/tests/services/data/textract_regression/electric_bill_photo.png --out /tmp/qa/bill-photo.heic
```

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

1. Upload the text PDF bill: it appears with a reading status, then values.
2. Upload several at once: the second text PDF, the Word bill, the CSV log, the Excel log,
   the photo of a bill and the PDF with no text layer.
3. Drop the five files from `/tmp/qa/` (`.zip`, `.gif`, `.heic`, `.doc`, `.xls`) on the
   upload dialog; the file picker only offers files that can be read. No crash. Each file is
   refused before upload and marked "Not uploaded", with a message that names it, for
   example "old-bill.doc can't be read here." Nothing new appears in Evidence (PR #160).
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
4. Request a value (Request, then Add to requests): it shows up in Requests, and its card
   says "Request not sent" until the request is sent. Once you send it (step 6), the card
   says "Requested" (PR #159). Add to requests has no Raised by field.
5. Reload: every decision is kept.

## 6. Coverage & requests

1. Missing data points show up as "Inputs missing", with a Request button.
2. Create a request, edit it, send it: it gets a request number and the state "Requested".
   Each row says who took its latest step and when, for example "Sent by <your name> · <time>".
3. Resolve one request; withdraw another with a reason.
4. Reload: states and numbers are kept.
5. Edit the text of a sent request from a second tab: you see "Request N was already sent, so
   its text can't change. Withdraw it and add a new request instead." and the row shows its real
   state.

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
