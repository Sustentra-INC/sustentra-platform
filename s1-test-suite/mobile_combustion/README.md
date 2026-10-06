# EXT-002 golden set: Scope 1 mobile combustion (CT-S1-MOBFUEL)

Synthetic fuel-card statements, pump receipts and fleet fuel invoices with hand-checked
expected values. All merchants, fleets, drivers, plates and card numbers are fictional.

One record per fuel **transaction** (Scope 1 schema `fuel_transaction`, S1-MOB-110/410).

| ID | Document | What it exercises |
|---|---|---|
| MF-01 | Fleet fuel-card statement | 4 transaction records; DEF and car-wash lines skipped; odometer column ignored; masked card per line; B20 is diesel with a 20% blend |
| MF-02 | Pump receipt (narrow page) | "12.457 GAL @ $3.459/GAL"; fleet-card prompts give vehicle and card |
| MF-03 | Canadian diesel receipt | Litres, ISO date; "Unit: T-118" is the vehicle, not a unit of measure |
| MF-04 | CNG fleet invoice | GGE kept as GGE; price column ignored; **no CNG fleet variant in the vocabulary**, so it halts until a reviewer sets the type |
| MF-05 | Forklift propane cylinders | Quantity by weight (lb), not cylinder count; classifier leans stationary but "forklift" contradicts it, so it halts for a reviewer |
| MF-06 | UK fuel-card statement, 2 pages | Litres; day-first dates; table continues under a repeated header on page 2; AdBlue skipped; stationary/mobile tie broken by "fuel card"/"vehicle" |
| MF-07 | Biofuel blends statement | B20 -> diesel 20%, B100 -> biodiesel, E85 -> e85 (flagged), E10 -> gasoline 10%; the classifier confidently picks the stationary biofuel variant, contradicted by fleet context, so it halts for a reviewer |
| MF-08 | Photographed receipt, no text | Halts: `unreadable_document` |
| MF-09 | Fleet EV-charging statement (kWh) | Halts: `unsupported_document` (electricity is Scope 2) |

Samples with `reviewer_override` are run twice by the tests: without the override they
must halt (`expected_halt_without_override`), with it every field must match.

```bash
pytest backend/tests/golden_s1/test_fuel_golden.py
python -m backend.tests.golden_s1.stationary_combustion_golden mobile_combustion
python scripts/generate_mobile_combustion_samples.py   # regenerate (review both diffs)
```
