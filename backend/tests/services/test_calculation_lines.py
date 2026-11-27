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


def test_removing_a_vehicle_group_never_drops_its_documents() -> None:
    mine = "s1:mobile:diesel-fuel:vg-lieferwagen-z-rich"  # the slug keeps ASCII letters only
    groups = [_group("Diesel Fuel", "Lieferwagen – Zürich")]

    def tree(settings_groups: list[dict]) -> dict:
        store = FakeStore()
        store.add_document("M1", "CT-S1-MOBFUEL", [_mobile()])
        store.add_document("M2", "CT-S1-MOBFUEL", [_mobile()])
        # M2 was also placed on the group's line by hand
        return _tree(store, {"M2": {"placements": [{"from": cl.SUPPORTING_UNASSIGNED, "to": mine}]}},
                     recalculation={"vehicle_groups": settings_groups})

    before = tree(groups)
    assert mine in {line["key"] for line in before["lines"]}
    assert sorted(_lines_with_docs(before)[mine]) == ["M1", "M2"]
    after = tree([])  # the group is removed in Setup
    assert mine not in {line["key"] for line in after["lines"]}
    unassigned = {row["document_id"] for row in after["blocks"]["supporting"]["unassigned"]}
    assert unassigned == {"M1", "M2"}  # both still listed, in Unassigned supporting evidence
    assert after["set_aside"] == []


def test_two_vehicle_groups_with_one_name_get_distinct_lines_and_cjk_names_do_not_fail() -> None:
    twice = [_group("Diesel Fuel", "配送トラック"), _group("Diesel Fuel", "配送トラック"),
             _group("Diesel Fuel", "Lieferwagen – Zürich")]
    anchors = [a for a, _ in cl.vehicle_group_anchors(twice)]
    assert anchors == ["vg-none", "vg-none-2", "vg-lieferwagen-z-rich"]  # CJK-only names slug alike, then number by order
    assert _tree(FakeStore(), recalculation={"vehicle_groups": twice})["blocks"]["summary"] == []


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


# --- the calculation family, for a move's "won't count" warning --------------------------------
def _rows_by_line(tree: dict) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for scope in tree["blocks"]["supporting"]["scopes"]:
        for category in scope["categories"]:
            for level2 in category["level2s"]:
                for line in level2["lines"]:
                    for row in line["documents"]:
                        rows[line["line"]["key"]] = row
    return rows


def test_lines_and_rows_carry_the_calculation_family() -> None:
    store = FakeStore()
    store.add_document("GAS", "CT-S1-FUELQTY", [_gas()])
    store.add_document("BILL", "CT-S2-ELEC", [_elec(10)])
    tree = _tree(store)
    family = {line["key"]: line["family"] for line in tree["lines"]}
    assert family[GAS_KC] == "stationary" and family[ELEC_KC] == "electricity"
    rows = _rows_by_line(tree)
    assert rows[GAS_KC]["value_family"] == "stationary" and rows[ELEC_KC]["value_family"] == "electricity"


def test_a_line_no_calculation_reads_has_no_family() -> None:
    from backend.app.services import calculation_lines as cl

    fugitive = cl.make_line("fugitive", "r-404a", "R-404A", "facility", "fac-kc01", "Kansas City Plant",
                            created_by_user=True)
    steam = cl.make_line("purchased_energy", "steam", "Steam", "facility", "fac-kc01", "Kansas City Plant",
                         created_by_user=True)
    assert fugitive.family is None and steam.family is None
    assert fugitive.to_dict()["family"] is None


def test_a_document_on_several_lines_reports_each_placements_own_family_and_a_block_has_none() -> None:
    store = FakeStore()
    store.add_document("BILL", "CT-S2-ELEC", [_elec(10), _elec(20, "St Louis Plant")])
    store.add_document("WB", "CT-S0-WORKBOOK", [])
    rows = _rows_by_line(_tree(store))
    assert rows[ELEC_KC]["value_family"] == "electricity" and rows[ELEC_STL]["value_family"] == "electricity"
    empty = _tree(FakeStore())
    assert empty["lines"] == [] and empty["blocks"]["summary"] == []


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


def test_moving_one_placement_onto_a_line_the_document_already_has_merges_without_a_duplicate() -> None:
    store = FakeStore()
    store.add_document("BILL", "CT-S2-ELEC", [_elec(10), _elec(20, "St Louis Plant")])
    tree = _tree(store, {"BILL": {"placements": [{"from": ELEC_KC, "to": ELEC_STL}]}})
    assert _lines_with_docs(tree) == {ELEC_STL: ["BILL"]}
    row = _rows_by_line(tree)[ELEC_STL]
    assert row["values"] == 12 and row["also_in"] == []  # both records now show on the one line, once


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


def test_the_server_fills_in_the_key_of_a_line_and_the_saved_form_round_trips() -> None:
    saved = cl.normalize_evidence_lines([_line()])[0]
    assert saved["key"] == "s1:stationary:propane:fac-kc01" and saved["scope"] == "s1" and saved["level2"] == "propane"
    assert cl.normalize_evidence_lines([saved]) == [saved]
    company = cl.normalize_evidence_lines([
        _line(category="contractual", level2_label="PPAs", anchor_kind="company", anchor_id=None)])
    assert company[0]["key"] == "s2:contractual:ppas:company"


def test_a_settings_save_drops_evidence_lines_whatever_they_hold() -> None:
    """Lines change only through the Evidence actions: a save's own copy (a stale tab's, even a broken one)
    is ignored, never judged, so an autosave cannot fail on it."""

    assert "evidenceLines" in SETTINGS_KEYS  # an old client may still send it
    for sent in ([_line()], "nope", [{"junk": 1}], [_line(), _line()]):
        assert EngagementUpdate(settings={"evidenceLines": sent, "dataScope": "x"}).settings == {"dataScope": "x"}


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
        cl.normalize_evidence_lines([bad])


def test_evidence_lines_limits_and_duplicates() -> None:
    with pytest.raises(ValueError):
        cl.normalize_evidence_lines("nope")
    with pytest.raises(ValueError):
        cl.normalize_evidence_lines([_line(), _line()])
    many = [_line(level2_label=f"Fuel {i}") for i in range(201)]
    with pytest.raises(ValueError):
        cl.normalize_evidence_lines(many)
    assert len(cl.normalize_evidence_lines(many[:200])) == 200


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
    history = schedule["history"]
    assert [h["at"] for h in history] == sorted((h["at"] for h in history), reverse=True)  # newest first
    corrected = next(h for h in history if h["action"] == "corrected")
    assert (corrected["actor_name"], corrected["field"], corrected["value"], corrected["unit"], corrected["file_name"],
            corrected["page"]) == ("bo@example.com", "Activity quantity", "150", "MMBtu", "BILL-C.pdf", 1)
    # Ana accepted all of BILL-A's fields in one minute: one entry, with a count
    bulk = next(h for h in history if h["action"] == "accepted" and h["actor_name"] == "Ana Reyes")
    assert bulk["count"] > 1 and bulk["field"] is None and bulk["at"] == "2025-04-02T10:00:00Z"
    assert history[-1] == {"action": "extracted", "actor_name": "System", "at": "2025-04-01T08:05:00Z", "field": None,
                           "value": None, "unit": None, "file_name": None, "page": None, "count": 3, "documents": 3}


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
    record = group_reviewed_records({"document_id": "D"}, "CT-S1-FUELQTY", items, [])[0]
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
    assert [(h["action"], h["actor_name"], h["field"], h["value"]) for h in schedule["history"][:2]] == [
        ("corrected", "bo@example.com", "Activity quantity", "300"),
        ("accepted", "ana@example.com", "Activity quantity", "310")]
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
# G2's values are rejected, and a rejected facility name does not place a bill: the reviewer chose its facility.
COUNTS_DECISIONS = {"G2": {"facilityId": "fac-stl2"}}


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
    tree = _tree(_counts_store(), COUNTS_DECISIONS)
    blocks = tree["blocks"]
    # Block 1 is reference only: the workbook's one value is not counted anywhere
    assert blocks["summary_counts"] == {"documents": 1, "values": 0, "accepted": 0, "to_review": 0, "issues": 0,
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


def test_a_bill_moved_into_block_1_carries_no_values_and_counts_for_nothing() -> None:
    store = _counts_store()
    base = _tree(store, COUNTS_DECISIONS)
    decisions = {**COUNTS_DECISIONS, "G1": {"placements": [{"from": GAS_KC, "to": cl.BLOCK_SUMMARY}]}}
    tree = _tree(store, decisions)
    blocks = tree["blocks"]
    row = next(d for d in blocks["summary"] if d["document_id"] == "G1")
    assert row["values"] == 0 and row["accepted"] == 0  # nothing to accept on a reference document
    assert blocks["summary_counts"]["documents"] == 2 and blocks["summary_counts"]["values"] == 0
    assert cl.in_summary_block([cl.Slot(cl.BLOCK_SUMMARY, {0})]) is True
    assert cl.in_summary_block([cl.Slot(GAS_KC, {0})]) is False
    # its values leave Supporting evidence too: no count anywhere picks them up
    before = {s["scope"]: s["counts"] for s in base["blocks"]["supporting"]["scopes"]}["s1"]
    after = {s["scope"]: s["counts"] for s in blocks["supporting"]["scopes"]}["s1"]
    assert after["documents"] == before["documents"] - 1 and after["values"] == before["values"] - 6


def test_the_facility_filter_shows_one_facility_and_recomputes_counts() -> None:
    service = _tree_service(_counts_store())
    tree = service.tree(_engagement(), _own, COUNTS_DECISIONS, "fac-stl2")
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
    nothing = service.tree(_engagement(), _own, COUNTS_DECISIONS, "fac-nowhere")
    assert nothing["lines"] == [] and _lines_with_docs(nothing) == {}
    unfiltered = service.tree(_engagement(), _own, COUNTS_DECISIONS, None)
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


# --- D1: the server validates line anchors ----------------------------------------------------
def _check(lines: list[dict], *, stored: set[str] | None = None, facilities: list[dict] | None = None,
           groups: list[dict] | None = None) -> None:
    cl.check_new_lines(cl.normalize_evidence_lines(lines), stored_keys=stored or set(),
                       facilities=[KC, STL] if facilities is None else facilities, vehicle_groups=groups or [])


def _refused(lines: list[dict], match: str, **kwargs: Any) -> None:
    with pytest.raises(ValueError, match=match):
        _check(lines, **kwargs)


def test_a_line_on_a_setup_facility_is_accepted_and_an_unknown_facility_is_refused() -> None:
    _check([_line()])
    _refused([_line(anchor_id="fac-gone")], "facility isn't in Setup")


def test_a_facility_without_a_facility_id_is_anchored_by_its_name() -> None:
    nameless = {"name": "Müller Käserei – Zürich"}
    anchor = cl.facility_anchor_id(nameless)
    assert anchor == "name-m-ller-k-serei-z-rich"
    _check([_line(anchor_id=anchor)], facilities=[nameless])
    _refused([_line(anchor_id="name-other")], "facility isn't in Setup", facilities=[nameless])


def test_an_engagement_with_no_facilities_refuses_facility_lines_but_not_company_wide_ones() -> None:
    _refused([_line()], "Add a facility in Setup first", facilities=[])
    _refused([_line(category="contractual", level2_label="PPAs", anchor_id="fac-kc01")],
             "Add a facility in Setup first", facilities=[])
    _check([_line(category="contractual", level2_label="PPAs", anchor_kind="company", anchor_id=None)],
           facilities=[])
    _check([_line()], stored={"s1:stationary:propane:fac-kc01"}, facilities=[])  # already stored: left alone


def test_a_vehicle_group_line_follows_the_groups_in_the_same_settings() -> None:
    groups = [{"vehicle_type": "Truck", "factor_fuel_type": "Diesel", "label": "Delivery vans", "fuel": "Diesel Fuel"}]
    mobile = {"category": "mobile", "level2_label": "Diesel Fuel", "anchor_kind": "vehicle_group", "label": "Vans"}
    _check([{**mobile, "anchor_id": "vg-delivery-vans"}], groups=groups)
    _refused([{**mobile, "anchor_id": "vg-delivery-vans"}], "vehicle group isn't in Setup")  # no groups
    # the group is renamed in Setup: the old anchor is refused as new, the stored line is left alone
    renamed = [{**groups[0], "label": "Courier vans"}]
    _refused([{**mobile, "anchor_id": "vg-delivery-vans"}], "vehicle group isn't in Setup", groups=renamed)
    _check([{**mobile, "anchor_id": "vg-delivery-vans"}], groups=renamed,
           stored={"s1:mobile:diesel-fuel:vg-delivery-vans"})
    twins = [groups[0], dict(groups[0])]
    _check([{**mobile, "anchor_id": "vg-delivery-vans-2"}], groups=twins)


def test_company_anchor_is_for_contractual_lines_only_and_contractual_may_sit_on_a_facility() -> None:
    _check([_line(category="contractual", level2_label="PPAs", anchor_kind="company", anchor_id=None)])
    _check([_line(category="contractual", level2_label="PPAs", anchor_id="fac-kc01")])
    _refused([_line(category="contractual", level2_label="PPAs", anchor_id="fac-gone")], "facility isn't in Setup")
    _refused([_line(anchor_kind="company", anchor_id=None)], "Only contractual instruments")


@pytest.mark.parametrize("label", ["燃料", "日本語の燃料", "—", "Ω", "!!!", "💥"])
def test_a_name_with_no_letters_or_numbers_is_refused(label: str) -> None:
    _refused([_line(level2_label=label)], "Use letters or numbers")


def test_a_literal_none_and_a_120_character_non_ascii_name_with_letters_are_fine() -> None:
    _check([_line(level2_label="None")])
    long = "Ölé" * 40
    assert len(long) == 120
    _check([_line(level2_label=long, label=long)])


def test_the_200_line_cap_still_holds_and_a_full_valid_list_passes() -> None:
    many = [_line(level2_label=f"Fuel {i}") for i in range(200)]
    _check(many)
    with pytest.raises(ValueError, match="at most 200"):
        _check([*many, _line(level2_label="Fuel 200")])


def _saved(**changes: Any) -> dict:
    return cl.normalize_evidence_lines([_line(**changes)])[0]


def test_the_engagement_routes_check_anchors_against_the_same_settings() -> None:
    from fastapi import HTTPException

    from backend.app.api import engagements as engagements_api

    engagements_api._check_line_anchors({"facilities": [KC]}, {"settings": {}})
    engagements_api._check_line_anchors({"facilities": [KC], "evidenceLines": [_saved()]}, {"settings": {}})
    for bad in ({"facilities": [KC], "evidenceLines": [_saved(anchor_id="fac-nope")]},
                {"evidenceLines": [_saved()]}):
        with pytest.raises(HTTPException) as caught:
            engagements_api._check_line_anchors(bad, {"settings": {}})
        assert caught.value.status_code == 422 and caught.value.detail
    # vehicle groups are read from the same settings' recalculation block
    group = {"vehicle_type": "Truck", "factor_fuel_type": "Diesel", "label": "Vans", "fuel": "Diesel Fuel"}
    mobile = cl.normalize_evidence_lines([{"category": "mobile", "level2_label": "Diesel Fuel",
                                           "anchor_kind": "vehicle_group", "anchor_id": "vg-vans", "label": "Vans"}])
    engagements_api._check_line_anchors({"facilities": [KC], "recalculation": {"vehicle_groups": [group]},
                                         "evidenceLines": mobile}, None)
    with pytest.raises(HTTPException):
        engagements_api._check_line_anchors({"facilities": [KC], "evidenceLines": mobile}, None)


def test_a_save_that_keeps_a_removed_facilitys_line_is_not_refused() -> None:
    from backend.app.api import engagements as engagements_api

    stored_line = [_saved()]
    current = {"settings": {"facilities": [KC], "evidenceLines": stored_line}}
    # Setup now holds only St Louis, and the Kansas City line is stored already: other settings still save.
    engagements_api._check_line_anchors({"facilities": [STL], "evidenceLines": stored_line}, current)


def test_a_stored_line_on_a_removed_facility_does_not_break_the_tree() -> None:
    mine = [_saved(anchor_id="fac-gone", label="Propane at the old plant")]
    store = FakeStore()
    store.add_document("G1", "CT-S1-FUELQTY", [_gas()])
    orphan = "s1:stationary:propane:fac-gone"  # fac-gone is not a Setup facility
    tree = _tree(store, {"G1": {"placements": [{"from": GAS_KC, "to": orphan}]}}, evidenceLines=mine)
    # the read path is unchanged: the line stays visible with its document, and nothing fails
    assert _lines_with_docs(tree) == {orphan: ["G1"]}


# --- D2: who created a line, and when ---------------------------------------------------------
NOW = "2025-11-04T10:00:00+00:00"


def test_a_new_line_is_stamped_and_a_stored_one_keeps_its_stamp() -> None:
    old = {**_saved(), "created_by": "user-1", "created_at": "2025-10-01T09:00:00+00:00"}
    new = _saved(level2_label="Diesel")
    out = cl.stamp_new_lines([_saved(label="Renamed"), new], [old], user_id="user-2", now=NOW)
    assert (out[0]["created_by"], out[0]["created_at"]) == ("user-1", "2025-10-01T09:00:00+00:00")
    assert out[0]["label"] == "Renamed"
    assert (out[1]["created_by"], out[1]["created_at"]) == ("user-2", NOW)


def test_a_forged_stamp_is_dropped_for_new_and_stored_lines() -> None:
    forged = {"created_by": "admin", "created_at": "2001-01-01T00:00:00+00:00"}
    old = {**_saved(), "created_by": "user-1", "created_at": NOW}
    out = cl.stamp_new_lines(cl.normalize_evidence_lines([{**_line(), **forged}, {**_line(level2_label="Diesel"), **forged}]),
                             [old], user_id="user-2", now="2025-11-05T00:00:00+00:00")
    assert out[0]["created_by"] == "user-1" and out[0]["created_at"] == NOW
    assert out[1]["created_by"] == "user-2" and out[1]["created_at"] == "2025-11-05T00:00:00+00:00"


def test_a_line_stored_before_stamps_existed_stays_unstamped() -> None:
    out = cl.stamp_new_lines([_saved()], [_saved()], user_id="user-2", now=NOW)
    assert "created_by" not in out[0] and "created_at" not in out[0]
    assert cl.stamp_new_lines([_saved()], "junk", user_id="u", now=NOW)[0]["created_by"] == "u"


def test_stamps_survive_the_settings_check_and_reach_the_line() -> None:
    entry = {**_saved(), "created_by": "user-1", "created_at": NOW}
    assert cl.normalize_evidence_lines([entry])[0]["created_by"] == "user-1"
    [line] = cl.user_lines({"evidenceLines": [entry]})
    assert (line.created_by, line.created_at) == ("user-1", NOW)
    assert cl.user_lines({"evidenceLines": [_saved()]})[0].created_by is None


def test_the_tree_names_the_creator_and_copes_with_an_unknown_one() -> None:
    mine = [{**_saved(), "created_by": "u-1", "created_at": NOW},
            {**_saved(level2_label="Diesel", label="Diesel"), "created_by": "u-gone", "created_at": NOW},
            _saved(level2_label="Kerosene", label="Kerosene")]
    store = FakeStore()
    store.add_document("G1", "CT-S1-FUELQTY", [_gas()])
    tree = _tree_service(store).tree(_engagement(evidenceLines=mine), _own, None, None, {"u-1": "Müller Käserei – Zürich"})
    by_label = {ln["label"]: ln for ln in tree["lines"]}
    assert by_label["Propane at KC"]["created_by_name"] == "Müller Käserei – Zürich"
    assert by_label["Propane at KC"]["created_at"] == NOW
    assert by_label["Diesel"]["created_by_name"] is None and by_label["Kerosene"]["created_by_name"] is None
    assert "created_by_name" not in by_label["Natural Gas, Kansas City Plant"]  # a system line has no creator


# --- D3 fix round: the saved chain is derived from where the document is filed now ---------------
def _doc(default: list[cl.Slot]) -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(default_slots=default, document={"file_name": "feb-bill.pdf"}, document_id="D")


def _next(chain: list, move: dict, default: list[cl.Slot], known: set[str]) -> list:
    from backend.app.api import evidence_actions

    return evidence_actions._next_chain(chain, move, _doc(default), known)  # type: ignore[arg-type]


def _resolved(default: list[cl.Slot], chain: list, known: set[str]) -> list:
    return sorted((s.target, tuple(sorted(s.records)), tuple(s.flags)) for s in cl.merge_slots(
        [cl.resolve_target(s, known) for s in cl.apply_placements(default, chain, known)]))


def _simulate(seed: int, steps: int, churn: float):  # noqa: ANN202
    """API-valid random moves on one document while lines vanish and come back: a move's ``from`` is a place
    the document shows now (so a document parked on a missing line moves from "supporting:unassigned"), and
    its ``to`` a line that exists or a fixed place. Yields (default, saved chain, move, known) per step."""

    import random

    rng = random.Random(seed)
    base, others = ["D1", "D2"], ["X1", "X2", "X3"]
    known = set(base) | set(others)
    default = cl.merge_slots([cl.Slot(rng.choice(base), {i}) for i in range(rng.randint(1, 3))])
    chain: list = []
    for _ in range(steps):
        if rng.random() < churn:
            line = rng.choice(others)
            known = known - {line} if line in known else known | {line}
        shown = [t for t, _, _ in _resolved(default, chain, known)]
        source = rng.choice(shown)
        target = rng.choice([t for t in sorted(known) + [cl.BLOCK_SUMMARY, cl.BLOCK_UNASSIGNED, cl.SUPPORTING_UNASSIGNED]
                             if t != source])
        move = {"from": source, "to": target}
        yield default, chain, move, set(known)
        chain = _next(chain, move, default, known)


def test_the_saved_chain_files_the_document_exactly_as_the_full_history_does_and_stays_short() -> None:
    steps = fallbacks = 0
    for seed in range(400):
        longest = 0
        for default, chain, move, known in _simulate(seed, 40, 0.15):
            full = [*chain, move]
            now = _next(chain, move, default, known)
            filing = cl.apply_placements(default, full, known)
            # exactly where every record is now: by raw place, so "parked on X1" never turns into "parked on X3"
            assert cl.raw_filing(cl.apply_placements(default, now, known)) == cl.raw_filing(filing), (seed, full, now)
            assert _resolved(default, now, known) == _resolved(default, full, known)
            steps += 1
            if len(now) > len(default) + len(default) // 2:  # the full chain was kept
                fallbacks += 1
            longest = max(longest, len(now))
        assert longest <= cl.MAX_PLACEMENT_MOVES
    assert fallbacks / steps < 0.02, (fallbacks, steps)


def test_a_chain_never_has_more_moves_than_default_slots_plus_one_parking_move_per_swap() -> None:
    for seed in range(300):
        for default, chain, move, known in _simulate(seed, 60, 0.0):
            now = _next(chain, move, default, known)
            assert len(now) <= len(default) + len(default) // 2, (seed, now)


def test_a_thousand_moves_between_two_lines_leave_at_most_one_saved_move() -> None:
    default = [cl.Slot("s1:stationary:a:f1", {0})]
    known = {"s1:stationary:a:f1", "s1:stationary:b:f1"}
    chain: list = []
    for i in range(1000):
        here = "s1:stationary:a:f1" if i % 2 == 0 else "s1:stationary:b:f1"
        there = "s1:stationary:b:f1" if i % 2 == 0 else "s1:stationary:a:f1"
        chain = _next(chain, {"from": here, "to": there}, default, known)
    assert chain == []  # 1000 moves ended where they began
    assert _next(chain, {"from": "s1:stationary:a:f1", "to": "s1:stationary:b:f1"}, default, known) == [
        {"from": "s1:stationary:a:f1", "to": "s1:stationary:b:f1"}]


def test_seed_2178_a_record_moved_off_a_gone_line_is_not_put_back_on_another() -> None:
    """The review's repro (seed 2178): compaction by resolved filing parked a record on a different missing
    line than the history had, so it came back on the wrong line when that line returned."""

    for default, chain, move, known in _simulate(2178, 15, 0.25):
        now = _next(chain, move, default, known)
        full = [*chain, move]
        assert cl.raw_filing(cl.apply_placements(default, now, known)) == cl.raw_filing(
            cl.apply_placements(default, full, known))
        for line in ("X1", "X2", "X3"):  # whichever missing line returns, a parked record is where it was parked
            back = known | {line}
            parked = {t for t in cl.raw_filing(cl.apply_placements(default, full, known)) if t == line}
            assert parked <= set(cl.raw_filing(cl.apply_placements(default, now, back)))


def test_a_document_parked_on_a_line_that_is_gone_stays_parked_there_and_returns_with_the_line() -> None:
    default = [cl.Slot("G", {0})]
    chain = _next([], {"from": "G", "to": "X"}, default, {"G", "X"})
    assert chain == [{"from": "G", "to": "X"}]
    gone = {"G"}
    # still the same one move however often it is asked about, and back on X when X returns
    assert _next(chain, {"from": "supporting:unassigned", "to": "supporting:unassigned"}, default, gone) == chain
    assert _resolved(default, chain, {"G", "X"}) == [("X", (0,), ())]


def test_derive_places_every_default_slot_and_orders_out_before_in() -> None:
    default = [cl.Slot("A", {0}), cl.Slot("B", {1})]
    where = lambda *pairs: [cl.Slot(t, set(r)) for t, r in pairs]  # noqa: E731
    assert cl.derive_placements(default, where(("A", {0}), ("B", {1}))) == []
    assert cl.derive_placements(default, where(("C", {0, 1}))) == [{"from": "A", "to": "C"}, {"from": "B", "to": "C"}]
    # A -> B and B -> C: B moves out first, or A's records would arrive in B and move on with it
    assert cl.derive_placements(default, where(("B", {0}), ("C", {1}))) == [
        {"from": "B", "to": "C"}, {"from": "A", "to": "B"}]
    # two slots swapping places go through a free fixed place; a default slot split across places is not derivable
    assert cl.derive_placements(default, where(("B", {0}), ("A", {1}))) == [
        {"from": "A", "to": cl.BLOCK_SUMMARY}, {"from": "B", "to": "A"}, {"from": cl.BLOCK_SUMMARY, "to": "B"}]
    taken = [cl.Slot("A", {0}), cl.Slot("B", {1}), cl.Slot(cl.BLOCK_SUMMARY, {2}), cl.Slot(cl.BLOCK_UNASSIGNED, {3}),
             cl.Slot(cl.SUPPORTING_UNASSIGNED, {4})]
    swapped = where(("B", {0}), ("A", {1}), (cl.BLOCK_SUMMARY, {2}), (cl.BLOCK_UNASSIGNED, {3}), (cl.SUPPORTING_UNASSIGNED, {4}))
    assert cl.derive_placements(taken, swapped) is None
    assert cl.derive_placements([cl.Slot("A", {0, 1})], where(("B", {0}), ("C", {1}))) is None


def test_a_chain_that_cannot_be_shortened_is_capped_with_a_plain_sentence_naming_the_document() -> None:
    from fastapi import HTTPException

    chain = [{"from": f"x{i}", "to": f"y{i}"} for i in range(cl.MAX_PLACEMENT_MOVES)]
    # a swap with every fixed place taken has no safe order, so the long chain is kept and the cap is reached
    full_default = [cl.Slot("A", {0}), cl.Slot("B", {1}), cl.Slot(cl.BLOCK_SUMMARY, {2}), cl.Slot(cl.BLOCK_UNASSIGNED, {3}),
                    cl.Slot(cl.SUPPORTING_UNASSIGNED, {4})]
    swapped = [{"from": "A", "to": "T"}, {"from": "B", "to": "A"}, {"from": "T", "to": "B"}]
    with pytest.raises(HTTPException) as caught:
        _next([*chain, *swapped[:2]], swapped[2], full_default, {"A", "B", "T"})
    assert caught.value.status_code == 409 and "feb-bill.pdf" in caught.value.detail
    assert "moved too many times" in caught.value.detail


# --- vehicle groups carry a stable group_id (S1-BE-012) ---------------------------------------------------------
def _ids(groups: list[dict]) -> list[str]:
    return [g["group_id"] for g in groups]


def _with_ids(groups: list[dict], stored: list[dict] | None = None) -> list[dict]:
    return cl.assign_group_ids(groups, stored)


def test_a_new_group_gets_an_opaque_id_and_names_do_not_matter() -> None:
    names = ["配送トラック", "配送トラック", "Lieferwagen – Zürich", "Zürich", "z-rich", "", "x" * 200]
    groups = _with_ids([_group("Diesel Fuel", n) for n in names])
    ids = _ids(groups)
    assert len(set(ids)) == len(names)  # distinct, even for the same name and for names that slug alike
    assert all(cl.GROUP_ID.match(i) and i.startswith("vgid-") for i in ids)
    # a new id is its own slug (the line key keeps it) and can never be an old ``vg-<slug>`` anchor
    assert all(cl.slug(i) == i and not i.startswith("vg-") for i in ids)
    assert all(a == i for (a, _), i in zip(cl.vehicle_group_anchors(groups), ids, strict=True))
    assert not any("none" in i or "z-rich" in i for i in ids)  # no longer built from the name


def test_rename_reorder_and_removal_never_change_another_groups_id() -> None:
    stored = _with_ids([_group("Diesel Fuel", "Trucks"), _group("Diesel Fuel", "Trucks"), _group("Motor Gasoline", "Pickups")])
    a, b, c = _ids(stored)
    renamed = _with_ids([{**stored[0], "label": "Delivery 配送"}, stored[1], stored[2]], stored)
    assert _ids(renamed) == [a, b, c] and renamed[0]["label"] == "Delivery 配送"
    assert _ids(_with_ids([stored[2], stored[0], stored[1]], stored)) == [c, a, b]  # reordered
    assert _ids(_with_ids([stored[1], stored[2]], stored)) == [b, c]  # the first removed
    assert _ids(_with_ids([stored[0], stored[2]], stored)) == [a, c]  # the second removed
    assert _ids(_with_ids([stored[0], stored[1]], stored)) == [a, b]  # the last removed


def test_an_added_group_never_takes_the_id_of_a_removed_one() -> None:
    stored = _with_ids([_group("Diesel Fuel", "A"), _group("Diesel Fuel", "B")])
    after_removal = _with_ids([stored[1]], stored)
    again = _with_ids([stored[1], _group("Diesel Fuel", "A")], after_removal)  # "A" is added again
    assert again[1]["group_id"] not in _ids(stored)
    assert again[0]["group_id"] == stored[1]["group_id"]


def test_an_id_the_engagement_never_had_is_not_trusted() -> None:
    stored = _with_ids([_group("Diesel Fuel", "A")])
    forged = {**_group("Diesel Fuel", "B"), "group_id": "vg-forgedforged"}
    out = _with_ids([stored[0], forged], stored)
    assert out[0]["group_id"] == stored[0]["group_id"] and out[1]["group_id"] != "vg-forgedforged"
    twice = _with_ids([stored[0], {**_group("Diesel Fuel", "C"), "group_id": stored[0]["group_id"]}], stored)
    assert len(set(_ids(twice))) == 2  # one id, one group


def test_a_client_that_sends_no_ids_keeps_the_groups_it_did_not_change() -> None:
    stored = _with_ids([_group("Diesel Fuel", "Trucks"), _group("Diesel Fuel", "Trucks"), _group("Motor Gasoline", "Pickups")])
    bare = [{k: v for k, v in g.items() if k != "group_id"} for g in stored]
    assert _ids(_with_ids(bare, stored)) == _ids(stored)  # duplicates matched in order
    assert _ids(_with_ids(bare[::-1], stored))[0] == stored[2]["group_id"]  # a reordered unchanged group too
    changed = [{**bare[0], "label": "Renamed"}, *bare[1:]]
    out = _with_ids(changed, stored)
    assert out[1]["group_id"] in _ids(stored) and out[0]["group_id"] not in _ids(stored)  # a rename it cannot tell: new


def test_groups_saved_before_ids_are_known_by_their_old_anchor() -> None:
    old = [_group("Diesel Fuel", "配送トラック"), _group("Diesel Fuel", "配送トラック")]
    assert [a for a, _ in cl.vehicle_group_anchors(old)] == ["vg-none", "vg-none-2"]
    out = _with_ids(old, old)
    assert _ids(out) == ["vg-none", "vg-none-2"]  # the lines they already have
    # the page sends each group's id back, so removing the first no longer renumbers the second
    assert _ids(_with_ids([{**old[1], "group_id": "vg-none-2"}], out)) == ["vg-none-2"]
    mixed = [{**old[0], "group_id": "vg-abcdef012345"}, old[1]]
    assert [a for a, _ in cl.vehicle_group_anchors(mixed)] == ["vg-abcdef012345", "vg-none-2"]


def test_a_group_with_no_id_never_takes_an_anchor_another_group_has_as_its_id() -> None:
    groups = [{**_group("Diesel Fuel", "Trucks"), "group_id": "vg-trucks"}, _group("Diesel Fuel", "Trucks")]
    anchors = [a for a, _ in cl.vehicle_group_anchors(groups)]
    assert anchors[0] == "vg-trucks" and anchors[1] != "vg-trucks" and len(set(anchors)) == 2


def _on_line(settings_groups: list[dict], line: str, store: FakeStore | None = None) -> tuple[dict, list[str]]:
    store = store or FakeStore()
    if not store.documents:
        store.add_document("M2", "CT-S1-MOBFUEL", [_mobile()])
    tree = _tree(store, {"M2": {"placements": [{"from": cl.SUPPORTING_UNASSIGNED, "to": line}]}},
                 recalculation={"vehicle_groups": settings_groups})
    return tree, _lines_with_docs(tree).get(line, [])


@pytest.mark.parametrize("names", [["Trucks", "Trucks"], ["配送トラック", "配送トラック"], ["Zürich", "Zürich", "Zürich"]],
                         ids=["duplicate names", "CJK only", "accented"])
def test_a_document_placed_by_hand_stays_on_its_groups_line_through_every_change(names: list[str]) -> None:
    stored = _with_ids([_group("Diesel Fuel", n) for n in names])
    target = stored[-1]  # the last group: removing or reordering an earlier one used to renumber it
    line = f"s1:mobile:diesel-fuel:{target['group_id']}"
    tree, docs = _on_line(stored, line)
    assert docs == ["M2"]
    changes = {
        "renamed": [*stored[:-1], {**target, "label": "Brand new name"}],
        "first removed": stored[1:],
        "all others removed": [target],
        "reordered": [target, *stored[:-1]],
        "other groups edited": [{**g, "model_year": 2020} for g in stored[:-1]] + [target],
    }
    for name, groups in changes.items():
        after, docs = _on_line(_with_ids(groups, stored), line)
        assert docs == ["M2"], name
        assert line in {ln["key"] for ln in after["lines"]}, name
    renamed_tree, _ = _on_line(_with_ids(changes["renamed"], stored), line)
    assert {ln["key"]: ln["label"] for ln in renamed_tree["lines"]}[line].endswith("Brand new name")  # the label follows


def test_a_document_parked_on_a_removed_group_returns_only_with_that_group() -> None:
    stored = _with_ids([_group("Diesel Fuel", "Trucks"), _group("Diesel Fuel", "Yard"), _group("Diesel Fuel", "Vans")])
    line = f"s1:mobile:diesel-fuel:{stored[0]['group_id']}"
    store = FakeStore()
    store.add_document("M2", "CT-S1-MOBFUEL", [_mobile()])
    gone, docs = _on_line(_with_ids(stored[1:], stored), line, store)
    assert docs == [] and [r["document_id"] for r in gone["blocks"]["supporting"]["unassigned"]] == ["M2"]
    # the group is added again: a new group, a new line: the document does not land on it
    back = _with_ids([*stored[1:], _group("Diesel Fuel", "Trucks")], _with_ids(stored[1:], stored))
    again, docs = _on_line(back, line, store)
    assert docs == []
    # while a rename of the removed group's neighbour, or the group's own id, brings nothing back by name
    same_id = [*stored[1:], {**_group("Diesel Fuel", "Trucks"), "group_id": stored[0]["group_id"]}]
    assert _on_line(same_id, line, store)[1] == ["M2"]  # the stored id is what a line is: the data, not the name


def test_every_vehicle_group_line_label_and_key_follows_the_id() -> None:
    groups = _with_ids([_group("Diesel Fuel", "Trucks")])
    tree = _tree(FakeStore(), recalculation={"vehicle_groups": groups})
    assert tree["vehicle_groups"] == [{"anchor_id": groups[0]["group_id"], "label": "Trucks", "fuel": "Diesel Fuel"}]
    key = cl.line_key("s1", "mobile", "diesel-fuel", "vehicle_group", groups[0]["group_id"])
    assert key == f"s1:mobile:diesel-fuel:{groups[0]['group_id']}"
    entry = {"category": "mobile", "level2_label": "Diesel Fuel", "anchor_kind": "vehicle_group",
             "anchor_id": groups[0]["group_id"], "label": "Trucks, diesel"}
    assert cl.normalize_evidence_lines([entry])[0]["key"] == key
    cl.check_new_lines(cl.normalize_evidence_lines([entry]), stored_keys=set(), facilities=[KC], vehicle_groups=groups)


# --- an existing engagement migrates with identical filing and recalculation ---------------------------------------
def _migration_module() -> Any:
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "migrations" / "versions" / "0021_vehicle_group_ids.py"
    spec = importlib.util.spec_from_file_location("migration_0021", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LEGACY_GROUPS = [  # what stored engagements hold today: no ids, anchors from the label and the order
    _group("Diesel Fuel", "配送トラック"), _group("Diesel Fuel", "配送トラック"), _group("Diesel Fuel", "Lieferwagen – Zürich"),
    _group("Diesel Fuel", "Lieferwagen – Zürich"), _group("Motor Gasoline", "Pickups"),
]


def test_the_migration_gives_each_group_the_anchor_it_has_today_and_is_safe_to_run_twice() -> None:
    migration = _migration_module()
    migrated = migration._add_ids(LEGACY_GROUPS)
    assert [g["group_id"] for g in migrated] == [a for a, _ in cl.vehicle_group_anchors(LEGACY_GROUPS)]
    assert [g["group_id"] for g in migrated] == ["vg-none", "vg-none-2", "vg-lieferwagen-z-rich",
                                                  "vg-lieferwagen-z-rich-2", "vg-pickups"]
    assert [{k: v for k, v in g.items() if k != "group_id"} for g in migrated] == LEGACY_GROUPS  # nothing else changed
    assert migration._add_ids(migrated) is None  # already done: left alone
    assert migration._remove_ids(migrated) == LEGACY_GROUPS and migration._remove_ids(LEGACY_GROUPS) is None
    # the migration's own copy of the old numbering is the code's old numbering
    assert migration._legacy_anchors(LEGACY_GROUPS) == cl.legacy_group_anchors(LEGACY_GROUPS)
    for label in ["", "x" * 200, "Zürich", "配送", "a--b", "  spaced  out  "]:
        group = _group("Diesel Fuel", label)
        assert migration._legacy_anchors([group, group]) == cl.legacy_group_anchors([group, group])
        assert all(cl.GROUP_ID.match(a) for a in cl.legacy_group_anchors([group, group]))  # valid ids as they are


def test_an_existing_engagement_files_and_recalculates_exactly_the_same_after_the_migration() -> None:
    from backend.tests.services.test_engagement_recalculation_service import _service as recalculation_service

    migration = _migration_module()
    migrated = migration._add_ids(LEGACY_GROUPS)
    by_anchor = {a: g for a, g in cl.vehicle_group_anchors(LEGACY_GROUPS)}
    user_line = cl.normalize_evidence_lines([{"category": "mobile", "level2_label": "Diesel Fuel",
                                              "anchor_kind": "vehicle_group", "anchor_id": "vg-none-2",
                                              "label": "Night trucks"}])
    store = FakeStore()
    for i in range(1, 6):
        store.add_document(f"M{i}", "CT-S1-MOBFUEL", [_mobile()])
    store.add_document("P1", "CT-S1-MOBFUEL", [_mobile(fuel="gasoline")])
    # #260 chains and a document parked on a line that is gone, written in the old keys
    decisions = {
        "M1": {"placements": [{"from": cl.SUPPORTING_UNASSIGNED, "to": "s1:mobile:diesel-fuel:vg-none"}]},
        "M2": {"placements": [{"from": cl.SUPPORTING_UNASSIGNED, "to": "s1:mobile:diesel-fuel:vg-none-2"}]},
        "M3": {"placements": [{"from": cl.SUPPORTING_UNASSIGNED, "to": "s1:mobile:diesel-fuel:vg-lieferwagen-z-rich-2"},
                              {"from": "s1:mobile:diesel-fuel:vg-lieferwagen-z-rich-2", "to": "block:unassigned"}]},
        "M4": {"placements": [{"from": cl.SUPPORTING_UNASSIGNED, "to": "s1:mobile:diesel-fuel:vg-gone-group"}]},
    }
    assert set(by_anchor) >= {"vg-none", "vg-none-2"}

    def view(groups: list[dict]) -> tuple[Any, Any]:
        tree = _tree(store, decisions, recalculation={"vehicle_groups": groups}, evidenceLines=user_line)
        filing = _lines_with_docs(tree)
        parked = sorted(row["document_id"] for row in tree["blocks"]["supporting"]["unassigned"])
        keys = sorted(line["key"] for line in tree["lines"])
        return (filing, parked, keys, [(g["anchor_id"], g["label"]) for g in tree["vehicle_groups"]],
                tree["blocks"]["unassigned"] == [], tree["set_aside"])

    assert view(LEGACY_GROUPS) == view(migrated)
    legacy_result = recalculation_service(store).recalculate(
        {"id": "ENG-1", "reporting_period_start": "2025-01-01", "reporting_period_end": "2025-12-31",
         "settings": {"facilities": [KC], "recalculation": {"vehicle_groups": LEGACY_GROUPS}}}, _own)
    migrated_result = recalculation_service(store).recalculate(
        {"id": "ENG-1", "reporting_period_start": "2025-01-01", "reporting_period_end": "2025-12-31",
         "settings": {"facilities": [KC], "recalculation": {"vehicle_groups": migrated}}}, _own)
    assert legacy_result == migrated_result
    assert legacy_result["categories"]["mobile_combustion"] is not None


# --- fix round 1: groups with the same name, and a rename plus a reorder, with no ids sent -----------------------
def _bare(groups: list[dict]) -> list[dict]:
    return [{k: v for k, v in g.items() if k != "group_id"} for g in groups]


def _g(label: str, **more: Any) -> dict:
    return {**_group("Diesel Fuel", label), "distance": 1000, "distance_unit": "mi", **more}


def test_two_groups_with_one_name_and_different_figures_keep_their_own_ids_when_reordered_without_ids() -> None:
    stored = _with_ids([_g("Trucks", distance=1000), _g("Trucks", distance=5000)])
    out = _with_ids(_bare(stored)[::-1], stored)
    assert [(g["distance"], g["group_id"]) for g in out] == [(5000, stored[1]["group_id"]), (1000, stored[0]["group_id"])]


def test_a_rename_plus_a_reorder_without_ids_never_hands_a_group_the_id_of_the_group_whose_name_it_took() -> None:
    stored = _with_ids([_g("Trucks", distance=1), _g("Vans", distance=2)])
    trucks, vans = stored
    b = _bare(stored)
    out = _with_ids([{**b[1], "label": "Lorries"}, {**b[0], "label": "Vans"}], stored)
    lorries, new_vans = out
    assert new_vans["group_id"] == trucks["group_id"]  # the group with Trucks' figures, now named Vans
    assert lorries["group_id"] not in (trucks["group_id"], vans["group_id"])  # Vans' id is not given to a rival
    assert len({g["group_id"] for g in out}) == 2


def test_a_rename_without_ids_keeps_the_id_only_when_one_group_fits() -> None:
    stored = _with_ids([_g("Trucks", distance=1), _g("Vans", distance=2)])
    b = _bare(stored)
    renamed = _with_ids([{**b[0], "label": "Haulers"}, b[1]], stored)
    assert _ids(renamed) == _ids(stored)  # unique figures: the same group, renamed
    twins = _with_ids([_g("Trucks"), _g("Trucks")], None)
    both = _with_ids([{**g, "label": "Haulers"} for g in _bare(twins)], twins)
    assert set(_ids(both)).isdisjoint(_ids(twins))  # two groups equally good: neither claims an id


def test_a_group_whose_figures_changed_keeps_its_id_when_it_is_the_only_one_with_that_name() -> None:
    stored = _with_ids([_g("Trucks", distance=1), _g("Vans", distance=2)])
    b = _bare(stored)
    out = _with_ids([{**b[0], "distance": 99}, b[1]], stored)
    assert _ids(out) == _ids(stored)
    same_name = _with_ids([_g("Trucks", distance=1), _g("Trucks", distance=2)])
    ambiguous = _with_ids([{**g, "distance": g["distance"] + 100} for g in _bare(same_name)], same_name)
    assert set(_ids(ambiguous)).isdisjoint(_ids(same_name))  # which is which: not guessed


def test_an_old_anchor_and_a_new_id_are_never_equal_even_for_a_label_that_looks_like_an_id() -> None:
    old = [_group("Diesel Fuel", "id 0123456789ab")]  # legacy anchor: vg-id-0123456789ab
    assert cl.legacy_group_anchors(old) == ["vg-id-0123456789ab"]
    fresh = cl.new_group_id({"vg-id-0123456789ab"})
    assert fresh.startswith("vgid-") and fresh != "vg-id-0123456789ab" and cl.slug(fresh) == fresh


@pytest.mark.parametrize("reverse", [False, True], ids=["in order", "reordered too"])
def test_two_groups_that_swap_names_without_ids_do_not_trade_ids(reverse: bool) -> None:
    stored = _with_ids([_g("Trucks", distance=1), _g("Vans", distance=2)])
    trucks, vans = stored
    b = _bare(stored)
    swapped = [{**b[0], "label": "Vans"}, {**b[1], "label": "Trucks"}]  # the 1 mi group is now Vans, the 2 mi one Trucks
    out = _with_ids(swapped[::-1] if reverse else swapped, stored)
    assert not {g["group_id"] for g in out} & {trucks["group_id"], vans["group_id"]}  # neither takes an old id
    assert len({g["group_id"] for g in out}) == 2  # and they differ


def test_a_name_swap_where_the_client_sends_ids_still_keeps_them() -> None:
    stored = _with_ids([_g("Trucks", distance=1), _g("Vans", distance=2)])
    swapped = [{**stored[0], "label": "Vans"}, {**stored[1], "label": "Trucks"}]
    assert _ids(_with_ids(swapped, stored)) == _ids(stored)  # the ids sent are what a rename keeps


def test_a_group_whose_figures_are_another_unmatched_groups_does_not_take_its_neighbours_id() -> None:
    stored = _with_ids([_g("Trucks", distance=1), _g("Vans", distance=2), _g("Pickups", distance=3)])
    b = _bare(stored)
    # Trucks (1 mi) is renamed Pickups and Pickups (3 mi) kept: the 1 mi group has the figures of stored Trucks
    out = _with_ids([{**b[0], "label": "Vans"}, b[1], b[2]], stored)
    assert out[2]["group_id"] == stored[2]["group_id"]  # Pickups, unchanged, keeps its id
    assert out[0]["group_id"] != stored[1]["group_id"]  # the group named Vans with Trucks' figures does not take Vans'


def test_two_swaps_at_once_each_park_on_a_free_place_of_their_own() -> None:
    default = [cl.Slot("A", {0}), cl.Slot("B", {1}), cl.Slot("C", {2}), cl.Slot("D", {3})]
    where = lambda *pairs: [cl.Slot(t, set(r)) for t, r in pairs]  # noqa: E731
    swapped = where(("B", {0}), ("A", {1}), ("D", {2}), ("C", {3}))  # A and B swap, and so do C and D
    chain = cl.derive_placements(default, swapped)
    assert chain is not None  # two cycles, and fixed places to park them on: no fall-back to the full chain
    known = {"A", "B", "C", "D"}
    assert _resolved(default, chain, known) == sorted((t, tuple(sorted(r)), ()) for t, r in (("B", {0}), ("A", {1}), ("D", {2}), ("C", {3})))
    assert len(chain) <= 2 * len(default)


def test_every_filing_of_three_default_slots_over_three_places_is_derived_when_a_free_place_exists() -> None:
    """Every way three default slots (two records each) can be filed on three lines plus the three fixed
    places: the chain is derived (never the full-chain fall-back) and puts every record where it is filed."""

    import itertools

    default = [cl.Slot("A", {0, 1}), cl.Slot("B", {2, 3}), cl.Slot("C", {4, 5})]
    places = ["A", "B", "C", cl.BLOCK_SUMMARY, cl.BLOCK_UNASSIGNED, cl.SUPPORTING_UNASSIGNED]
    known = {"A", "B", "C"}
    for filing in itertools.product(places, repeat=3):
        used = set(filing) | {"A", "B", "C"}
        wanted = [cl.Slot(place, set(slot.records)) for slot, place in zip(default, filing, strict=True)]
        chain = cl.derive_placements(default, wanted)
        if len(used) < len(places):  # a free fixed place exists: the chain must be derived
            assert chain is not None, filing
        if chain is not None:
            assert _resolved(default, chain, known) == sorted(
                (s.target, tuple(sorted(s.records)), ()) for s in cl.merge_slots(wanted)), filing


def test_a_move_from_all_places_takes_every_place_the_document_is_in_to_the_target() -> None:
    slots = [cl.Slot(GAS_KC, {0}), cl.Slot(GAS_STL, {1}), cl.Slot(cl.BLOCK_SUMMARY, {2})]
    moved = cl.apply_placements(slots, [{"from": cl.ALL_PLACES, "to": ELEC_KC}], {GAS_KC, GAS_STL, ELEC_KC})
    assert [(s.target, s.records) for s in moved] == [(ELEC_KC, {0, 1, 2})]
    # a later move out of the target works as for any place
    back = cl.apply_placements(slots, [{"from": "*", "to": ELEC_KC}, {"from": ELEC_KC, "to": cl.BLOCK_SUMMARY}])
    assert [(s.target, s.records) for s in back] == [(cl.BLOCK_SUMMARY, {0, 1, 2})]
    # a document with no places is untouched, and a bad move is ignored
    assert cl.apply_placements([], [{"from": "*", "to": GAS_KC}]) == []
    assert cl.apply_placements(slots[:1], [{"from": "*", "to": "*"}])[0].target == GAS_KC


def test_each_line_names_the_document_type_it_holds() -> None:
    def line(category: str, level2: str = "x", anchor_kind: str = "facility") -> cl.CalculationLine:
        return cl.make_line(category, level2, level2, anchor_kind, "A", "L", created_by_user=False)

    assert cl.line_type_id(line("stationary")) == "CT-S1-FUELQTY"
    assert cl.line_type_id(line("biogenic")) == "CT-S1-FUELQTY"
    assert cl.line_type_id(line("biogenic", anchor_kind="vehicle_group")) == "CT-S1-MOBFUEL"
    assert cl.line_type_id(line("mobile", anchor_kind="vehicle_group")) == "CT-S1-MOBFUEL"
    assert cl.line_type_id(line("fugitive")) == "CT-S1-REFRSVC"
    assert cl.line_type_id(line("purchased_energy", "electricity")) == "CT-S2-ELEC"
    assert cl.line_type_id(line("purchased_energy", "steam")) == "CT-S2-THERMAL"
    assert cl.line_type_id(line("process")) is None
    assert cl.line_type_id(line("contractual", anchor_kind="company")) is None
