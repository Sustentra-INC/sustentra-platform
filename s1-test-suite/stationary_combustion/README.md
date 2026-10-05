# EXT-001 golden set: Scope 1 stationary combustion (CT-S1-FUELQTY)

Synthetic fuel bills and delivery documents with hand-checked expected values. All
suppliers, customers, addresses and account numbers are fictional.

| ID | Document | What it exercises |
|---|---|---|
| SC-01 | Natural gas bill, one meter | Labels and values in separate columns; usage in therms, converted to MMBtu; the CCF "difference" column must be ignored |
| SC-02 | Natural gas bill, two meters | One record per meter with its own read dates; usage in CCF; total row ignored; classifier tie with an electricity variant resolved by the content check |
| SC-03 | Corrected gas invoice, one meter, two periods | One record per service period; energy (Dth) column picked over volume (Mcf); "Bill To" value on the next line |
| SC-04 | Heating oil delivery ticket | Gallons; delivery date as period start and end |
| SC-05 | Propane invoice (Canada) | Litres; ISO dates; the non-fuel line item (tank rental, `EA`) is skipped |
| SC-06 | Monthly bulk diesel statement (standby generators) | Three deliveries become three records; the total row is not a record; site line split into name and address |
| SC-07 | Industrial gas bill, label: value lines only | Mcf; separate period start/end labels; the daily average is not the quantity |
| SC-08 | Scanned bill, no text layer | Halts: `unreadable_document` |
| SC-09 | Water bill shaped like a gas bill | Halts: `unsupported_document` (no combusted fuel) |

- `documents/` - the PDFs (committed; regenerate with `python scripts/generate_stationary_combustion_samples.py`).
- `expected/<ID>.expected.json` - expected classification, halt, document fields and one entry per record.
  `activity_quantity` / `activity_unit` are the normalized values (energy in MMBtu; volumes, liquids and
  masses keep their unit); `raw_quantity` / `raw_unit` are what the document says.

Run the gate and print the per-document accuracy report:

```bash
pytest backend/tests/golden_s1/test_stationary_combustion_golden.py
python -m backend.tests.golden_s1.stationary_combustion_golden
```

Add real (redacted) bills here as they arrive: drop the PDF in `documents/`, write its
`expected/*.expected.json`, and the tests pick it up automatically.
