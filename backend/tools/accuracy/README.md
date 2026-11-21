# Accuracy harness

Scores the real extraction pipeline against the answer keys, per field family.

    python -m backend.tools.accuracy                  # STG, NPL, LHF found in ~/Downloads; rule readers only
    python -m backend.tools.accuracy --set NAME DOCS_DIR KEY_CSV --out DIR
    python -m backend.tools.accuracy --ai-record DIR  # real Claude (needs credentials); replies saved in DIR
    python -m backend.tools.accuracy --ai-replay DIR  # recorded replies, no network; a missing reply fails the run
    python -m backend.tools.accuracy --write-baseline backend/tests/data/accuracy-baseline.json

**Data rules.** Documents, keys, reports and recorded replies stay outside the repository (the tool refuses
paths inside it). The only thing it writes into the repo is the baseline: aggregate counts per field family,
no values, file names or company names.

## Outcomes

| outcome | meaning |
|---|---|
| match | the extractor gave the key's value (`exact` = no tolerance needed) |
| wrong | the extractor gave a different value; **silent** if it carried no warning flag and confidence >= 0.50 |
| missed | the extractor has the field but gave no value, or never made that record |
| not_targeted | the extractor has no field for it yet (meter reads, demand, amounts, converted quantities...) |
| unscored | not a reading: notes, platform actions, reporting/recalculation rows, non-evidence documents, unmapped labels, ambiguous records, files not in the folder |

A value the key does not cover is **unscored, never wrong** (counted under `extracted_values_with_no_key_cell`).
Precision = match / (match + wrong); recall = match / (match + wrong + missed).

Comparison: numbers as printed must be equal (commas, currency and unit text ignored); a value that went
through a unit conversion, and every total, may differ by 0.1% relative. Dates must be the same day. Ids ignore
case, spacing and punctuation; names also ignore accents. Informational flags (`unit_converted`, ...) do not
count as a warning (see `model.INFORMATIONAL_FLAGS`).

## Mapping table

`mapping.py` is the table (key field name -> family -> extractor field). Selectors in labels
(`[Apr 2031] ...`, `January ...`, `run 03/05/2031 ...`, `[VEH-9 Jan-31] ...`) and the key's `page_or_row` column
("row 3", "p1 row 2") pick the record of a multi-record document; where the key gives a record's service period,
that period finds the record. Families: supplier, account, meter, statement_date, period_start, period_end,
activity_quantity, activity_unit (scored with the quantity), activity_total (sums), distance, fuel_type,
vehicle_type, model_year, refrigerant_type, refrigerant_recovered, technician, equipment_id, equipment_capacity,
service_address, facility (placement), document_recognition, non_evidence_rejected.

Known artefact: a fleet-card statement has transaction dates and no service period, so the key's statement
period is `not_targeted` for it and a transaction date is never compared to a period start.

Placement: the facility is scored from the name the extractor read. A name that is not the key's facility is
wrong only when no address was read; with an address it is unscored (needs the engagement's facility book).

## Not in v1

Reporting-set scoring (recalculated emissions, LHF reported totals), reporting-year placement of 2024 rows and
duplicates, and the CI gate (PR 2). `--ai-record` has not been run against live Claude in this PR; the record/
replay wrapper is covered by unit tests with a fake client.
