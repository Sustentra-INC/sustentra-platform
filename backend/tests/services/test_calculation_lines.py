"""Calculation lines and the Evidence tree: where documents are filed, how reviewers move them,
and a line's schedule. Built on the recalculation tests' FakeStore."""

from __future__ import annotations

from typing import Any

import pytest

from backend.app.api.engagements import SETTINGS_KEYS, EngagementUpdate
from backend.app.services import calculation_lines as cl
from backend.app.services.evidence_tree_service import EvidenceTreeService
from backend.tests.services.test_engagement_recalculation_service import ORG, FakeStore, _own

KC = {"facilityId": "fac-kc01", "name": "Kansas City Plant", "address": "100 Main Street, Kansas City, MO 64105"}
STL = {"facilityId": "fac-stl2", "name": "St Louis Plant", "address": "200 Oak Avenue, St Louis, MO 63101"}
GAS_KC = "s1:stationary:natural-gas:fac-kc01"
GAS_STL = "s1:stationary:natural-gas:fac-stl2"
ELEC_KC = "s2:purchased_energy:electricity:fac-kc01"
ELEC_STL = "s2:purchased_energy:electricity:fac-stl2"


def _engagement(**settings: Any) -> dict:
    settings.setdefault("facilities", [KC, STL])
    return {"id": "ENG-1", "reporting_period_start": "2025-01-01", "reporting_period_end": "2025-03-31",
            "settings": settings}


def _tree_service(store: FakeStore) -> EvidenceTreeService:
    return EvidenceTreeService(store, store, store)


def _gas(quantity: float = 100, start: str = "2025-01-01", end: str = "2025-01-31", plant: str = "Kansas City Plant",
         fuel: str = "natural_gas", **extra: Any) -> dict:
    return {"fuel_type": (fuel, None), "activity_quantity": (quantity, "MMBtu"), "activity_unit": ("MMBtu", None),
            "service_period_start": (start, None), "service_period_end": (end, None),
            "facility_name": (plant, None), **{k: (v, None) for k, v in extra.items()}}


def _elec(mwh: float, plant: str = "Kansas City Plant", start: str = "2025-01-01", end: str = "2025-01-31") -> dict:
    return {"activity_quantity": (mwh, "MWh"), "activity_unit": ("MWh", None), "energy_type": ("electricity", None),
            "facility_name": (plant, None), "service_period_start": (start, None), "service_period_end": (end, None)}


def _tree(store: FakeStore, decisions: dict | None = None, **settings: Any) -> dict:
    return _tree_service(store).tree(_engagement(**settings), _own, decisions)


def _lines_with_docs(tree: dict) -> dict[str, list[str]]:
    """line key -> document ids filed under it."""

    out: dict[str, list[str]] = {}
    for scope in tree["blocks"]["supporting"]["scopes"]:
        for category in scope["categories"]:
            for level2 in category["level2s"]:
                for line in level2["lines"]:
                    if line["documents"]:
                        out[line["line"]["key"]] = [d["document_id"] for d in line["documents"]]
    return out


# --- keys -----------------------------------------------------------------------------------
def test_line_key_format_and_slugs() -> None:
    key = cl.line_key("s1", "stationary", "Natural Gas", "facility", "FAC-KC01")
    assert key == "s1:stationary:natural-gas:fac-kc01"
    assert cl.LINE_KEY.match(key)
    assert cl.line_key("s2", "contractual", "Energy attribute certificates", "company", "anything") == \
        "s2:contractual:energy-attribute-certificates:company"
    assert cl.slug("Distillate Fuel Oil No. 2") == "distillate-fuel-oil-no-2"
    assert cl.slug("  ") == "none" and len(cl.slug("x" * 300)) == 60
    assert cl.CATEGORY_LABEL["biogenic"] == "Biogenic CO₂"


def test_summary_types_are_one_backend_list() -> None:
    assert set(cl.SUMMARY_TYPES.values()) >= {"Inventory workbook", "Organizational boundary statement",
                                              "Emission factor source list", "Facility list",
                                              "Prior-year inventory or report"}


# --- default placement of a record, by canonical type ---------------------------------------
def _place(canonical: str, record: dict, decision: dict | None = None, groups: list | None = None,
           choices: dict | None = None) -> cl.RecordPlacement:
    store = FakeStore()
    store.add_document("D1", canonical, [record])
    service = _tree_service(store)
    loaded = service.load(_engagement(recalculation={"vehicle_groups": groups or [], "fuel_choices": choices or {}}),
                          _own, {"D1": decision} if decision else None)
    assert len(loaded.docs) == 1
    from backend.app.services.engagement_recalculation_service import parse_inputs

    inputs = parse_inputs({"recalculation": {"vehicle_groups": groups or [], "fuel_choices": choices or {}}})
    return cl.place_record(loaded.docs[0].records[0], ref=service.reference, facilities=[KC, STL],
                           decisions={"D1": decision} if decision else {}, vehicle_groups=inputs.vehicle_groups,
                           fuel_choices=inputs.fuel_choices)


def test_stationary_goes_to_its_fuel_and_matched_facility() -> None:
    placement = _place("CT-S1-FUELQTY", _gas())
    assert placement.line_key == GAS_KC
    assert (placement.level2_label, placement.anchor_kind) == ("Natural Gas", "facility")


def test_facility_decision_wins_over_the_name_match() -> None:
    assert _place("CT-S1-FUELQTY", _gas(), decision={"facilityId": "fac-stl2"}).line_key == GAS_STL


def test_unknown_facility_or_fuel_has_no_line() -> None:
    assert _place("CT-S1-FUELQTY", _gas(plant="Somewhere Else")).line_key is None
    ambiguous = _place("CT-S1-FUELQTY", _gas(fuel="fuel_oil"))  # reviewer has not chosen the EPA fuel
    assert ambiguous.category == "stationary" and ambiguous.level2 is None and ambiguous.line_key is None


def test_fuel_choices_resolve_an_ambiguous_fuel() -> None:
    placement = _place("CT-S1-FUELQTY", _gas(fuel="fuel_oil"),
                       choices={"stationary:fuel_oil": "Residual Fuel Oil No. 6"})
    assert placement.line_key == "s1:stationary:residual-fuel-oil-no-6:fac-kc01"


def test_biomass_fuel_goes_under_biogenic() -> None:
    placement = _place("CT-S1-FUELQTY", _gas(fuel="Bagasse"))
    assert placement.category == "biogenic"
    assert placement.line_key == "biogenic:biogenic:bagasse:fac-kc01"


def _mobile(fuel: str = "diesel") -> dict:
    return {"fuel_type": (fuel, None), "activity_quantity": (50, "gal"), "activity_unit": ("gal", None),
            "transaction_date": ("2025-02-03", None), "facility_name": ("Kansas City Plant", None)}


def _group(fuel: str, label: str) -> dict:
    return {"fuel": fuel, "vehicle_type": "Medium- and Heavy-Duty Vehicles", "factor_fuel_type": "Diesel",
            "on_road": True, "label": label}


def test_mobile_takes_the_vehicle_group_only_when_exactly_one_uses_the_fuel() -> None:
    one = [_group("Diesel Fuel", "Delivery trucks"), _group("Motor Gasoline", "Pickups")]
    assert _place("CT-S1-MOBFUEL", _mobile(), groups=one).line_key == "s1:mobile:diesel-fuel:vg-delivery-trucks"
    two = [_group("Diesel Fuel", "Delivery trucks"), _group("Diesel Fuel", "Yard equipment")]
    placement = _place("CT-S1-MOBFUEL", _mobile(), groups=two)
    assert (placement.category, placement.level2, placement.line_key) == ("mobile", "diesel-fuel", None)
    assert _place("CT-S1-MOBFUEL", _mobile()).line_key is None  # no vehicle groups set up


def test_electricity_thermal_and_refrigerant_placements() -> None:
    assert _place("CT-S2-ELEC", _elec(10)).line_key == ELEC_KC
    thermal = {"activity_quantity": (5, "MMBtu"), "energy_type": ("Chilled water", None),
               "facility_name": ("St Louis Plant", None)}
    assert _place("CT-S2-THERMAL", thermal).line_key == "s2:purchased_energy:cooling:fac-stl2"
    assert _place("CT-S2-THERMAL", {**thermal, "energy_type": ("hot water", None)}).level2 == "heating"
    assert _place("CT-S2-THERMAL", {**thermal, "energy_type": ("steam", None)}).level2 == "steam"
    assert _place("CT-S2-THERMAL", {**thermal, "energy_type": ("plasma", None)}).line_key is None
    refrigerant = {"refrigerant_type": ("R-410A", None), "refrigerant_added": (4, "lb"),
                   "service_date": ("2025-02-01", None), "facility_name": ("Kansas City Plant", None)}
    assert _place("CT-S1-REFRSVC", refrigerant).line_key == "s1:fugitive:r-410a:fac-kc01"
    assert _place("CT-S1-REFRSVC", {**refrigerant, "refrigerant_type": ("", None)}).line_key is None


# --- blocks ---------------------------------------------------------------------------------
def test_summary_and_unassigned_blocks() -> None:
    store = FakeStore()
    store.add_document("WB", "CT-GHG-WORKBOOK", [{"reported_total": (500, "t")}])
    store.add_document("FACLIST", "CT-GHG-FACSRCLIST", [{"facility_name": ("Kansas City Plant", None)}])
    store.add_document("READING", "CT-S1-FUELQTY", [_gas()])
    store.documents.append({"document_id": "NEW", "engagement_id": "ENG-1", "org_id": ORG, "file_name": "scan.pdf",
                            "processing_status": "in_progress"})
    store.documents.append({"document_id": "BAD", "engagement_id": "ENG-1", "org_id": ORG, "file_name": "bad.pdf",
                            "processing_status": "failed"})
    tree = _tree(store)
    blocks = tree["blocks"]
    assert [d["document_id"] for d in blocks["summary"]] == ["FACLIST", "WB"]
    assert {d["document_id"]: d["processing_status"] for d in blocks["unassigned"]} == {
        "NEW": "in_progress", "BAD": "failed"}
    assert all(d["detected_type"] is None for d in blocks["unassigned"])
    assert blocks["summary"][1]["detected_type"] == "Inventory workbook"
    assert _lines_with_docs(tree) == {GAS_KC: ["READING"]}


def test_a_record_with_a_category_but_no_anchor_is_unassigned_supporting_evidence() -> None:
    store = FakeStore()
    store.add_document("ODD", "CT-S1-FUELQTY", [_gas(plant="Unknown Site")])
    store.add_document("PROC", "CT-S1-PROCACT", [{"production_quantity": (9, "t")}])
    tree = _tree(store)
    assert {d["document_id"] for d in tree["blocks"]["supporting"]["unassigned"]} == {"ODD", "PROC"}
    assert _lines_with_docs(tree) == {}


def test_withdrawn_duplicate_and_superseded_documents_are_set_aside_not_filed() -> None:
    store = FakeStore()
    for name in ("KEEP", "WITHDRAWN", "DUP", "OLD"):
        store.add_document(name, "CT-S1-FUELQTY", [_gas()])
    decisions = {"WITHDRAWN": {"disposition": "withdrawn"},
                 "DUP": {"relationships": [{"kind": "duplicate", "otherDocumentId": "KEEP"}]},
                 "KEEP": {"relationships": [{"kind": "supersedes", "otherDocumentId": "OLD"}]}}
    tree = _tree(store, decisions)
    assert _lines_with_docs(tree) == {GAS_KC: ["KEEP"]}
    assert {(d["document_id"], d["reason"]) for d in tree["set_aside"]} == {
        ("WITHDRAWN", "withdrawn"), ("DUP", "duplicate"), ("OLD", "superseded")}


# --- a document whose records map to several lines ---------------------------------------------
def test_a_multi_line_document_appears_under_each_line_with_only_that_lines_records() -> None:
    store = FakeStore()
    store.add_document("BILL", "CT-S2-ELEC", [_elec(10, "Kansas City Plant"), _elec(20, "St Louis Plant"),
                                              _elec(30, "St Louis Plant")])
    tree = _tree(store)
    assert _lines_with_docs(tree) == {ELEC_KC: ["BILL"], ELEC_STL: ["BILL"]}
    rows = {}
    for scope in tree["blocks"]["supporting"]["scopes"]:
        for category in scope["categories"]:
            for level2 in category["level2s"]:
                for line in level2["lines"]:
                    for row in line["documents"]:
                        rows[line["line"]["key"]] = row
    assert rows[ELEC_KC]["values"] == 6 and rows[ELEC_STL]["values"] == 12  # 6 fields per record
    assert rows[ELEC_KC]["also_in"] == [ELEC_STL] and rows[ELEC_STL]["also_in"] == [ELEC_KC]
    assert rows[ELEC_KC]["facility_name"] == "Kansas City Plant" and rows[ELEC_KC]["facility_id"] == "fac-kc01"
    assert (rows[ELEC_KC]["period_start"], rows[ELEC_KC]["period_end"]) == ("2025-01-01", "2025-01-31")


# --- the tree's shape and counts ---------------------------------------------------------------
def test_tree_levels_counts_and_pre_created_facility_lines() -> None:
    store = FakeStore()
    store.add_document("G1", "CT-S1-FUELQTY", [_gas()])  # all 6 fields accepted
    store.add_document("G2", "CT-S1-FUELQTY", [_gas(plant="St Louis Plant")], decision=None)
    tree = _tree(store)
    scopes = {s["scope"]: s for s in tree["blocks"]["supporting"]["scopes"]}
    assert list(scopes) == ["s1", "s2", "biogenic"]
    assert [c["category"] for c in scopes["s1"]["categories"]] == ["stationary", "mobile", "fugitive", "process"]
    assert [c["category"] for c in scopes["s2"]["categories"]] == ["purchased_energy", "contractual"]
    assert [c["label"] for c in scopes["biogenic"]["categories"]] == ["Biogenic CO₂"]
    stationary = scopes["s1"]["categories"][0]
    assert [level2["level2"] for level2 in stationary["level2s"]] == ["natural-gas"]
    gas = stationary["level2s"][0]
    # one line per Setup facility is pre-created for a level 2 that has a record
    assert [ln["line"]["key"] for ln in gas["lines"]] == [GAS_KC, GAS_STL]
    assert all(ln["line"]["created_by_user"] is False for ln in gas["lines"])
    assert gas["counts"] == {"documents": 2, "values": 12, "accepted": 6, "to_review": 6, "issues": 0,
                             "pct_accepted": 50.0}
    assert stationary["counts"] == gas["counts"]
    assert scopes["s2"]["categories"][0]["level2s"] == []
    assert [f["facility_id"] for f in tree["facilities"]] == ["fac-kc01", "fac-stl2"]
    assert {line["key"] for line in tree["lines"]} == {GAS_KC, GAS_STL}


def test_default_lines_per_vehicle_group_and_user_lines_are_marked() -> None:
    store = FakeStore()
    store.add_document("M1", "CT-S1-MOBFUEL", [_mobile()])
    mine = {"category": "stationary", "level2_label": "Propane", "anchor_kind": "facility", "anchor_id": "fac-kc01",
            "label": "Propane at the Kansas City Plant"}
    groups = [_group("Diesel Fuel", "Delivery trucks"), _group("Diesel Fuel", "Yard equipment"),
              _group("Motor Gasoline", "Pickups")]
    tree = _tree(store, recalculation={"vehicle_groups": groups},
                 evidenceLines=cl.normalize_evidence_lines([mine]))
    by_key = {line["key"]: line for line in tree["lines"]}
    assert set(by_key) == {"s1:mobile:diesel-fuel:vg-delivery-trucks", "s1:mobile:diesel-fuel:vg-yard-equipment",
                           "s1:stationary:propane:fac-kc01"}
    assert by_key["s1:stationary:propane:fac-kc01"]["created_by_user"] is True
    assert by_key["s1:mobile:diesel-fuel:vg-yard-equipment"]["created_by_user"] is False
    # two diesel groups: the record has no anchor
    assert [d["document_id"] for d in tree["blocks"]["supporting"]["unassigned"]] == ["M1"]


def test_a_reviewers_line_that_duplicates_a_system_line_is_the_system_line() -> None:
    store = FakeStore()
    store.add_document("G1", "CT-S1-FUELQTY", [_gas()])
    duplicate = cl.normalize_evidence_lines([{"category": "stationary", "level2_label": "Natural Gas",
                                              "anchor_kind": "facility", "anchor_id": "fac-kc01",
                                              "label": "My gas line"}])
    tree = _tree(store, evidenceLines=duplicate)
    line = next(ln for ln in tree["lines"] if ln["key"] == GAS_KC)
    assert line["created_by_user"] is False and line["label"] != "My gas line"
    assert _tree_service(store).system_line_keys(_engagement(), _own) == {GAS_KC, GAS_STL}


# --- the reviewer's moves ----------------------------------------------------------------------
def _gas_store() -> FakeStore:
    store = FakeStore()
    store.add_document("G1", "CT-S1-FUELQTY", [_gas()])
    store.add_document("WB", "CT-GHG-WORKBOOK", [{"reported_total": (500, "t")}])
    store.add_document("UNREAD", "CT-S1-FUELQTY", [_gas(plant="Unknown")])
    return store


def test_move_a_document_to_another_line() -> None:
    decisions = {"G1": {"documentId": "G1", "facilityId": "fac-kc01", "note": "kept",
                        "placements": [{"from": GAS_KC, "to": GAS_STL}]}}
    tree = _tree(_gas_store(), decisions)
    assert _lines_with_docs(tree)[GAS_STL] == ["G1"] and GAS_KC not in _lines_with_docs(tree)


def test_a_chain_of_moves_applies_in_order() -> None:
    moves = [{"from": GAS_KC, "to": GAS_STL}, {"from": GAS_STL, "to": cl.BLOCK_UNASSIGNED},
             {"from": cl.BLOCK_UNASSIGNED, "to": GAS_KC}]
    assert _lines_with_docs(_tree(_gas_store(), {"G1": {"placements": moves}})) == {GAS_KC: ["G1"]}
    stale = [{"from": GAS_STL, "to": GAS_KC}, {"from": GAS_KC, "to": GAS_KC}, "junk", {"to": GAS_STL}]
    assert _lines_with_docs(_tree(_gas_store(), {"G1": {"placements": stale}})) == {GAS_KC: ["G1"]}


def test_move_to_and_from_the_blocks() -> None:
    decisions = {"G1": {"placements": [{"from": GAS_KC, "to": cl.BLOCK_SUMMARY}]},
                 "WB": {"placements": [{"from": cl.BLOCK_SUMMARY, "to": GAS_STL}]},
                 "UNREAD": {"placements": [{"from": cl.SUPPORTING_UNASSIGNED, "to": cl.BLOCK_UNASSIGNED}]}}
    tree = _tree(_gas_store(), decisions)
    assert [d["document_id"] for d in tree["blocks"]["summary"]] == ["G1"]
    assert [d["document_id"] for d in tree["blocks"]["unassigned"]] == ["UNREAD"]
    assert _lines_with_docs(tree) == {GAS_STL: ["WB"]}
    assert tree["blocks"]["supporting"]["unassigned"] == []


def test_a_move_to_a_line_that_does_not_exist_lands_in_unassigned_supporting_evidence_flagged() -> None:
    gone = "s1:stationary:propane:fac-kc01"  # never created, or deleted after the move
    tree = _tree(_gas_store(), {"G1": {"placements": [{"from": GAS_KC, "to": gone}]}})
    row = next(d for d in tree["blocks"]["supporting"]["unassigned"] if d["document_id"] == "G1")
    assert row["flags"] == ["unknown_line"] and row["values"] == 6
    # ...and the document comes back to the line when the line exists
    mine = cl.normalize_evidence_lines([{"category": "stationary", "level2_label": "Propane", "anchor_kind": "facility",
                                         "anchor_id": "fac-kc01", "label": "Propane at KC"}])
    tree = _tree(_gas_store(), {"G1": {"placements": [{"from": GAS_KC, "to": gone}]}}, evidenceLines=mine)
    assert _lines_with_docs(tree)[gone] == ["G1"]


def test_moves_keep_the_other_payload_keys_out_of_placement_logic() -> None:
    slots = cl.apply_placements([cl.Slot(GAS_KC, {0, 1})], [{"from": GAS_KC, "to": GAS_STL}])
    assert [(s.target, s.records) for s in slots] == [(GAS_STL, {0, 1})]
    both = cl.apply_placements([cl.Slot(GAS_KC, {0}), cl.Slot(GAS_STL, {1})], [{"from": GAS_KC, "to": GAS_STL}])
    assert [(s.target, s.records) for s in both] == [(GAS_STL, {0, 1})]
    assert cl.apply_placements([cl.Slot(GAS_KC, {0})], "not a list")[0].target == GAS_KC


# --- settings["evidenceLines"] -----------------------------------------------------------------
def _line(**changes: Any) -> dict:
    return {"category": "stationary", "level2_label": "Propane", "anchor_kind": "facility", "anchor_id": "fac-kc01",
            "label": "Propane at KC", **changes}


def test_evidence_lines_are_an_allowed_setting_and_the_server_fills_in_the_key() -> None:
    assert "evidenceLines" in SETTINGS_KEYS
    update = EngagementUpdate(settings={"evidenceLines": [_line()]})
    assert update.settings is not None
    saved = update.settings["evidenceLines"][0]
    assert saved["key"] == "s1:stationary:propane:fac-kc01" and saved["scope"] == "s1" and saved["level2"] == "propane"
    # the saved form round-trips
    assert EngagementUpdate(settings={"evidenceLines": [saved]}).settings == {"evidenceLines": [saved]}
    company = EngagementUpdate(settings={"evidenceLines": [
        _line(category="contractual", level2_label="PPAs", anchor_kind="company", anchor_id=None)]}).settings
    assert company is not None and company["evidenceLines"][0]["key"] == "s2:contractual:ppas:company"


@pytest.mark.parametrize("bad", [
    _line(key="s1:stationary:propane:somewhere-else"),
    _line(category="scope3"),
    _line(scope="s2"),
    _line(anchor_kind="region"),
    _line(label="x" * 121),
    _line(level2_label="y" * 121),
    _line(label="  "),
    _line(anchor_id=None),
    _line(extra="field"),
])
def test_evidence_lines_reject_bad_entries(bad: dict) -> None:
    with pytest.raises(ValueError):
        EngagementUpdate(settings={"evidenceLines": [bad]})


def test_evidence_lines_limits_and_duplicates() -> None:
    with pytest.raises(ValueError):
        EngagementUpdate(settings={"evidenceLines": "nope"})
    with pytest.raises(ValueError):
        EngagementUpdate(settings={"evidenceLines": [_line(), _line()]})
    many = [_line(level2_label=f"Fuel {i}") for i in range(201)]
    with pytest.raises(ValueError):
        EngagementUpdate(settings={"evidenceLines": many})
    assert len(EngagementUpdate(settings={"evidenceLines": many[:200]}).settings["evidenceLines"]) == 200  # type: ignore[index]


@pytest.mark.asyncio
async def test_settings_may_not_add_a_system_line(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import HTTPException

    from backend.app.api import engagements as engagements_api
    from backend.app.api import evidence_tree as tree_api
    from backend.tests.api.conftest import make_user

    store = FakeStore()
    store.add_document("G1", "CT-S1-FUELQTY", [_gas()], org_id=str(make_user().org_id))
    monkeypatch.setattr(tree_api, "_service", lambda: _tree_service(store))

    async def none(db, engagement):  # noqa: ANN001, ANN202
        return {}

    monkeypatch.setattr(tree_api, "document_decisions", none)
    current = {"id": "ENG-1", "reporting_period_start": None, "reporting_period_end": None,
               "settings": {"facilities": [KC]}}
    system = cl.normalize_evidence_lines([_line(level2_label="Natural Gas")])
    with pytest.raises(HTTPException) as caught:
        await engagements_api._reject_system_lines(None, current, {"facilities": [KC], "evidenceLines": system},  # type: ignore[arg-type]
                                                   make_user())
    assert caught.value.status_code == 422 and "already creates" in caught.value.detail
    own = cl.normalize_evidence_lines([_line()])  # propane: no documents, so not a system line
    await engagements_api._reject_system_lines(None, current, {"facilities": [KC], "evidenceLines": own},  # type: ignore[arg-type]
                                               make_user())
    # a line that was already stored is not re-judged when other settings are saved
    stored = {**current, "settings": {"facilities": [KC], "evidenceLines": system}}
    await engagements_api._reject_system_lines(None, stored, {"facilities": [KC], "evidenceLines": system},  # type: ignore[arg-type]
                                               make_user())
    await engagements_api._reject_system_lines(None, current, {"facilities": [KC]}, make_user())  # type: ignore[arg-type]


# --- a line's schedule -------------------------------------------------------------------------
def _schedule_store() -> FakeStore:
    store = FakeStore()
    # A 31-day bill spanning two months: Jan 16 to Feb 15 (16 days in January, 15 in February).
    store.add_document("BILL-A", "CT-S1-FUELQTY", [_gas(310, "2025-01-16", "2025-02-15", account_number="ACC-9",
                                                         service_address="100 Main Street, Kansas City, MO")])
    # The next bill is read but not reviewed.
    store.add_document("BILL-B", "CT-S1-FUELQTY", [_gas(280, "2025-02-16", "2025-03-15", account_number="ACC-9")],
                       decision=None)
    # A full accepted January bill from another account.
    store.add_document("BILL-C", "CT-S1-FUELQTY", [_gas(155, "2025-01-01", "2025-01-15", account_number="ACC-7")])
    return store


def test_schedule_coverage_for_a_bill_spanning_two_months() -> None:
    schedule = _tree_service(_schedule_store()).schedule(_engagement(), _own, GAS_KC)
    assert schedule is not None
    assert schedule["reporting_period"] == {"start": "2025-01-01", "end": "2025-03-31"}
    months = {m["month"]: m for m in schedule["coverage"]}
    assert list(months) == ["2025-01", "2025-02", "2025-03"]
    # January: BILL-C covers 1-15 and BILL-A covers 16-31: all 31 days
    assert months["2025-01"]["status"] == "counted"
    assert months["2025-01"]["quantity"] == pytest.approx(155 + 310 * 16 / 31, abs=1e-3)
    assert months["2025-01"]["unit"] == "MMBtu" and sorted(months["2025-01"]["document_ids"]) == ["BILL-A", "BILL-C"]
    # February: BILL-A covers 15 of 28 days; BILL-B (unreviewed) covers the rest
    assert months["2025-02"]["status"] == "counted_in_part"
    assert months["2025-02"]["quantity"] == pytest.approx(310 * 15 / 31, abs=1e-3)
    # March: only the unreviewed bill covers it
    assert months["2025-03"] == {"month": "2025-03", "status": "not_reviewed", "quantity": None, "unit": None,
                                 "document_ids": ["BILL-B"], "flags": [], "waiting_on": []}


def test_schedule_marks_months_with_no_document() -> None:
    store = FakeStore()
    store.add_document("BILL-A", "CT-S1-FUELQTY", [_gas(310, "2025-01-16", "2025-02-15")])
    months = {m["month"]: m["status"] for m in
              _tree_service(store).schedule(_engagement(), _own, GAS_KC)["coverage"]}  # type: ignore[index]
    assert months == {"2025-01": "counted_in_part", "2025-02": "counted_in_part", "2025-03": "no_document"}


def test_schedule_identifiers_count_documents() -> None:
    schedule = _tree_service(_schedule_store()).schedule(_engagement(), _own, GAS_KC)
    assert schedule is not None
    identifiers = {(i["label"], i["value"]): (i["documents_with"], i["documents_total"])
                   for i in schedule["identifiers"]}
    assert identifiers == {("Facility", "Kansas City Plant"): (3, 3),
                           ("Service address", "100 Main Street, Kansas City, MO"): (1, 3),
                           ("Account number", "ACC-9"): (2, 3), ("Account number", "ACC-7"): (1, 3)}  # no meter field


def test_schedule_values_and_history_newest_first_with_names() -> None:
    store = _schedule_store()
    store.reviews["BILL-A"] = [{**r, "reviewer_id": "Ana@Example.com", "reviewed_at": "2025-04-02T10:00:00Z"}
                               for r in store.reviews["BILL-A"]]
    store.reviews["BILL-C"] = [
        {**r, "reviewer_id": "bo@example.com", "reviewed_at": "2025-04-03T09:30:00Z",
         **({"decision": "edited", "reviewed_value": 150} if r["candidate_id"].endswith("activity_quantity") else {})}
        for r in store.reviews["BILL-C"]]
    store.results["BILL-A"][0]["created_at"] = "2025-04-01T08:00:00Z"
    store.results["BILL-C"][0]["created_at"] = "2025-04-01T08:05:00Z"
    names = {"ana@example.com": "Ana Reyes"}
    schedule = _tree_service(store).schedule(_engagement(), _own, GAS_KC,
                                             name_of=lambda login: names.get(login.lower(), login))
    assert schedule is not None
    values = {v["document_id"]: v for v in schedule["values"]}
    assert [v["document_id"] for v in schedule["values"]] == ["BILL-C", "BILL-A", "BILL-B"]  # by service period
    assert values["BILL-A"] | {"candidate_id": None} == {
        "service_period_start": "2025-01-16", "service_period_end": "2025-02-15", "days": 31, "quantity": 310,
        "unit": "MMBtu", "document_id": "BILL-A", "file_name": "BILL-A.pdf", "page": 1, "candidate_id": None,
        "decided_by": "Ana Reyes", "decided_at": "2025-04-02T10:00:00Z", "decision": "accepted", "waiting_on": [],
        "rejected_fields": []}
    assert values["BILL-A"]["candidate_id"] == "BILL-A:1:activity_quantity"
    assert values["BILL-C"]["quantity"] == 150 and values["BILL-C"]["decision"] == "edited"
    assert values["BILL-C"]["decided_by"] == "bo@example.com"  # no name on file: the login
    assert values["BILL-B"]["decision"] == "not_reviewed" and values["BILL-B"]["decided_by"] is None
    assert schedule["history"] == [
        {"at": "2025-04-03T09:30:00Z", "text": "bo@example.com edited 150 MMBtu from BILL-C.pdf, page 1"},
        {"at": "2025-04-02T10:00:00Z", "text": "Ana Reyes accepted 310 MMBtu from BILL-A.pdf, page 1"},
        {"at": "2025-04-01T08:05:00Z", "text": "System extracted 3 values from 3 documents"},
    ]


def test_schedule_of_a_line_with_no_documents_and_of_an_unknown_line() -> None:
    mine = cl.normalize_evidence_lines([_line()])
    service = _tree_service(FakeStore())
    empty = service.schedule(_engagement(evidenceLines=mine), _own, "s1:stationary:propane:fac-kc01")
    assert empty is not None and empty["values"] == [] and empty["history"] == [] and empty["identifiers"] == []
    assert [m["status"] for m in empty["coverage"]] == ["no_document"] * 3
    assert empty["line"]["created_by_user"] is True
    assert service.schedule(_engagement(), _own, "s1:stationary:nothing:fac-kc01") is None


def test_coverage_without_a_reporting_period_spans_the_values() -> None:
    from datetime import date

    values = [cl.Covered(date(2025, 11, 20), date(2025, 12, 10), 21.0, "gal", True, "D1")]
    months = cl.month_coverage((None, None), values)
    assert [(m["month"], m["status"]) for m in months] == [("2025-11", "counted_in_part"),
                                                          ("2025-12", "counted_in_part")]
    assert cl.month_coverage((None, None), []) == []
    # undated or reversed values never count
    assert cl.month_coverage((date(2025, 1, 1), date(2025, 1, 31)),
                             [cl.Covered(None, None, 5.0, "gal", True, "D2"),
                              cl.Covered(date(2025, 1, 9), date(2025, 1, 2), 5.0, "gal", True, "D3")])[0][
        "status"] == "no_document"


# --- fix round 1 --------------------------------------------------------------------------------
def _rows(tree: dict, target: str) -> list[dict]:
    blocks = tree["blocks"]
    if target == cl.SUPPORTING_UNASSIGNED:
        return blocks["supporting"]["unassigned"]
    return [d for scope in blocks["supporting"]["scopes"] for c in scope["categories"] for lv in c["level2s"]
            for ln in lv["lines"] if ln["line"]["key"] == target for d in ln["documents"]]


def test_a_document_moved_to_a_deleted_line_can_be_moved_back_out() -> None:
    gone = "s1:stationary:propane:fac-kc01"
    moves = [{"from": GAS_KC, "to": gone}]
    tree = _tree(_gas_store(), {"G1": {"placements": moves}})
    row = next(d for d in tree["blocks"]["supporting"]["unassigned"] if d["document_id"] == "G1")
    assert row["flags"] == ["unknown_line"] and row["placement_from"] == cl.SUPPORTING_UNASSIGNED
    moves.append({"from": row["placement_from"], "to": GAS_STL})  # what the UI sends next
    tree = _tree(_gas_store(), {"G1": {"placements": moves}})
    assert _lines_with_docs(tree)[GAS_STL] == ["G1"]
    assert "G1" not in [d["document_id"] for d in tree["blocks"]["supporting"]["unassigned"]]
    assert _rows(tree, GAS_STL)[0]["placement_from"] == GAS_STL and _rows(tree, GAS_STL)[0]["flags"] == []


def test_a_document_with_a_real_unassigned_placement_and_an_unknown_line_placement() -> None:
    store = FakeStore()
    store.add_document("MIX", "CT-S1-FUELQTY", [_gas(), _gas(plant="Unknown Site")])
    gone = "s1:stationary:propane:fac-kc01"
    moves: list[dict] = [{"from": GAS_KC, "to": gone}]
    tree = _tree(store, {"MIX": {"placements": moves}})
    rows = tree["blocks"]["supporting"]["unassigned"]
    assert [(r["document_id"], r["values"], r["flags"], r["placement_from"]) for r in rows] == [
        ("MIX", 12, ["unknown_line"], cl.SUPPORTING_UNASSIGNED)]  # one row: both records
    moves.append({"from": cl.SUPPORTING_UNASSIGNED, "to": GAS_STL})
    tree = _tree(store, {"MIX": {"placements": moves}})
    assert tree["blocks"]["supporting"]["unassigned"] == []
    assert _rows(tree, GAS_STL)[0]["values"] == 12


def test_file_documents_is_the_one_pure_filing_function() -> None:
    kc = cl.RecordPlacement("stationary", "natural-gas", "Natural Gas", "facility", "fac-kc01")
    nothing = cl.RecordPlacement("stationary")
    filed = cl.file_documents(
        [("A", "CT-S1-FUELQTY", [kc, nothing]), ("B", None, []), ("C", "CT-GHG-WORKBOOK", [])],
        {"A": {"placements": [{"from": GAS_KC, "to": "s1:stationary:coal:fac-x"}]}}, {GAS_KC})
    assert [(s.target, sorted(s.records), s.flags) for s in filed["A"]] == [
        (cl.SUPPORTING_UNASSIGNED, [0, 1], ["unknown_line"])]
    assert [s.target for s in filed["B"]] == [cl.BLOCK_UNASSIGNED] and [s.target for s in filed["C"]] == [cl.BLOCK_SUMMARY]


def test_recalculation_service_and_evidence_modules_have_no_import_cycle() -> None:
    import subprocess
    import sys

    code = "import backend.app.services.calculation_lines as c, sys; " \
           "assert 'backend.app.services.engagement_recalculation_service' not in sys.modules"
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0


def test_stored_lines_skip_only_the_invalid_entry() -> None:
    good = {"category": "stationary", "level2_label": "Propane", "anchor_kind": "facility", "anchor_id": "fac-kc01",
            "label": "Propane at KC"}
    lines = cl.user_lines({"evidenceLines": [{"category": "nonsense"}, good, "junk", dict(good)]})
    assert [ln.key for ln in lines] == ["s1:stationary:propane:fac-kc01"]
    assert cl.user_lines({"evidenceLines": "nope"}) == [] and cl.user_lines(None) == []


def test_placement_follows_the_reviewed_fuel_not_the_extracted_one() -> None:
    store = FakeStore()
    store.add_document("G1", "CT-S1-FUELQTY", [_gas(fuel="natural_gas")])
    store.reviews["G1"] = [{**r, "decision": "edited", "reviewed_value": "kerosene"}
                           if r["candidate_id"].endswith("fuel_type") else r for r in store.reviews["G1"]]
    tree = _tree(store)
    assert _lines_with_docs(tree) == {"s1:stationary:kerosene:fac-kc01": ["G1"]}


def test_a_field_without_a_candidate_id_has_none_not_the_text_none() -> None:
    from backend.app.services.reviewed_evidence import group_reviewed_records

    items = [{"field_name": "fuel_type", "normalized_value": "x", "unit": None, "record_index": None}]
    record = group_reviewed_records({"document_id": "D"}, "CT-S1-FUELQTY", items, {})[0]
    assert record.fields["fuel_type"].candidate_id is None


def test_coverage_clips_to_the_reporting_period() -> None:
    from datetime import date

    value = cl.Covered(date(2025, 1, 10), date(2025, 2, 5), 27.0, "gal", True, "D1")
    months = cl.month_coverage((date(2025, 1, 10), date(2025, 2, 5)), [value])
    assert [(m["month"], m["status"]) for m in months] == [("2025-01", "counted"), ("2025-02", "counted")]
    assert sum(m["quantity"] for m in months) == pytest.approx(27.0)


def test_a_value_in_a_unit_that_cannot_be_added_is_not_counted_in_full() -> None:
    from datetime import date

    values = [cl.Covered(date(2025, 1, 1), date(2025, 1, 31), 10.0, "gal", True, "D1"),
              cl.Covered(date(2025, 1, 1), date(2025, 1, 31), 5.0, "MWh", True, "D2")]
    month = cl.month_coverage((date(2025, 1, 1), date(2025, 1, 31)), values)[0]
    assert (month["status"], month["flags"], month["quantity"], month["unit"]) == (
        "counted_in_part", ["unconverted"], 10.0, "gal")
    assert month["document_ids"] == ["D1", "D2"]


def test_a_counted_month_with_no_numeric_quantity_reports_null() -> None:
    from datetime import date

    month = cl.month_coverage((date(2025, 1, 1), date(2025, 1, 31)),
                              [cl.Covered(date(2025, 1, 1), date(2025, 1, 31), None, None, True, "D1")])[0]
    assert (month["status"], month["quantity"], month["unit"], month["flags"]) == ("counted", None, None, [])


def test_history_lists_every_decision_on_a_value() -> None:
    store = FakeStore()
    store.add_document("BILL-A", "CT-S1-FUELQTY", [_gas(310, "2025-01-16", "2025-02-15")], decision=None)
    qty = "BILL-A:1:activity_quantity"
    store.reviews["BILL-A"] = [
        {"candidate_id": qty, "decision": "accepted", "org_id": ORG, "reviewed_value": 310, "reviewed_unit": "MMBtu",
         "reviewer_id": "ana@example.com", "reviewed_at": "2025-04-01T10:00:00Z"},
        {"candidate_id": qty, "decision": "edited", "org_id": ORG, "reviewed_value": 300, "reviewed_unit": "MMBtu",
         "reviewer_id": "bo@example.com", "reviewed_at": "2025-04-02T10:00:00Z"},
        {"candidate_id": "BILL-A:1:fuel_type", "decision": "accepted", "org_id": ORG, "reviewed_value": "natural_gas"},
    ]
    schedule = _tree_service(store).schedule(_engagement(), _own, GAS_KC)
    assert schedule is not None
    assert [h["text"] for h in schedule["history"][:2]] == [
        "bo@example.com edited 300 MMBtu from BILL-A.pdf, page 1",
        "ana@example.com accepted 310 MMBtu from BILL-A.pdf, page 1"]
    assert schedule["values"][0]["decision"] == "edited" and schedule["values"][0]["quantity"] == 300


def test_tree_lists_vehicle_groups_with_the_anchor_ids_lines_use() -> None:
    groups = [_group("Diesel Fuel", "Delivery trucks"), _group("Diesel Fuel", "Delivery trucks"),
              _group("Motor Gasoline", "Pickups")]
    tree = _tree(FakeStore(), recalculation={"vehicle_groups": groups})
    assert tree["vehicle_groups"] == [
        {"anchor_id": "vg-delivery-trucks", "label": "Delivery trucks", "fuel": "Diesel Fuel"},
        {"anchor_id": "vg-delivery-trucks-2", "label": "Delivery trucks", "fuel": "Diesel Fuel"},
        {"anchor_id": "vg-pickups", "label": "Pickups", "fuel": "Motor Gasoline"}]
    assert tree["anchors_for_contractual"] == "company"
    # a client builds a mobile line from them and the server accepts it
    entry = {"category": "mobile", "level2_label": "Diesel Fuel", "anchor_kind": "vehicle_group",
             "anchor_id": tree["vehicle_groups"][0]["anchor_id"], "label": "Delivery trucks, diesel"}
    assert cl.normalize_evidence_lines([entry])[0]["key"] == "s1:mobile:diesel-fuel:vg-delivery-trucks"


# --- counts at every level and the facility filter ----------------------------------------------
def _counts_store() -> FakeStore:
    store = FakeStore()
    store.add_document("BILL", "CT-S2-ELEC", [_elec(10, "Kansas City Plant"), _elec(20, "St Louis Plant")])
    store.add_document("G1", "CT-S1-FUELQTY", [_gas()])
    store.add_document("G2", "CT-S1-FUELQTY", [_gas(plant="St Louis Plant")], decision="rejected")
    store.add_document("WB", "CT-GHG-WORKBOOK", [{"reported_total": (500, "t")}], decision=None)
    store.documents.append({"document_id": "NEW", "engagement_id": "ENG-1", "org_id": ORG, "file_name": "n.pdf",
                            "processing_status": "queued"})
    return store


def test_counts_at_every_level_never_double_count_a_document_in_two_places() -> None:
    tree = _tree(_counts_store())
    blocks = tree["blocks"]
    assert blocks["summary_counts"] == {"documents": 1, "values": 1, "accepted": 0, "to_review": 1, "issues": 0,
                                        "pct_accepted": 0.0}
    assert blocks["unassigned_counts"]["documents"] == 1 and blocks["unassigned_counts"]["values"] == 0
    assert blocks["supporting"]["unassigned_counts"]["documents"] == 0
    scopes = {s["scope"]: s for s in blocks["supporting"]["scopes"]}
    # BILL sits on two lines (one per facility): one document, 12 values (6 per record)
    assert scopes["s2"]["counts"] == {"documents": 1, "values": 12, "accepted": 12, "to_review": 0, "issues": 0,
                                      "pct_accepted": 100.0}
    assert scopes["s1"]["counts"] == {"documents": 2, "values": 12, "accepted": 6, "to_review": 0, "issues": 6,
                                      "pct_accepted": 50.0}
    assert scopes["biogenic"]["counts"]["documents"] == 0


def test_the_facility_filter_shows_one_facility_and_recomputes_counts() -> None:
    service = _tree_service(_counts_store())
    tree = service.tree(_engagement(), _own, None, "fac-stl2")
    assert {ln["key"] for ln in tree["lines"]} == {GAS_STL, ELEC_STL}
    assert _lines_with_docs(tree) == {GAS_STL: ["G2"], ELEC_STL: ["BILL"]}
    scopes = {s["scope"]: s for s in tree["blocks"]["supporting"]["scopes"]}
    assert scopes["s1"]["counts"] == {"documents": 1, "values": 6, "accepted": 0, "to_review": 0, "issues": 6,
                                      "pct_accepted": 0.0}  # issues are kept
    assert scopes["s2"]["counts"]["values"] == 6 and scopes["s2"]["counts"]["documents"] == 1
    # blocks follow their rows' facility: the workbook and the unread file match no facility
    assert tree["blocks"]["summary"] == [] and tree["blocks"]["unassigned"] == []
    assert tree["blocks"]["summary_counts"]["documents"] == 0
    assert [f["facility_id"] for f in tree["facilities"]] == ["fac-kc01", "fac-stl2"]  # not filtered
    nothing = service.tree(_engagement(), _own, None, "fac-nowhere")
    assert nothing["lines"] == [] and _lines_with_docs(nothing) == {}
    unfiltered = service.tree(_engagement(), _own, None, None)
    assert len(unfiltered["lines"]) == 4 and len(unfiltered["blocks"]["summary"]) == 1


def test_a_stored_chain_through_a_line_that_was_since_deleted_still_lands_on_the_final_line() -> None:
    gone = "s1:stationary:propane:fac-kc01"
    moves = [{"from": GAS_KC, "to": gone}, {"from": gone, "to": GAS_STL}]
    slots = cl.apply_placements([cl.Slot(GAS_KC, {0})], moves, {GAS_KC, GAS_STL})
    assert [(s.target, s.records) for s in slots] == [(GAS_STL, {0})]
    filed = cl.file_documents([("D", "CT-S1-FUELQTY", [cl.RecordPlacement("stationary", "natural-gas", "Natural Gas",
                                                                          "facility", "fac-kc01")])],
                              {"D": {"placements": moves}}, {GAS_KC, GAS_STL})
    assert [s.target for s in filed["D"]] == [GAS_STL]
