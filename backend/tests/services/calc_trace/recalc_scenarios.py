"""Recalculation scenarios shared by the trace tests: stationary, mobile and electricity lines together."""

from __future__ import annotations

from typing import Any

from backend.app.services.engagement_recalculation_service import EngagementRecalculationService
from backend.tests.services.test_calculation_lines import ELEC_KC, ELEC_STL, GAS_KC, KC, STL
from backend.tests.services.test_calculation_lines import _elec as _elec_record
from backend.tests.services.test_calculation_lines import _gas as _gas_record
from backend.tests.services.test_engagement_recalculation_service import FakeStore, _diesel_purchase, _own

REGIONS = {"Kansas City Plant": "NYUP", "St Louis Plant": "RFCE"}
GROUP_ROAD = {"fuel": "Diesel Fuel", "vehicle_type": "Medium- and Heavy-Duty Vehicles", "factor_fuel_type": "Diesel",
              "on_road": True, "model_year": 2018, "distance": 10000, "distance_unit": "mi", "label": "Heavy trucks"}


def run(store: FakeStore, **recalculation: Any) -> dict:
    engagement = {"id": "ENG-1", "reporting_period_start": "2025-01-01", "reporting_period_end": "2025-12-31",
                  "settings": {"facilities": [KC, STL], "recalculation": recalculation}}
    return EngagementRecalculationService(store, store, store).recalculate(engagement, _own, None)


def mixed_store() -> FakeStore:
    store = FakeStore()
    store.add_document("GAS-KC-1", "CT-S1-FUELQTY", [_gas_record(30000, "2025-01-01", "2025-01-31")])
    store.add_document("GAS-KC-2", "CT-S1-FUELQTY", [_gas_record(35000, "2025-02-01", "2025-02-28")])
    store.add_document("GAS-STL", "CT-S1-FUELQTY", [_gas_record(500, "2025-01-01", "2025-01-31", plant="St Louis Plant")])
    store.add_document("E-KC", "CT-S2-ELEC", [{**_elec_record(1200, start="2025-01-01", end="2025-12-31"),
                                               "activity_quantity": (1200000, "kWh")}])
    store.add_document("E-STL", "CT-S2-ELEC", [_elec_record(800, plant="St Louis Plant", start="2025-01-01",
                                                            end="2025-12-31")])
    store.add_document("FLEET", "CT-S1-MOBFUEL", [_diesel_purchase(600), _diesel_purchase(400, "2025-09-01")])
    return store


def scenarios() -> dict[str, dict]:
    """Named recalculation responses: with and without company figures, a consolidated share, no regions."""

    kwargs: dict[str, dict[str, Any]] = {
        "plain": {"grid_regions": REGIONS, "vehicle_groups": [GROUP_ROAD]},
        "company": {"grid_regions": REGIONS, "vehicle_groups": [GROUP_ROAD],
                    "reported_activity": {GAS_KC: {"quantity": 650000, "unit": "therms"},
                                          ELEC_KC: {"quantity": 1000000, "unit": "kWh"}},
                    "reported_lines": {GAS_KC: 3400.0, ELEC_STL: 12.5}},
        "share": {"grid_regions": REGIONS, "vehicle_groups": [GROUP_ROAD], "consolidated_shares": {"fac-kc01": 60.0}},
        "no_regions": {},
    }
    return {name: run(mixed_store(), **kw) for name, kw in kwargs.items()}
