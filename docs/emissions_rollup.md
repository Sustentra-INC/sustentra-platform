# Emissions roll-up

The roll-up turns each emission category's result into the Scope 1, Scope 2 and inventory totals, then checks the company's reported values against them. It follows the roll-up chart in GHG Required Data (Structure Breakdown tab), with Claire's answers of 22 October 2026 (recorded at the end):

- **Step 1a:** category results to Scope 1: each category, each of the 7 gases, the total, and biogenic CO2 (a placeholder, in no total).
- **Step 1b:** category results to Scope 2, location-based and market-based. Runs side by side with 1a.
- **Step 2:** inventory totals (Scope 1 + Scope 2, once per Scope 2 basis). Runs after 1a and 1b.
- **Final outputs:** the list of values companies report (workbook rows 22-38 and 43-51): reported vs recalculated, difference %, and within the materiality threshold (5% unless Setup says otherwise). A list, not a step.

Code: `backend/app/services/emissions_rollup.py` (pure, table-driven). TypeScript types: `frontend/features/s1/api/recalculation.ts` (`Rollup`, `RollupLayout` and related). Setup's in-scope list (`DATA_POINT_CATALOGUE`) is built from the same final outputs, so the two cannot drift.

## The rules

- **The 7 gases.** Every scope uses CO2, CH4, N2O, HFCs, PFCs, SF6 and NF3. Anything else (HFOs, ammonia, hydrocarbons, the HCFC share of a blend) is excluded from every total and shown under the category's `excluded`.
- **Two numbers per gas.** Each category gives, for every gas, the mass (t of gas) and the CO2e (t).
  - Mass adds up gas by gas across categories: one total per gas, per scope.
  - CO2e adds up within each category to the category total; the category totals add up to the scope total.
- **Per-gas rows are in tonnes of gas,** under each of the three totals: Scope 1, Scope 2 location-based, Scope 2 market-based (three sets of 7).
- **Scope 2 keeps every gas.** No Scope 2 method emits fluorinated gases, so HFCs, PFCs, SF6 and NF3 are placeholders (`basis: "structural_zero"`): 0, under both bases.
- **Missing categories count as 0.** A category that is not built, or built but without evidence, is `not_available` and adds 0 to every total. The roll-up always runs and produces every total; a total lists such categories under `counted_as_zero`.
- **Partial means open work.** A total is `partial` only while a category with evidence is still being worked on: open questions, missing vehicle groups, or a refrigerant whose make-up is unknown.
- **A true 0** for a category itself needs the reviewer's confirmation that the company has none (`absent_sources`, with a reason).
- **Biogenic CO2** is a placeholder (`not_available`) until its calculation is agreed. The calculator already gives biogenic CO2 for biomass fuels; `BIOGENIC_BUILT = True` reports it.

## Endpoints

| Call | What it adds |
|---|---|
| `GET /v1/reference/recalculation` | `rollup_layout`: the structure with no values (steps, sources, nodes, final outputs). Use it to draw the chart before an engagement has data. |
| `GET /v1/engagements/{id}/recalculation` | `rollup`: the values for one engagement. Older responses have no `rollup`; fall back to `comparisons`. |

## Shape of `rollup`

```json
{
  "version": 2, "gwp_set": "AR5", "tolerance_pct": 5.0,
  "gas_groups": ["CO2", "CH4", "N2O", "HFCs", "PFCs", "SF6", "NF3"],
  "steps": [{"key": "step_1a", "label": "...", "order": 1, "after": [], "node_keys": ["..."]},
            {"key": "step_1b", "label": "...", "order": 2, "after": [], "node_keys": ["..."]},
            {"key": "step_2", "label": "...", "order": 3, "after": ["step_1a", "step_1b"], "node_keys": ["..."]}],
  "categories": {"fugitive_refrigerants": {"status": "calculated", "open_items": 0, "gaps": [],
                                           "excluded": {"mass_t": 0.0045, "co2e_t": 0.0045}}},
  "nodes": {"scope1_total": {"step": "step_1a", "co2e_t": 170.78, "status": "complete", "terms": [], "missing": [],
                             "counted_as_zero": [{"source": "process_sources", "reason": "not_built"}]}},
  "final_outputs": [{"key": "scope1_total", "workbook_row": 22, "reported": 175, "recalculated": 170.78,
                     "difference_pct": -2.41, "within_threshold": true, "status": "within_tolerance"}],
  "checks": [{"key": "scope1_total_equals_gas_sum", "ok": true},
             {"key": "fugitive_total_equals_gas_sum", "ok": true}]
}
```

Numbers are unrounded metric tonnes. Round only for display (2 dp). `null` means "not available" (and counts as 0 in the totals above it).

## Sources (categories)

| key | built | workbook row | gases |
|---|---|---|---|
| `stationary_combustion` | yes | 43 | CO2, CH4, N2O |
| `mobile_combustion` | yes | 44 | CO2, CH4, N2O |
| `process_sources` | no | 45 | all 7 |
| `fugitive_refrigerants` | yes | 46 (part) | CO2, HFCs, PFCs, SF6, NF3 |
| `fugitive_purchased_gases` | no | 46 (part) | all 7 |
| `agricultural_sources` | no | 47 | CO2, CH4, N2O |
| `purchased_electricity` | yes | 48 | CO2, CH4, N2O |
| `purchased_steam` | yes | 49 | CO2, CH4, N2O |
| `purchased_heating` | yes | 50 | CO2, CH4, N2O |
| `purchased_cooling` | no | 51 | CO2, CH4, N2O |

Rows are those of "Data from summary documents" after Claire added Scope 1 NF3 at row 29, which moved every row below it down by one. To confirm against her updated workbook.

Source status:

| status | meaning | in the totals |
|---|---|---|
| `calculated` | result from reviewed evidence | its numbers |
| `partial` | result, but open questions or a gap (e.g. no vehicle groups for mobile CH4/N2O) | its numbers; the total is partial |
| `awaiting_inputs` | evidence exists, questions still open | 0 for now; the total is partial |
| `confirmed_absent` | the reviewer said the company has none (`absent_sources`, with a reason) | 0, a true 0 |
| `no_evidence` | built, no evidence uploaded | 0 (`counted_as_zero`) |
| `not_built` | category not built yet | 0 (`counted_as_zero`) |

## Nodes (Steps 1a, 1b, 2)

Each node has `co2e_t`, `status` (`complete`, `partial`, `not_available`), `terms` (what was added), `missing` (open work that keeps it partial), `counted_as_zero` (sources added as 0) and `lower_bound` (a partial value that can only grow). Gas nodes also have `mass_t` (tonnes of the gas itself). Category nodes with a value carry `gases`: all 7, each with `mass_t` and `co2e_t`.

- Totals and gas rows always have a value. A category node is `not_available` (null) when none of its sources has a result or a confirmed absence.
- `checks` confirm each scope total equals the sum of its gases, each inventory total equals its scopes, and each category's CO2e equals the sum of its gases.

## Final outputs

| Rows | Data points | Unit |
|---|---|---|
| 22 | Scope 1 (Total) | t CO2e |
| 23-29 | Scope 1 CO2, CH4, N2O, HFCs, PFCs, SF6, NF3 | t of gas |
| 30 | Scope 2 (Total), location-based and market-based | t CO2e |
| 31-37 | Scope 2 CO2 ... NF3, location-based (`scope2_*`) and market-based (`scope2_market_*`) | t of gas |
| 38 | CO2 emissions from biogenic combustion (placeholder) | t CO2e |
| 43-51 | Category totals (Optional) | t CO2e |

| status | when |
|---|---|
| `not_in_scope` | Setup set the data point out of scope: shown, never judged |
| `not_recalculated` | the category (or biogenic CO2) is not built yet |
| `no_evidence` | nothing to compare (`reason`: `no_evidence` or `awaiting_inputs`) |
| `not_reported` | no reported value |
| `within_tolerance` / `exceeds_tolerance` | complete value compared |
| `incomplete` | partial value: never "within"; `within_threshold` still says "within so far" |
| `exceeds_tolerance` with `reason: "lower_bound"` | partial value already above the reported value by more than the threshold |

A per-gas row compared in tonnes of gas whose reported value matches the CO2e instead gets the flag `reported_matches_other_unit`.

## Settings the screen can save

Under `settings.recalculation` (PATCH `/v1/engagements/{id}`):

- `reported`: `{output key: number >= 0}`, any final output key.
- `absent_sources`: `{source key: reason}` (reason required, at most 500 characters).
- `reported_units`: `{key: "t" | "t CO2e"}` for the per-gas rows, when a company reported a gas in t CO2e instead of tonnes.

## Claire's answers (22 October 2026)

1. **Steps:** they match. Step 1a (Scope 1) and Step 1b (Scope 2, once per method) run in parallel; Step 2 (inventory totals) runs after both. "Final outputs" is a list of what to report, not a step.
2. **Units:** the reported per-gas numbers are in tonnes of gas: CO2, CH4, N2O, HFCs, PFCs, SF6 and NF3.
3. **Scope 2 per gas:** one set of the 7 gases under each of the three totals (Scope 1, Scope 2 location-based, Scope 2 market-based).
4. **Inventory totals:** location-based = Scope 1 + Scope 2 location-based; market-based = Scope 1 + Scope 2 market-based (Step 2).
5. **Unbuilt categories:** mark them not_available and count them as 0. The roll-up must always run and produce every total; not every company has every category.
6. **Scope 1 NF3:** a row now (29), added to the workbook by Claire.
7. **HFOs and natural refrigerants:** not included. Anything outside the 7 gases is excluded.
8. **Scope 2 F-gases:** 0 in practice, but keep a placeholder for all 7 gases under each scope.

Also: biogenic CO2 is a category of its own (t CO2e), kept not_available until its calculation is built.
