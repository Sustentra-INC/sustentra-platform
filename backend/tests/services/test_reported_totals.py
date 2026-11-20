"""The emissions a company reports in its summary document: the table reader (a Yum-shaped statement and a
JPMorgan-shaped table), units, what an accepted figure feeds and that it never touches the recalculated side."""

from __future__ import annotations

from typing import Any

import pytest

from backend.app.reference.extraction_config_loader import load_default_extraction_configs
from backend.app.services import emissions_rollup as rollup
from backend.app.services import reported_totals as rt
from backend.app.services.extraction_target_service import ExtractionTargetService
from backend.tests.services.recalc_store import RecalcStore, recalculate

TARGETS = ExtractionTargetService().get_targets_for_canonical_type(rt.WORKBOOK_TYPE_ID)


# --- a parser output with boxes, shaped like Yum's "GHG Emissions by scope and type of gas" ---------------------
def block(n: int, text: str, x: float, y: float, w: float = 0.08, h: float = 0.012, page: int = 3) -> dict[str, Any]:
    return {"block_id": f"b{n}", "page_number": page, "text": text, "source_reference_id": f"s{n}",
            "bounding_box": {"left": x, "top": y, "width": w, "height": h}}


def parser_output(blocks: list[dict[str, Any]], tables: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    refs = [{"source_reference_id": b["source_reference_id"], "document_id": "d1", "page_number": b["page_number"],
             "text_snippet": b["text"], "bounding_box": {"x": b["bounding_box"]["left"], "y": b["bounding_box"]["top"],
                                                         "width": b["bounding_box"]["width"],
                                                         "height": b["bounding_box"]["height"]},
             "parser_block_ids": [b["block_id"]], "source_kind": "line_text"} for b in blocks]
    return {"document_id": "d1", "text_blocks": blocks, "source_references": refs, "tables": tables or [],
            "key_value_pairs": []}


COLS = [0.40, 0.50, 0.60, 0.70, 0.82]  # CO2 CH4 N2O HFC Total


def yum_blocks(scope2_label: tuple[str, ...] = ("Scope 2", "(location-based)"), unit: str = "Emissions MTCO₂e") -> list[dict[str, Any]]:
    out = [block(1, "GHG Emissions by scope and type of gas in metric tons of carbon dioxide equivalent", 0.1, 0.20, 0.8),
           block(2, unit, 0.40, 0.25, 0.4)]
    for i, head in enumerate(["CO₂", "CH₄", "N₂O", "HFC", "Total CO₂e"]):
        out.append(block(10 + i, head, COLS[i], 0.28, 0.07))
    rows = [(0.32, ("Scope 1",), ["34,128", "19", "21", "4,754", "38,922"]),
            (0.37, scope2_label, ["104,634", "189", "366", "N/A", "105,189"]),
            (0.43, ("Scope 3 (location-based)",), [None, None, None, None, "30,660,751"])]
    n = 100
    for y, label, cells in rows:
        for j, text in enumerate(label):  # a two-line label is two blocks, the numbers sit between them
            out.append(block(n := n + 1, text, 0.10, y + (0.0 if len(label) == 1 else (j * 0.012 - 0.006)), 0.2))
        for i, text in enumerate(cells):
            if text:
                out.append(block(n := n + 1, text, COLS[i], y, 0.07))
    return out


def read(blocks: list[dict[str, Any]], tables: list[dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    outcome = rt.ReportedTotalsExtractor().extract(parser_output(blocks, tables), TARGETS, "ev1")
    read.notes = outcome.notes  # type: ignore[attr-defined]
    return {c["field_name"]: c for c in outcome.candidates}


def test_the_yum_table_is_read_cell_by_cell_with_a_highlight_each() -> None:
    got = read(yum_blocks())
    assert [got[f]["normalized_value"] for f in ("scope1_co2", "scope1_ch4", "scope1_n2o", "scope1_hfcs", "scope1_total")] \
        == [34128, 19, 21, 4754, 38922]
    assert [got[f]["normalized_value"] for f in ("scope2_co2", "scope2_ch4", "scope2_n2o", "scope2_location_total")] \
        == [104634, 189, 366, 105189]
    assert got["scope1_co2"]["raw_value"] == "34,128" and got["scope1_total"]["unit"] == "tCO2e"
    assert any(f.startswith("unit_as_printed:") and "MTCO2e" in f for f in got["scope1_total"]["validation_flags"])
    box = got["scope1_co2"]["source_reference"]["bounding_box"]  # the cell's own box: it is outlined on the PDF
    assert box["x"] == pytest.approx(0.40) and box["y"] == pytest.approx(0.32)
    assert got["scope1_co2"]["source_reference"]["text_snippet"] == "34,128"


def test_na_is_not_reported_never_zero() -> None:
    cell = read(yum_blocks())["scope2_hfcs"]
    assert cell["raw_value"] == "N/A" and cell["normalized_value"] is None and cell["unit"] is None
    assert "not_reported" in cell["validation_flags"]


def test_a_two_line_label_and_a_lone_total_are_read_and_scope_3_is_reported_only() -> None:
    got = read(yum_blocks())
    assert got["scope2_location_total"]["normalized_value"] == 105189  # "Scope 2" + "(location-based)"
    assert got["scope3_total"]["normalized_value"] == 30660751
    assert rt.is_reported_only("scope3_total") and "scope3_total" not in rollup.FINAL_OUTPUT_KEYS
    assert got["scope3_co2"]["normalized_value"] is None and got["scope3_co2"]["raw_value"] is None


def test_a_bare_scope_2_row_with_no_basis_is_not_read() -> None:
    got = read(yum_blocks(scope2_label=("Scope 2",)))
    assert all(got[f]["raw_value"] is None for f in ("scope2_co2", "scope2_location_total", "scope2_market_total"))
    assert got["scope1_total"]["normalized_value"] == 38922


def test_a_sentence_is_not_a_table_and_nothing_is_guessed_from_it() -> None:
    blocks = [block(1, "Our Scope 1 emissions were 38,922 MTCO2e in 2023, up from 36,000.", 0.1, 0.3, 0.8)]
    assert all(c["raw_value"] is None for c in read(blocks).values())


def test_no_unit_printed_keeps_the_value_with_no_unit_and_never_converts() -> None:
    blocks = [b for b in yum_blocks() if b["block_id"] not in ("b1", "b2")]
    cell = read(blocks)["scope1_total"]
    assert cell["normalized_value"] == 38922 and cell["unit"] is None and "unit_missing" in cell["validation_flags"]


def test_two_different_units_near_a_table_read_no_unit() -> None:
    blocks = yum_blocks() + [block(90, "ktCO2e", 0.93, 0.33, 0.05)]
    assert read(blocks)["scope1_total"]["unit"] is None


def test_year_columns_are_not_read_because_the_year_is_not_chosen() -> None:  # JPMorgan-shaped
    blocks = [block(1, "tCO2e", 0.1, 0.2, 0.1), block(2, "2023", 0.5, 0.25, 0.06), block(3, "2022", 0.65, 0.25, 0.06),
              block(4, "Scope 1", 0.1, 0.3), block(5, "1,000", 0.5, 0.3, 0.06), block(6, "1,100", 0.65, 0.3, 0.06)]
    got = read(blocks)
    assert all(c["raw_value"] is None for c in got.values())
    assert any("several year columns" in n for n in read.notes)  # type: ignore[attr-defined]


def test_a_workbook_or_textract_table_with_one_value_per_row_reads_totals_with_the_unit_in_its_header() -> None:
    table = {"table_id": "t1", "page_number": 4, "sheet_name": None, "source_reference_id": None, "rows": [
        ["Emissions (metric tons CO2e)", "2023"], ["Scope 1", "2,100"], ["Scope 2 – market-based", "900"],
        ["Scope 3", "N/A"]]}
    got = read([], [table])
    assert got["scope1_total"]["normalized_value"] == 2100 and got["scope1_total"]["unit"] == "tCO2e"
    # "Scope 2 - market-based" with an en dash is not an exact row name here: nothing is guessed
    assert got["scope2_market_total"]["raw_value"] is None
    assert got["scope3_total"]["raw_value"] == "N/A" and got["scope3_total"]["normalized_value"] is None


def test_a_gas_by_scope_table_in_rows_is_read_by_column_position() -> None:
    table = {"table_id": "t1", "page_number": 2, "sheet_name": "Summary", "source_reference_id": None, "rows": [
        ["Metric tons CO2e", "CO₂", "CH₄", "N₂O", "HFC", "Total CO₂e"],
        ["Scope 1", "34,128", "19", "21", "4,754", "38,922"],
        ["Scope 2\n(location-based)", "104,634", "189", "366", "N/A", "105,189"]]}
    got = read([], [table])
    assert got["scope1_hfcs"]["normalized_value"] == 4754 and got["scope2_location_total"]["normalized_value"] == 105189
    assert got["scope2_hfcs"]["normalized_value"] is None and "not_reported" in got["scope2_hfcs"]["validation_flags"]


# --- units ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text,label", [
    ("MTCO₂e", "tCO2e"), ("MT CO2e", "tCO2e"), ("metric tons CO2e", "tCO2e"), ("Metric tons of carbon dioxide equivalent", "tCO2e"),
    ("tCO2e", "tCO2e"), ("tonnes CO2-e", "tCO2e"), ("MtCO2e", "MtCO2e"), ("MMTCO2e", "MtCO2e"),
    ("million metric tons CO2e", "MtCO2e"), ("ktCO2e", "ktCO2e"), ("kgCO2e", "kgCO2e")])
def test_units_are_read(text: str, label: str) -> None:
    unit = rt.parse_unit(text)
    assert unit is not None and unit.label == label and unit.co2e


@pytest.mark.parametrize("text", ["mtco2e", "tons CO2e", "short tons CO2e", "CO2e", "metric tons", "", "thousand tCO2e of"])
def test_an_ambiguous_or_unknown_unit_is_not_read(text: str) -> None:
    assert rt.parse_unit(text) is None


def test_mtco2e_normalises_to_tonnes_and_plain_mass_only_for_a_gas() -> None:
    mega, metric = rt.parse_unit("MtCO2e"), rt.parse_unit("MTCO2e")
    assert mega is not None and metric is not None
    assert rt.to_tonnes(1.2, mega) == pytest.approx(1_200_000) and rt.to_tonnes(34128, metric) == 34128
    assert rt.parse_unit("metric tons") is None
    plain = rt.parse_unit("metric tons", mass=True)
    assert plain is not None and plain.label == "t" and not plain.co2e


# --- what an accepted figure feeds -----------------------------------------------------------------------------
DOC = {"document_id": "d1", "file_name": "statement.pdf"}


def item(name: str, value: Any, unit: str | None = "tCO2e", page: int = 3, flags: list[str] | None = None) -> dict[str, Any]:
    return {"field_name": name, "normalized_value": value, "unit": unit, "display_label": name,
            "validation_flags": flags or [], "source_reference": {"page_number": page}}


def accepted(**over: Any) -> dict[str, Any]:
    return {"decision": "accepted", **over}


def test_only_accepted_or_corrected_figures_count() -> None:
    it = item("scope1_total", 38922)
    assert rt.figure_of(it, None, DOC) is None
    assert rt.figure_of(it, {"decision": "rejected"}, DOC) is None
    assert rt.figure_of(it, {"decision": "needs_more_evidence"}, DOC) is None
    assert rt.figure_of(item("scope1_total", 38922, flags=["ai_suggested"]), None, DOC) is None
    figure = rt.figure_of(it, accepted(), DOC)
    assert figure is not None and figure.value_t == 38922 and figure.page == 3 and figure.document_id == "d1"
    corrected = rt.figure_of(it, {"decision": "edited", "reviewed_value": 40000}, DOC)
    assert corrected is not None and corrected.value_t == 40000


def test_a_figure_in_mtco2e_is_normalised_and_keeps_what_was_printed() -> None:
    figure = rt.figure_of(item("scope1_total", 1.2, "MtCO2e"), accepted(), DOC)
    assert figure is not None and figure.value_t == pytest.approx(1_200_000) and figure.printed == "1.2 MtCO2e"


def test_not_reported_unitless_and_wrong_unit_figures_feed_nothing() -> None:
    assert rt.figure_of(item("scope2_hfcs", None, None), accepted(), DOC) is None  # N/A
    assert rt.figure_of(item("scope1_total", 5, None), accepted(), DOC) is None  # no unit
    assert rt.figure_of(item("scope1_total", 5, "t"), accepted(), DOC) is None  # tonnes of what? never guessed
    assert rt.figure_of(item("reporting_year", 2023, None), accepted(), DOC) is None  # not a data point
    gas = rt.figure_of(item("scope1_ch4", 19, "t"), accepted(), DOC)
    assert gas is not None and gas.unit_choice == "t"
    assert rt.figure_of(item("scope1_ch4", 19, "tCO2e"), accepted(), DOC).unit_choice == "t CO2e"  # type: ignore[union-attr]


def figures(*items: tuple[str, float, str]) -> list[rt.DocumentFigure]:
    return [f for name, value, unit in items if (f := rt.figure_of(item(name, value, unit), accepted(), DOC))]


def test_a_manual_entry_wins_and_a_difference_is_flagged() -> None:
    reported, units, sources, only = rt.overlay({"scope1_total": 40000.0}, {}, figures(("scope1_total", 38922, "tCO2e")))
    assert reported["scope1_total"] == 40000.0
    assert sources["scope1_total"]["used"] == "manual" and sources["scope1_total"]["differs"] is True
    assert sources["scope1_total"]["document"]["page"] == 3 and only == []
    same = rt.overlay({"scope1_total": 38922.0}, {}, figures(("scope1_total", 38922, "tCO2e")))[2]
    assert same["scope1_total"]["differs"] is False


def test_a_document_figure_fills_what_nobody_typed_and_sets_its_unit() -> None:
    reported, units, sources, _ = rt.overlay({}, {}, figures(("scope1_total", 38922, "tCO2e"), ("scope1_ch4", 19, "t")))
    assert reported == {"scope1_total": 38922, "scope1_ch4": 19}
    assert units == {"scope1_ch4": "t"} and sources["scope1_ch4"]["used"] == "document"


def test_scope_3_is_reported_only_never_a_comparison_input() -> None:
    reported, _, sources, only = rt.overlay({}, {}, figures(("scope3_total", 30660751, "tCO2e")))
    assert reported == {} and sources == {} and [o["key"] for o in only] == ["scope3_total"]


def test_two_documents_that_disagree_feed_nothing() -> None:
    other = rt.figure_of(item("scope1_total", 99), accepted(), {"document_id": "d2", "file_name": "b.pdf"})
    assert other is not None
    reported, _, sources, _ = rt.overlay({}, {}, [*figures(("scope1_total", 38922, "tCO2e")), other])
    assert "scope1_total" not in reported and len(sources["scope1_total"]["conflict"]) == 2


# --- through the real recalculation: the Reported side moves, the recalculated side never does ------------------
def summary_store(decision: str | None) -> RecalcStore:
    store = RecalcStore()
    store.add("elec", [{"consumption": (1000, "kWh")}], "CT-S2-ELEC")
    store.documents.append({"document_id": "sum", "engagement_id": "ENG-1", "org_id": "org-a", "file_name": "statement.pdf"})
    items = [{"candidate_id": "sum:scope1_total", "record_index": None, **item("scope1_total", 38922)},
             {"candidate_id": "sum:scope1_ch4", "record_index": None, **item("scope1_ch4", 19, "t")}]
    for i in items:
        i["document_id"] = "sum"
        i["source_reference"] = {"document_id": "sum", "page_number": 3}
    store.results["sum"] = [{"document_id": "sum", "org_id": "org-a", "canonical_type_id": "CT-GHG-WORKBOOK", "items": items}]
    store.reviews["sum"] = [] if decision is None else [
        {"candidate_id": i["candidate_id"], "document_id": "sum", "decision": decision, "org_id": "org-a", "reviewed_value": i["normalized_value"],
         "reviewed_unit": i["unit"]}
        for i in items]
    return store


def comparison(result: dict, key: str) -> dict:
    return next(c for c in result["comparisons"] if c["key"] == key)


def test_an_accepted_figure_feeds_reported_only_and_never_the_recalculated_side() -> None:
    before, after = recalculate(summary_store(None)), recalculate(summary_store("accepted"))
    assert comparison(before, "scope1_total")["reported"] is None
    assert comparison(after, "scope1_total")["reported"] == 38922
    assert comparison(after, "scope1_total")["reported_source"]["document"]["page"] == 3
    assert after["reported_sources"]["scope1_total"]["used"] == "document"
    for key in ("scope1_total", "scope1_ch4", "scope2_location_total"):
        assert comparison(after, key)["recalculated"] == comparison(before, key)["recalculated"]
    assert after["categories"] == before["categories"] and after["scope_totals"] == before["scope_totals"]
    assert after["documents_considered"] == before["documents_considered"]
    final = {o["key"]: o for o in after["rollup"]["final_outputs"]}
    assert final["scope1_total"]["reported"] == 38922 and final["scope1_ch4"]["reported_unit"] == "t"
    assert {o["key"]: o["recalculated"] for o in before["rollup"]["final_outputs"]} == {k: o["recalculated"] for k, o in final.items()}


def test_a_rejected_or_undecided_figure_feeds_nothing() -> None:
    for decision in (None, "rejected"):
        result = recalculate(summary_store(decision))
        assert comparison(result, "scope1_total")["reported"] is None and result["reported_sources"] == {}


def test_a_manual_entry_is_never_overwritten_by_the_document() -> None:
    store = summary_store("accepted")
    engagement = {"id": "ENG-1", "reporting_period_start": "2025-01-01", "reporting_period_end": "2025-12-31",
                  "settings": {"facilities": [], "recalculation": {"reported": {"scope1_total": 50000}}}}
    from backend.app.services.engagement_recalculation_service import EngagementRecalculationService

    result = EngagementRecalculationService(store, store, store).recalculate(engagement, lambda r: r.get("org_id") == "org-a")
    assert comparison(result, "scope1_total")["reported"] == 50000
    assert result["reported_sources"]["scope1_total"] | {"used": "manual"} == result["reported_sources"]["scope1_total"]
    assert result["reported_sources"]["scope1_total"]["differs"] is True
    assert engagement["settings"]["recalculation"]["reported"] == {"scope1_total": 50000}


# --- the template ----------------------------------------------------------------------------------------------
def test_the_template_covers_both_summary_types_with_roll_up_keys_and_small_schemas() -> None:
    names = [t["field_id"] for t in TARGETS]
    assert len(names) == len(set(names)) == 40
    reported = [n for n in names if n not in ("reporting_year", "reported_unit") and not rt.is_reported_only(n)]
    assert set(reported) <= rollup.FINAL_OUTPUT_KEYS
    meth = ExtractionTargetService().get_targets_for_canonical_type(rt.METHODDOC_TYPE_ID)
    assert [t["field_id"] for t in meth] == names
    assert {c.canonical_type_id for c in load_default_extraction_configs() if c.field_id == "scope1_total"} == rt.REPORTED_TYPES

    from backend.app.services import ai_extraction
    from backend.tests.services.test_methodology_prefill import MAX_FLAT_SCHEMA_BYTES, _measure

    sizes = _measure(ai_extraction.reading_output(tuple(names)))
    assert sizes["bytes"] <= MAX_FLAT_SCHEMA_BYTES and sizes["unions"] == 0 and sizes["unsupported"] == 0, sizes
