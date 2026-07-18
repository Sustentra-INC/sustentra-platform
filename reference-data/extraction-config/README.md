# Extraction Config Seed (PR5)

This folder holds **versioned reference data** for extraction target generation.
It is committed to the repository (it is not a local sample and is not ignored).

## Files

- `extraction_config_seed.json` — a handwritten array of extraction configs for a
  small S1 utility/fuel pilot.

## What this is

Each object follows the intent of `contracts/extraction_config.schema.json` and
describes **which field to attempt for a given classified document type** and
**how** (as metadata only). These are *instructions/target metadata*, not
extracted values.

PR5 does **not** extract any values. Extraction of values into
`extraction_candidate` records happens later, in PR6.

## Canonical types covered

The seed aligns `canonical_type_id` values to the real Vocabulary Library:

- `CT-S1-FUELQTY` — Stationary Fuel Consumption Record
- `CT-S1-MOBFUEL` — Mobile Fuel Consumption Record

## Status and versioning

- `population_status` is `provisional` for all seed rows.
- `version` is `v0.1`.

These configs are seed-only and provisional. `field_id` and `regulatory_field_id`
values should be aligned to the regulatory/product schema and the Vocabulary
Library in a later PR.

## Do not

- Do not place local, private sample documents here.
- Do not add secrets.
- Do not implement extraction logic here; this is configuration data only.
