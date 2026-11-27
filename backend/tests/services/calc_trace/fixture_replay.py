"""The frontend's recorded recalculation responses (``frontend/features/s1/tests/fixtures/recalculation*.json``) run
again through today's engine.

Those files predate calculation lines, so they cannot be summed line by line as they are. Each is rebuilt here as the
reviewed evidence it was made from (every input of its stationary, mobile and electricity categories: the documents,
their quantities and units, the facility, the grid region, the certificates), recalculated, and compared with the
recorded category totals. The grid region of a facility the file does not name is the eGRID subregion whose CO2 rate
gives the recorded mass.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from backend.app.reference.emission_factor_loader import default_emission_factor_reference
from backend.app.services import emissions_calculator as calc
from backend.tests.services.test_engagement_recalculation_service import FakeStore, SetupFromStoreService, _own

FIXTURES = Path(__file__).parents[4] / "frontend" / "features" / "s1" / "tests" / "fixtures"
NAMES = sorted(p.name for p in FIXTURES.glob("recalculation*.json"))
FUELS = {"Natural Gas": "natural_gas", "Diesel Fuel": "diesel"}
FAMILIES = ("stationary_combustion", "mobile_combustion", "purchased_electricity_location_based",
            "purchased_electricity_market_based")


def load(name: str) -> dict[str, Any]:
    out: dict[str, Any] = json.loads((FIXTURES / name).read_text())
    return out


def _region(mwh: float, co2_t: float) -> str:
    ref = default_emission_factor_reference()
    rate = co2_t * calc.LB_PER_METRIC_TON / mwh
    for row in ref.egrid_subregions():
        if abs(ref.electricity(row["egrid_subregion"])["CO2"].value - rate) < 1e-6 * rate:
            return str(row["egrid_subregion"])
    raise LookupError(f"no eGRID subregion has {rate} lb CO2 per MWh")


def rebuild(recorded: dict[str, Any], scale: int = 1) -> tuple[FakeStore, dict[str, Any]]:
    """(the store, the engagement) that recalculate to ``recorded``'s fuel and electricity categories. ``scale``
    repeats every stationary and electricity document that many times (a larger engagement, for timing)."""

    store = FakeStore()
    categories = recorded.get("categories") or {}
    grid_regions: dict[str, str] = {}
    documents: dict[str, list[dict[str, tuple]]] = {}
    kinds: dict[str, str] = {}
    for family, kind in (("stationary_combustion", "CT-S1-FUELQTY"), ("mobile_combustion", "CT-S1-MOBFUEL")):
        for item in (categories.get(family) or {}).get("details", {}).get("inputs", []):
            for month, doc in enumerate(item["documents"], start=1):
                start = f"2025-{(month - 1) % 12 + 1:02d}-01"
                record: dict[str, tuple] = {"fuel_type": (FUELS[item["fuel"]], None),
                                            "activity_quantity": (doc["quantity"], doc["unit"]),
                                            "activity_unit": (doc["unit"], None)}
                if kind == "CT-S1-MOBFUEL":
                    record["transaction_date"] = (start, None)
                else:
                    record.update(service_period_start=(start, None), service_period_end=(start[:8] + "28", None))
                documents.setdefault(doc["document_id"], []).append(record)
                kinds[doc["document_id"]] = kind
    location = categories.get("purchased_electricity_location_based")
    if location:
        mass = {line["key"]: line["mass_t"]["CO2"] for line in location["lines"]}
        for item in location["details"]["inputs"]:
            facility = item["fuel"]
            grid_regions[facility] = item.get("grid_region") or _region(item["quantity"], mass[facility])
            for doc in item["documents"]:
                documents.setdefault(doc["document_id"], []).append({
                    "activity_quantity": (doc["quantity"], doc["unit"]), "activity_unit": (doc["unit"], None),
                    "energy_type": ("electricity", None), "facility_name": (facility, None),
                    "service_period_start": ("2025-01-01", None), "service_period_end": ("2025-12-31", None)})
                kinds[doc["document_id"]] = "CT-S2-ELEC"
    for copy in range(scale):
        for document_id, records in documents.items():
            if copy and kinds[document_id] == "CT-S1-MOBFUEL":  # the test service files each one on a line of its own
                continue
            store.add_document(document_id if copy == 0 else f"{document_id}-{copy}", kinds[document_id], records)
    market = categories.get("purchased_electricity_market_based") or {}
    covered = float((market.get("details") or {}).get("covered_mwh") or 0) * scale
    recalculation: dict[str, Any] = {"grid_regions": grid_regions}
    if covered:
        recalculation["certificates"] = [{"label": "Certificates", "mwh": covered}]
    engagement = {"id": "ENG-1", "reporting_period_start": "2025-01-01", "reporting_period_end": "2025-12-31",
                  "settings": {"recalculation": recalculation}}
    return store, engagement


def replay(name: str, scale: int = 1, **options: Any) -> dict[str, Any]:
    store, engagement = rebuild(load(name), scale)
    out: dict[str, Any] = SetupFromStoreService(store).recalculate(engagement, _own, None, **options)
    return out


def slug(name: str) -> str:
    return re.sub(r"\W+", "_", name.removesuffix(".json"))
