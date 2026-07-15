# Vocabulary Workbook Cleanup (PR2.5 + PR2.5b)

## Scope

This document consolidates vocabulary workbook cleanup activity across:

- PR2.5: `Variants.confidence_threshold_default` normalization
- PR2.5b: `Variants.population_status` normalization preflight and blocker report

## Purpose

PR2.5 makes the real Vocabulary Library workbook loadable end-to-end by replacing bare `provisional` threshold placeholders in `Variants.confidence_threshold_default` with explicit numeric provisional thresholds.

## Workbook Updated

- Updated workbook: `reference-data/vocab library/Vocabulary_Library_v1.0.xlsx`
- Backup source: `backups/pr2_5_vocab_cleanup_20260714_203047/Vocabulary_Library_v1.0.xlsx`
- Rows changed: **94**

## Changed Rows

| Excel row | variant_id | canonical_type_id | old value | new value |
|---:|---|---|---|---|
| 22 | VR-FACSRCLIST-SRCREGISTER | CT-GHG-FACSRCLIST | provisional | 0.80 (provisional) |
| 23 | VR-FACSRCLIST-EQUIPLIST | CT-GHG-FACSRCLIST | provisional | 0.80 (provisional) |
| 24 | VR-FACSRCLIST-EMSEXPORT | CT-GHG-FACSRCLIST | provisional | 0.80 (provisional) |
| 25 | VR-S1-SRCEXCL-01 | CT-S1-SRCEXCL | provisional | 0.80 (provisional) |
| 26 | VR-S1-SRCEXCL-02 | CT-S1-SRCEXCL | provisional | 0.80 (provisional) |
| 27 | VR-S1-FUELQTY-01 | CT-S1-FUELQTY | provisional | 0.80 (provisional) |
| 28 | VR-S1-FUELQTY-02 | CT-S1-FUELQTY | provisional | 0.80 (provisional) |
| 29 | VR-S1-FUELQTY-03 | CT-S1-FUELQTY | provisional | 0.80 (provisional) |
| 30 | VR-S1-FUELQTY-04 | CT-S1-FUELQTY | provisional | 0.80 (provisional) |
| 31 | VR-S1-FUELQTY-05 | CT-S1-FUELQTY | provisional | 0.80 (provisional) |
| 32 | VR-S1-FUELQTY-06 | CT-S1-FUELQTY | provisional | 0.80 (provisional) |
| 33 | VR-S1-FUELPROP-01 | CT-S1-FUELPROP | provisional | 0.80 (provisional) |
| 34 | VR-S1-FUELPROP-02 | CT-S1-FUELPROP | provisional | 0.80 (provisional) |
| 35 | VR-S1-FUELPROP-03 | CT-S1-FUELPROP | provisional | 0.80 (provisional) |
| 36 | VR-S1-ONSGEN-01 | CT-S1-ONSGEN | provisional | 0.80 (provisional) |
| 37 | VR-S1-ONSGEN-02 | CT-S1-ONSGEN | provisional | 0.80 (provisional) |
| 38 | VR-S1-ONSGEN-03 | CT-S1-ONSGEN | provisional | 0.80 (provisional) |
| 39 | VR-S1-DIRMON-01 | CT-S1-DIRMON | provisional | 0.80 (provisional) |
| 40 | VR-S1-DIRMON-02 | CT-S1-DIRMON | provisional | 0.80 (provisional) |
| 41 | VR-S1-MOBFUEL-01 | CT-S1-MOBFUEL | provisional | 0.80 (provisional) |
| 42 | VR-S1-MOBFUEL-02 | CT-S1-MOBFUEL | provisional | 0.80 (provisional) |
| 43 | VR-S1-MOBFUEL-03 | CT-S1-MOBFUEL | provisional | 0.80 (provisional) |
| 44 | VR-S1-MOBFUEL-04 | CT-S1-MOBFUEL | provisional | 0.80 (provisional) |
| 45 | VR-S1-MOBFUEL-05 | CT-S1-MOBFUEL | provisional | 0.80 (provisional) |
| 46 | VR-S1-MOBFUEL-06 | CT-S1-MOBFUEL | provisional | 0.80 (provisional) |
| 47 | VR-S1-TRANSACT-01 | CT-S1-TRANSACT | provisional | 0.80 (provisional) |
| 48 | VR-S1-TRANSACT-02 | CT-S1-TRANSACT | provisional | 0.80 (provisional) |
| 49 | VR-S1-TRANSACT-03 | CT-S1-TRANSACT | provisional | 0.80 (provisional) |
| 50 | VR-S1-TRANSACT-04 | CT-S1-TRANSACT | provisional | 0.80 (provisional) |
| 51 | VR-S1-MOBASSET-01 | CT-S1-MOBASSET | provisional | 0.80 (provisional) |
| 52 | VR-S1-MOBASSET-02 | CT-S1-MOBASSET | provisional | 0.80 (provisional) |
| 53 | VR-S1-PROCACT-01 | CT-S1-PROCACT | provisional | 0.80 (provisional) |
| 54 | VR-S1-PROCACT-02 | CT-S1-PROCACT | provisional | 0.80 (provisional) |
| 55 | VR-S1-PROCACT-03 | CT-S1-PROCACT | provisional | 0.80 (provisional) |
| 56 | VR-S1-PROCMASS-01 | CT-S1-PROCMASS | provisional | 0.80 (provisional) |
| 57 | VR-S1-PROCMASS-02 | CT-S1-PROCMASS | provisional | 0.80 (provisional) |
| 58 | VR-S1-PROCMEAS-01 | CT-S1-PROCMEAS | provisional | 0.80 (provisional) |
| 59 | VR-S1-PROCMEAS-02 | CT-S1-PROCMEAS | provisional | 0.80 (provisional) |
| 60 | VR-S1-FGASINV-01 | CT-S1-FGASINV | provisional | 0.80 (provisional) |
| 61 | VR-S1-FGASINV-02 | CT-S1-FGASINV | provisional | 0.80 (provisional) |
| 62 | VR-S1-REFRSVC-01 | CT-S1-REFRSVC | provisional | 0.80 (provisional) |
| 63 | VR-S1-REFRSVC-02 | CT-S1-REFRSVC | provisional | 0.80 (provisional) |
| 64 | VR-S1-REFRSVC-03 | CT-S1-REFRSVC | provisional | 0.80 (provisional) |
| 65 | VR-S1-EQUIPLEAK-01 | CT-S1-EQUIPLEAK | provisional | 0.80 (provisional) |
| 66 | VR-S1-EQUIPLEAK-02 | CT-S1-EQUIPLEAK | provisional | 0.80 (provisional) |
| 67 | VR-S1-VENTFLARE-01 | CT-S1-VENTFLARE | provisional | 0.80 (provisional) |
| 68 | VR-S1-VENTFLARE-02 | CT-S1-VENTFLARE | provisional | 0.80 (provisional) |
| 69 | VR-S1-WASTEWTR-01 | CT-S1-WASTEWTR | provisional | 0.80 (provisional) |
| 70 | VR-S1-WASTEWTR-02 | CT-S1-WASTEWTR | provisional | 0.80 (provisional) |
| 71 | VR-S1-COALFUG-01 | CT-S1-COALFUG | provisional | 0.80 (provisional) |
| 72 | VR-S1-COALFUG-02 | CT-S1-COALFUG | provisional | 0.80 (provisional) |
| 73 | VR-S1-GASFUG-01 | CT-S1-GASFUG | provisional | 0.80 (provisional) |
| 74 | VR-S1-GASFUG-02 | CT-S1-GASFUG | provisional | 0.80 (provisional) |
| 75 | VR-S1-FGASPROC-01 | CT-S1-FGASPROC | provisional | 0.80 (provisional) |
| 76 | VR-S1-FGASPROC-02 | CT-S1-FGASPROC | provisional | 0.80 (provisional) |
| 77 | VR-S1-FGASPROC-03 | CT-S1-FGASPROC | provisional | 0.80 (provisional) |
| 78 | VR-S1-EFREF-01 | CT-S1-EFREF | provisional | 0.80 (provisional) |
| 79 | VR-S1-EFREF-02 | CT-S1-EFREF | provisional | 0.80 (provisional) |
| 80 | VR-S1-EFREF-03 | CT-S1-EFREF | provisional | 0.80 (provisional) |
| 81 | VR-S1-METHODDOC-01 | CT-S1-METHODDOC | provisional | 0.80 (provisional) |
| 82 | VR-S1-DATAQA-04 | CT-S1-DATAQA | provisional | 0.80 (provisional) |
| 83 | VR-S1-METHODDOC-02 | CT-S1-METHODDOC | provisional | 0.80 (provisional) |
| 84 | VR-S1-DATAQA-01 | CT-S1-DATAQA | provisional | 0.80 (provisional) |
| 85 | VR-S1-DATAQA-02 | CT-S1-DATAQA | provisional | 0.80 (provisional) |
| 86 | VR-S1-DATAQA-03 | CT-S1-DATAQA | provisional | 0.80 (provisional) |
| 87 | VR-LEASEAGREEMENT | CT-GHG-BOUNDAGREE | provisional | 0.80 (provisional) |
| 88 | VR-JVAGREEMENT | CT-GHG-BOUNDAGREE | provisional | 0.80 (provisional) |
| 89 | VR-OUTSOURCINGAGREEMENT | CT-GHG-BOUNDAGREE | provisional | 0.80 (provisional) |
| 90 | VR-EMISSIONSRIGHTS | CT-GHG-BOUNDAGREE | provisional | 0.80 (provisional) |
| 91 | VR-S1-MEASCAL-01 | CT-S1-MEASCAL | provisional | 0.80 (provisional) |
| 92 | VR-S1-MEASCAL-02 | CT-S1-MEASCAL | provisional | 0.80 (provisional) |
| 93 | VR-S1-MEASCAL-03 | CT-S1-MEASCAL | provisional | 0.80 (provisional) |
| 94 | VR-S1-MEASCAL-04 | CT-S1-MEASCAL | provisional | 0.80 (provisional) |
| 95 | VR-BASEYEAR-SELECTIONMEMO | CT-GHG-BASEYEAR | provisional | 0.80 (provisional) |
| 96 | VR-BASEYEAR-RECALCWORKSHEET | CT-GHG-BASEYEAR | provisional | 0.80 (provisional) |
| 97 | VR-S1-ELECSF6-01 | CT-S1-ELECSF6 | provisional | 0.80 (provisional) |
| 98 | VR-S1-ELECSF6-02 | CT-S1-ELECSF6 | provisional | 0.80 (provisional) |
| 99 | VR-S1-ELECSF6-03 | CT-S1-ELECSF6 | provisional | 0.80 (provisional) |
| 100 | VR-S1-MINECOMB-01 | CT-S1-MINECOMB | provisional | 0.80 (provisional) |
| 101 | VR-S1-MINECOMB-02 | CT-S1-MINECOMB | provisional | 0.80 (provisional) |
| 102 | VR-S1-ONSGEN-04 | CT-S1-ONSGEN | provisional | 0.80 (provisional) |
| 103 | VR-S1-ONSGEN-05 | CT-S1-ONSGEN | provisional | 0.80 (provisional) |
| 104 | VR-S1-PROCACT-04 | CT-S1-PROCACT | provisional | 0.80 (provisional) |
| 105 | VR-S1-PROCACT-05 | CT-S1-PROCACT | provisional | 0.80 (provisional) |
| 106 | VR-S1-PROCACT-06 | CT-S1-PROCACT | provisional | 0.80 (provisional) |
| 107 | VR-S1-PROCACT-07 | CT-S1-PROCACT | provisional | 0.80 (provisional) |
| 108 | VR-S1-PROCACT-08 | CT-S1-PROCACT | provisional | 0.80 (provisional) |
| 109 | VR-S1-PROCACT-09 | CT-S1-PROCACT | provisional | 0.80 (provisional) |
| 110 | VR-S1-PROCMASS-03 | CT-S1-PROCMASS | provisional | 0.80 (provisional) |
| 111 | VR-S1-PROCMASS-04 | CT-S1-PROCMASS | provisional | 0.80 (provisional) |
| 112 | VR-S1-PROCMASS-05 | CT-S1-PROCMASS | provisional | 0.80 (provisional) |
| 113 | VR-S1-PROCMASS-06 | CT-S1-PROCMASS | provisional | 0.80 (provisional) |
| 114 | VR-S1-WASTEWTR-03 | CT-S1-WASTEWTR | provisional | 0.80 (provisional) |
| 115 | VR-S1-PROCACT-10 | CT-S1-PROCACT | provisional | 0.80 (provisional) |

## Confirmations

- No loader logic was weakened. The loader still raises clear errors on invalid threshold values.
- Rows are mutable reference data; column contracts remain stable.

## PR2.5b Population Status Cleanup (Applied)

### Objective

Normalize `Variants.population_status` values under strict rules:

- blank / null / whitespace -> `provisional`
- case/spacing variants of allowed values -> normalized lowercase
- `skeleton` -> `provisional`

### Decision

- Non-empty invalid value `skeleton` was mapped to `provisional`.

### Workbook and Backup

- Target workbook: `reference-data/vocab library/Vocabulary_Library_v1.0.xlsx`
- PR2.5b backup (preserved, created before edits): `backups/pr2_5b_population_status_cleanup_20260714_210138/Vocabulary_Library_v1.0.xlsx`

### Rows Changed

- Blank/null rows changed to `provisional`: **92**
- `skeleton` rows changed to `provisional`: **4**
- Case/spacing normalization rows: **0**
- Total `population_status` rows changed: **96**
- Only the `Variants.population_status` column was modified.

### Full Row-Level Ledger

| Excel row | variant_id | canonical_type_id | old value | new value |
|---:|---|---|---|---|
| 22 | VR-FACSRCLIST-SRCREGISTER | CT-GHG-FACSRCLIST | (blank) | provisional |
| 23 | VR-FACSRCLIST-EQUIPLIST | CT-GHG-FACSRCLIST | (blank) | provisional |
| 24 | VR-FACSRCLIST-EMSEXPORT | CT-GHG-FACSRCLIST | (blank) | provisional |
| 25 | VR-S1-SRCEXCL-01 | CT-S1-SRCEXCL | (blank) | provisional |
| 26 | VR-S1-SRCEXCL-02 | CT-S1-SRCEXCL | (blank) | provisional |
| 27 | VR-S1-FUELQTY-01 | CT-S1-FUELQTY | (blank) | provisional |
| 28 | VR-S1-FUELQTY-02 | CT-S1-FUELQTY | (blank) | provisional |
| 29 | VR-S1-FUELQTY-03 | CT-S1-FUELQTY | (blank) | provisional |
| 30 | VR-S1-FUELQTY-04 | CT-S1-FUELQTY | (blank) | provisional |
| 31 | VR-S1-FUELQTY-05 | CT-S1-FUELQTY | (blank) | provisional |
| 32 | VR-S1-FUELQTY-06 | CT-S1-FUELQTY | (blank) | provisional |
| 33 | VR-S1-FUELPROP-01 | CT-S1-FUELPROP | (blank) | provisional |
| 34 | VR-S1-FUELPROP-02 | CT-S1-FUELPROP | (blank) | provisional |
| 35 | VR-S1-FUELPROP-03 | CT-S1-FUELPROP | (blank) | provisional |
| 36 | VR-S1-ONSGEN-01 | CT-S1-ONSGEN | (blank) | provisional |
| 37 | VR-S1-ONSGEN-02 | CT-S1-ONSGEN | (blank) | provisional |
| 39 | VR-S1-DIRMON-01 | CT-S1-DIRMON | (blank) | provisional |
| 40 | VR-S1-DIRMON-02 | CT-S1-DIRMON | (blank) | provisional |
| 41 | VR-S1-MOBFUEL-01 | CT-S1-MOBFUEL | (blank) | provisional |
| 42 | VR-S1-MOBFUEL-02 | CT-S1-MOBFUEL | (blank) | provisional |
| 43 | VR-S1-MOBFUEL-03 | CT-S1-MOBFUEL | (blank) | provisional |
| 44 | VR-S1-MOBFUEL-04 | CT-S1-MOBFUEL | (blank) | provisional |
| 45 | VR-S1-MOBFUEL-05 | CT-S1-MOBFUEL | (blank) | provisional |
| 46 | VR-S1-MOBFUEL-06 | CT-S1-MOBFUEL | (blank) | provisional |
| 47 | VR-S1-TRANSACT-01 | CT-S1-TRANSACT | (blank) | provisional |
| 48 | VR-S1-TRANSACT-02 | CT-S1-TRANSACT | (blank) | provisional |
| 49 | VR-S1-TRANSACT-03 | CT-S1-TRANSACT | (blank) | provisional |
| 50 | VR-S1-TRANSACT-04 | CT-S1-TRANSACT | (blank) | provisional |
| 51 | VR-S1-MOBASSET-01 | CT-S1-MOBASSET | (blank) | provisional |
| 52 | VR-S1-MOBASSET-02 | CT-S1-MOBASSET | (blank) | provisional |
| 53 | VR-S1-PROCACT-01 | CT-S1-PROCACT | (blank) | provisional |
| 54 | VR-S1-PROCACT-02 | CT-S1-PROCACT | (blank) | provisional |
| 55 | VR-S1-PROCACT-03 | CT-S1-PROCACT | (blank) | provisional |
| 56 | VR-S1-PROCMASS-01 | CT-S1-PROCMASS | (blank) | provisional |
| 57 | VR-S1-PROCMASS-02 | CT-S1-PROCMASS | (blank) | provisional |
| 58 | VR-S1-PROCMEAS-01 | CT-S1-PROCMEAS | (blank) | provisional |
| 59 | VR-S1-PROCMEAS-02 | CT-S1-PROCMEAS | (blank) | provisional |
| 60 | VR-S1-FGASINV-01 | CT-S1-FGASINV | (blank) | provisional |
| 61 | VR-S1-FGASINV-02 | CT-S1-FGASINV | (blank) | provisional |
| 62 | VR-S1-REFRSVC-01 | CT-S1-REFRSVC | (blank) | provisional |
| 63 | VR-S1-REFRSVC-02 | CT-S1-REFRSVC | (blank) | provisional |
| 64 | VR-S1-REFRSVC-03 | CT-S1-REFRSVC | (blank) | provisional |
| 65 | VR-S1-EQUIPLEAK-01 | CT-S1-EQUIPLEAK | (blank) | provisional |
| 66 | VR-S1-EQUIPLEAK-02 | CT-S1-EQUIPLEAK | (blank) | provisional |
| 67 | VR-S1-VENTFLARE-01 | CT-S1-VENTFLARE | (blank) | provisional |
| 68 | VR-S1-VENTFLARE-02 | CT-S1-VENTFLARE | (blank) | provisional |
| 69 | VR-S1-WASTEWTR-01 | CT-S1-WASTEWTR | (blank) | provisional |
| 70 | VR-S1-WASTEWTR-02 | CT-S1-WASTEWTR | (blank) | provisional |
| 71 | VR-S1-COALFUG-01 | CT-S1-COALFUG | (blank) | provisional |
| 72 | VR-S1-COALFUG-02 | CT-S1-COALFUG | (blank) | provisional |
| 73 | VR-S1-GASFUG-01 | CT-S1-GASFUG | (blank) | provisional |
| 74 | VR-S1-GASFUG-02 | CT-S1-GASFUG | (blank) | provisional |
| 75 | VR-S1-FGASPROC-01 | CT-S1-FGASPROC | (blank) | provisional |
| 76 | VR-S1-FGASPROC-02 | CT-S1-FGASPROC | (blank) | provisional |
| 77 | VR-S1-FGASPROC-03 | CT-S1-FGASPROC | (blank) | provisional |
| 78 | VR-S1-EFREF-01 | CT-S1-EFREF | (blank) | provisional |
| 79 | VR-S1-EFREF-02 | CT-S1-EFREF | (blank) | provisional |
| 80 | VR-S1-EFREF-03 | CT-S1-EFREF | (blank) | provisional |
| 81 | VR-S1-METHODDOC-01 | CT-S1-METHODDOC | (blank) | provisional |
| 82 | VR-S1-DATAQA-04 | CT-S1-DATAQA | (blank) | provisional |
| 83 | VR-S1-METHODDOC-02 | CT-S1-METHODDOC | (blank) | provisional |
| 84 | VR-S1-DATAQA-01 | CT-S1-DATAQA | (blank) | provisional |
| 85 | VR-S1-DATAQA-02 | CT-S1-DATAQA | (blank) | provisional |
| 86 | VR-S1-DATAQA-03 | CT-S1-DATAQA | (blank) | provisional |
| 87 | VR-LEASEAGREEMENT | CT-GHG-BOUNDAGREE | (blank) | provisional |
| 88 | VR-JVAGREEMENT | CT-GHG-BOUNDAGREE | (blank) | provisional |
| 89 | VR-OUTSOURCINGAGREEMENT | CT-GHG-BOUNDAGREE | (blank) | provisional |
| 90 | VR-EMISSIONSRIGHTS | CT-GHG-BOUNDAGREE | (blank) | provisional |
| 91 | VR-S1-MEASCAL-01 | CT-S1-MEASCAL | (blank) | provisional |
| 92 | VR-S1-MEASCAL-02 | CT-S1-MEASCAL | (blank) | provisional |
| 93 | VR-S1-MEASCAL-03 | CT-S1-MEASCAL | (blank) | provisional |
| 94 | VR-S1-MEASCAL-04 | CT-S1-MEASCAL | (blank) | provisional |
| 95 | VR-BASEYEAR-SELECTIONMEMO | CT-GHG-BASEYEAR | (blank) | provisional |
| 96 | VR-BASEYEAR-RECALCWORKSHEET | CT-GHG-BASEYEAR | (blank) | provisional |
| 97 | VR-S1-ELECSF6-01 | CT-S1-ELECSF6 | (blank) | provisional |
| 98 | VR-S1-ELECSF6-02 | CT-S1-ELECSF6 | (blank) | provisional |
| 99 | VR-S1-ELECSF6-03 | CT-S1-ELECSF6 | (blank) | provisional |
| 100 | VR-S1-MINECOMB-01 | CT-S1-MINECOMB | (blank) | provisional |
| 101 | VR-S1-MINECOMB-02 | CT-S1-MINECOMB | (blank) | provisional |
| 103 | VR-S1-ONSGEN-05 | CT-S1-ONSGEN | (blank) | provisional |
| 104 | VR-S1-PROCACT-04 | CT-S1-PROCACT | (blank) | provisional |
| 105 | VR-S1-PROCACT-05 | CT-S1-PROCACT | (blank) | provisional |
| 106 | VR-S1-PROCACT-06 | CT-S1-PROCACT | (blank) | provisional |
| 107 | VR-S1-PROCACT-07 | CT-S1-PROCACT | (blank) | provisional |
| 108 | VR-S1-PROCACT-08 | CT-S1-PROCACT | (blank) | provisional |
| 109 | VR-S1-PROCACT-09 | CT-S1-PROCACT | (blank) | provisional |
| 110 | VR-S1-PROCMASS-03 | CT-S1-PROCMASS | (blank) | provisional |
| 111 | VR-S1-PROCMASS-04 | CT-S1-PROCMASS | (blank) | provisional |
| 112 | VR-S1-PROCMASS-05 | CT-S1-PROCMASS | (blank) | provisional |
| 113 | VR-S1-PROCMASS-06 | CT-S1-PROCMASS | (blank) | provisional |
| 114 | VR-S1-WASTEWTR-03 | CT-S1-WASTEWTR | (blank) | provisional |
| 115 | VR-S1-PROCACT-10 | CT-S1-PROCACT | (blank) | provisional |
| 14 | VR-S2-SELFGEN-CERTSALE | CT-S2-SELFGEN | skeleton | provisional |
| 17 | VR-GHG-PDFEXPORT | CT-GHG-WORKBOOK | skeleton | provisional |
| 21 | VR-BASEYEAR-STRUCTURALCHANGE | CT-GHG-BASEYEAR | skeleton | provisional |
| 102 | VR-S1-ONSGEN-04 | CT-S1-ONSGEN | skeleton | provisional |

### Strict Loader Confirmation

- Strict loader logic was not weakened. Required-field and enum validation remain intact.
- The real workbook now loads successfully because the data was normalized, not because validation was relaxed.
