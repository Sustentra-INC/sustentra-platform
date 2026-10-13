# Reference implementations (test oracles)

Independent implementations of the GHG Required Data workbook's equations, kept
unchanged and used only by tests: `backend/tests/services/test_reference_crosscheck.py`
runs them and `backend/app/services/emissions_calculator.py` on the same inputs with
EPA GHG Emission Factors Hub 2025 factors and requires the same numbers.

- `jerome_stationary_combustion.py`: stationary combustion, Eq 1 / Eq 2 / Eq 3 (Jerome).
- `jerome_mobile_combustion.py`: mobile combustion, CO2 by fuel, CH4 / N2O by vehicle
  group, Eq 1-5 (Jerome).

They take emission factors as arguments (no unit conversion, no EPA lookup), so the
test supplies the Hub factors in kg and compares tonnes.
