# Cross-check against the EPA Simplified GHG Emissions Calculator

We compared our calculator with the EPA's own Simplified GHG Emissions Calculator (September 2024, `calculator_tool_epa.xlsm` in the ESG folder). The EPA tool uses the **June 2024** Emission Factors Hub. We use the **2025** Hub, which is the right one for 2025 reporting.

Tests: `backend/tests/services/test_epa_calculator_crosscheck.py`. The EPA values are in `backend/tests/reference_implementations/epa_simplified_calculator_2024.json`, read from the tool itself.

## What agrees

| | Result |
|---|---|
| Method: stationary combustion | Same formula as the tool (`Stationary Combustion!E141`). 10,000 MMBtu natural gas gives 531.145 t CO2e in both. |
| Method: electricity | Fed the tool's own eGRID2022 factors, we reproduce its worked example exactly: 200,000 kWh in HICC Miscellaneous gives 231,097.2 lb CO2, 24.8 lb CH4 and 3.8 lb N2O. CO2e agrees to one part in a million (we convert with 2,204.62 lb per tonne as Claire's workbook does; the tool uses 0.45359237 kg per lb). |
| Stationary fuel factors | All 28 fuels. CH4 and N2O are identical for every fuel, and CO2 is identical for 26 of the 28 (wood and landfill gas: see below). |
| Vehicle fuel CO2 factors | All 10 fuels identical (biodiesel and ethanol are named "(100%)" in the Hub). |
| GWPs (AR5) | All 32 identical, including CH4 28, N2O 265, SF6 23,500. |
| Biomass | Both leave biomass CO2 out of Scope 1 and report it separately. Biomass CH4 and N2O count in Scope 1 in both. |

## What differs, and why

1. **Grid electricity factors (eGRID2023 vs eGRID2022).**
   - The 2025 Hub moved to eGRID2023. CO2 per MWh changed by -21% to +10% depending on the region, for example:
     - RFC Michigan -20.9%;
     - NPCC Upstate NY -12.2%;
     - WECC California -12.2%;
     - RFC East -9.5%;
     - NYC/Westchester +10.1%;
     - US average -6.3%.
   - **What this means for an audit:** a company that used the 2024 tool, or older factors, will often land outside the 5% threshold on Scope 2 because of the factor vintage alone. That is a factor-vintage finding, not a consumption error, and the workpaper's "Show working" names the eGRID edition used.
2. **Vehicle CH4 and N2O factors.**
   - The 2025 Hub updated the on-road factors and rounds the non-road ones to two decimals.
   - Differences are small, and these gases are a small share of mobile emissions.
3. **Wood and landfill gas CO2.**
   - The tool lists their CO2 factor as 0 per MMBtu. The 2025 Hub gives 93.80 and 52.07 kg/MMBtu.
   - We report that CO2 as biogenic, so Scope 1 is the same either way.
4. **A refrigerant whose material balance comes out negative (open question for Claire).**
   - The EPA tool floors each gas at 0 (`IF(... < 0, 0, ...)`).
   - We keep the negative value and flag it (`negative_refrigerant_emissions`), so a recovery larger than the charge is visible to the reviewer instead of silently zeroed.
   - Both are defensible. Flooring matches the EPA tool. Keeping it shows the data problem. **Claire to decide.**

Also see `backend/tests/services/test_reference_crosscheck.py`, where the calculator agrees with Jerome's reference implementations on 28 values.
