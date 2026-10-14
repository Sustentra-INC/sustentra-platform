# Emissions roll-up

The roll-up turns each emission category's result into the Scope 1, Scope 2 and inventory totals, then checks the company's reported values against them. It follows the roll-up chart in GHG Required Data (Structure Breakdown tab):

- **Step 1a:** category results to Scope 1 (each category, each gas, the total, biogenic CO2 as a memo).
- **Step 1b:** category results to Scope 2, location-based and market-based.
- **Step 2:** inventory totals (Scope 1 + Scope 2, once per Scope 2 basis).
- **Final outputs:** the values companies report (workbook rows 22-50): reported vs recalculated, difference %, and within the materiality threshold (5% unless Setup says otherwise).

Code: `backend/app/services/emissions_rollup.py` (pure, table-driven). TypeScript types: `frontend/features/s1/api/recalculation.ts` (`Rollup`, `RollupLayout` and related).

## Endpoints

| Call | What it adds |
|---|---|
| `GET /v1/reference/recalculation` | `rollup_layout`: the structure with no values (steps, sources, nodes, final outputs). Use it to draw the chart before an engagement has data. |
| `GET /v1/engagements/{id}/recalculation` | `rollup`: the values for one engagement. Older responses have no `rollup`; fall back to `comparisons`. |

All other fields are unchanged. `needs_input[]` and `awaiting_review[]` items also gain `category` (the source key they hold open).

## Shape of `rollup`

```json
{
  "version": 1, "gwp_set": "AR5", "tolerance_pct": 5.0,
  "gas_groups": ["CO2", "CH4", "N2O", "HFCs", "PFCs", "SF6", "NF3"],
  "steps": [{"key": "step_1a", "label": "...", "order": 1, "node_keys": ["..."]}, "...",
            {"key": "final_outputs", "label": "...", "order": 4, "output_keys": ["..."]}],
  "categories": {"stationary_combustion": {"status": "calculated", "open_items": 0, "gaps": [], "absent_reason": null}},
  "nodes": {"scope1_total": {"step": "step_1a", "co2e_t": 170.78, "status": "complete", "terms": [], "missing": []}},
  "final_outputs": [{"key": "scope1_total", "workbook_row": 22, "reported": 175, "recalculated": 170.78,
                     "difference_pct": -2.41, "within_threshold": true, "status": "within_tolerance"}],
  "checks": [{"key": "scope1_total_equals_gas_sum", "ok": true}]
}
```

Numbers are unrounded metric tonnes. Round only for display (2 dp). `null` means "not available", never 0.

## Sources (categories)

| key | built | workbook row |
|---|---|---|
| `stationary_combustion` | yes | 42 |
| `mobile_combustion` | yes | 43 |
| `process_sources` | no | 44 |
| `fugitive_refrigerants` | yes | 45 (part) |
| `fugitive_purchased_gases` | no | 45 (part) |
| `agricultural_sources` | no | 46 |
| `purchased_electricity` | yes | 47 |
| `purchased_steam`, `purchased_heating`, `purchased_cooling` | no | 48, 49, 50 |

Source status:

| status | meaning | contributes |
|---|---|---|
| `calculated` | result from reviewed evidence | its numbers |
| `partial` | result, but open questions or a gap (e.g. no vehicle groups for mobile CH4/N2O) | its numbers |
| `awaiting_inputs` | evidence exists, questions still open | null |
| `confirmed_absent` | the reviewer said the company has none (`absent_sources`, with a reason) | 0 |
| `no_evidence` | built, no evidence uploaded | null |
| `not_built` | category not built yet | null |

## Nodes (Steps 1a, 1b, 2)

Each node has `co2e_t`, `status` (`complete`, `partial`, `not_available`), `terms` (what was added), `missing` (which sources are absent from the sum, and why) and `lower_bound` (a partial value that can only grow). Gas nodes also have `mass_t` (tonnes of the gas itself).

- A total with any missing source is `partial`: it shows the sum so far and names what is missing.
- Scope 2 HFCs, PFCs, SF6 and NF3 are structural zeros (`basis: "structural_zero"`).
- Biogenic CO2 is a memo, in no total.

## Final outputs

| status | when |
|---|---|
| `not_in_scope` | Setup set the data point out of scope: shown, never judged |
| `not_recalculated` | every missing source is not built yet |
| `no_evidence` | nothing to compare (`reason`: `no_evidence` or `awaiting_inputs`) |
| `not_reported` | no reported value |
| `needs_unit` | HFCs / PFCs / SF6 row without a unit (t or t CO2e); `unit_hint` suggests one |
| `within_tolerance` / `exceeds_tolerance` | complete total compared |
| `incomplete` | partial total: never "within"; `within_threshold` still says "within so far" |
| `exceeds_tolerance` with `reason: "lower_bound"` | partial total already above the reported value by more than the threshold |

## Settings the screen can save

Under `settings.recalculation` (PATCH `/v1/engagements/{id}`):

- `reported`: `{output key: number >= 0}`, any final output key.
- `absent_sources`: `{source key: reason}` (reason required, at most 500 characters).
- `reported_units`: `{key: "t" | "t CO2e"}` for rows 23-28 and 30-36.

## Open questions for Claire's chart

1. Does the chart's step structure match Steps 1a / 1b / 2 above? Moving a node between steps only edits `LAYOUT`.
2. Are rows 26-28 (HFCs, PFCs, SF6) reported in tonnes of gas or t CO2e?
3. Are rows 30-32 and 47 location-based only (as now), or also market-based?
4. Should the inventory totals be reported values (final outputs) too?
5. Unbuilt categories show `not_available` and make totals partial. Is that the right behaviour, or should they count as 0?
6. Is Scope 1 NF3 needed as a final output (there is no workbook row for it)?
7. HFOs and natural refrigerants (R-1234yf, R-290, ...) count in the fugitive total under "other gases". Keep?
8. Scope 2 F-gases are always 0. Is that right for the chart?
