"""ZIP code -> eGRID subregion, from the EPA Power Profiler ZIP Code Tool (eGRID2023)."""

from __future__ import annotations

import json

import pytest

from backend.app.reference import egrid_zip
from backend.app.reference.emission_factor_loader import default_emission_factor_reference
from backend.scripts.build_egrid_zip_reference import DEFAULT_SOURCE, build


def test_committed_json_matches_a_fresh_build_from_the_epa_workbook() -> None:
    assert json.loads(egrid_zip.ZIP_PATH.read_text(encoding="utf-8")) == build(DEFAULT_SOURCE)


def test_every_subregion_has_hub_factors() -> None:
    hub = {r["egrid_subregion"] for r in default_emission_factor_reference().egrid_subregions()}
    found = {s for v in json.loads(egrid_zip.ZIP_PATH.read_text())["zips"].values() for s in v.split("|")}
    assert found <= hub and len(found) == 27


@pytest.mark.parametrize(
    ("zip_code", "subregions"),
    [
        ("12207", ["NYUP"]),  # Albany: the workbook's Facility A
        ("19103", ["RFCE"]),  # Philadelphia: the workbook's Facility B
        ("23234", ["SRVC"]),  # Richmond
        ("10501", ["NYCW", "NYUP"]),  # served by utilities in two subregions
        ("99999", []),
        ("1220", []),
        (None, []),
    ],
)
def test_subregions_for_zip(zip_code: str | None, subregions: list[str]) -> None:
    assert egrid_zip.subregions_for_zip(zip_code) == subregions


@pytest.mark.parametrize(
    ("address", "zip_code"),
    [
        ("15 State Street, Albany, NY 12207", "12207"),
        ("4100 Deepwater Terminal Rd, Richmond, VA 23234-1234", "23234"),
        ("12345 Main St, Austin TX 78701", "78701"),
        ("2200 Market Street, Philadelphia, PA 19103, USA", "19103"),
        ("12345 Main St", None),  # a street number, not a ZIP code
        ("12345 Main St, Dallas", None),
        ("Albany, NY", None),
        (None, None),
    ],
)
def test_zip_from_address(address: str | None, zip_code: str | None) -> None:
    assert egrid_zip.zip_from_address(address) == zip_code
