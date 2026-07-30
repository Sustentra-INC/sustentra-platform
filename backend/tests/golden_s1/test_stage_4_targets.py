from __future__ import annotations

from backend.app.services.extraction_target_service import ExtractionTargetService
from backend.tests.golden_s1.golden_s1_runner import REPO_ROOT


def test_current_seed_exposes_known_s1_target_sets() -> None:
    service = ExtractionTargetService(repo_root=REPO_ROOT)
    fuel_quantity_fields = {
        target["field_id"]
        for target in service.get_targets_for_canonical_type("CT-S1-FUELQTY")
    }
    mobile_fuel_fields = {
        target["field_id"]
        for target in service.get_targets_for_canonical_type("CT-S1-MOBFUEL")
    }

    assert {"facility_name", "activity_quantity", "activity_unit"}.issubset(fuel_quantity_fields)
    assert {"fuel_type", "activity_quantity", "activity_unit"}.issubset(mobile_fuel_fields)
