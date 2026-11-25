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
    out = [block(1, "2023 GHG Emissions by scope and type of gas in metric tons of carbon dioxide equivalent", 0.1, 0.20, 0.8),
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
    assert "year:2023" in got["scope1_total"]["validation_flags"] and got["reporting_year"]["normalized_value"] == 2023


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
        ["Emissions (metric tons CO2e)", "2023"], ["Scope 1", "2,100"], ["Scope 3", "N/A"],
        ["Scope 2 – market-based", "900"]]}
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


def item(name: str, value: Any, unit: str | None = "tCO2e", page: int = 3, flags: list[str] | None = None,
         year: int | None = 2025) -> dict[str, Any]:
    return {"field_name": name, "normalized_value": value, "unit": unit, "display_label": name,
            "validation_flags": [*(flags or []), *([f"year:{year}"] if year else [])],
            "source_reference": {"page_number": page}}


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


YEARS = {2025}


def figures(*items: tuple[str, float, str]) -> list[rt.DocumentFigure]:
    return [f for name, value, unit in items if (f := rt.figure_of(item(name, value, unit), accepted(), DOC))]


def test_a_manual_entry_wins_and_a_difference_is_flagged() -> None:
    reported, units, sources, only = rt.overlay({"scope1_total": 40000.0}, {}, figures(("scope1_total", 38922, "tCO2e")), YEARS)
    assert reported["scope1_total"] == 40000.0
    assert sources["scope1_total"]["used"] == "manual" and sources["scope1_total"]["differs"] is True
    assert sources["scope1_total"]["document"]["page"] == 3 and only == []
    same = rt.overlay({"scope1_total": 38922.0}, {}, figures(("scope1_total", 38922, "tCO2e")), YEARS)[2]
    assert same["scope1_total"]["differs"] is False


def test_a_document_figure_fills_what_nobody_typed_and_sets_its_unit() -> None:
    reported, units, sources, _ = rt.overlay({}, {}, figures(("scope1_total", 38922, "tCO2e"), ("scope1_ch4", 19, "t")), YEARS)
    assert reported == {"scope1_total": 38922, "scope1_ch4": 19}
    assert units == {"scope1_ch4": "t"} and sources["scope1_ch4"]["used"] == "document"


def test_scope_3_is_reported_only_never_a_comparison_input() -> None:
    reported, _, sources, only = rt.overlay({}, {}, figures(("scope3_total", 30660751, "tCO2e")), YEARS)
    assert reported == {} and sources == {} and [o["key"] for o in only] == ["scope3_total"]


def test_two_documents_that_disagree_feed_nothing() -> None:
    other = rt.figure_of(item("scope1_total", 99), accepted(), {"document_id": "d2", "file_name": "b.pdf"})
    assert other is not None
    reported, _, sources, _ = rt.overlay({}, {}, [*figures(("scope1_total", 38922, "tCO2e")), other], YEARS)
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


# --- review findings: scale words, headers about another measure, years, single columns, stacked tables, MT -------
def with_unit_text(text: str) -> list[dict[str, Any]]:
    return [b for b in yum_blocks() if b["block_id"] not in ("b1", "b2")] + [block(2, text, 0.40, 0.25, 0.4)]


@pytest.mark.parametrize("caption,label", [
    ("Emissions (thousand tCO2e)", "ktCO2e"), ("tCO2e (in thousands)", "ktCO2e"), ("Emissions tCO2e '000", "ktCO2e"),
    ("Emissions (000s) tCO2e", "ktCO2e"), ("Emissions (thousands of metric tons CO2e)", "ktCO2e"),
    ("Emissions (million tCO2e)", "MtCO2e"), ("tCO2e (in millions)", "MtCO2e"), ("MM tCO2e", "MtCO2e"),
    ("m tCO2e", "MtCO2e"), ("k tCO2e", "ktCO2e"), ("million metric tons CO2e", "MtCO2e")])
def test_a_printed_scale_is_never_read_as_plain_tonnes(caption: str, label: str) -> None:
    unit, _, problem = rt.read_unit([caption])
    assert (unit, problem) == (label, None)
    cell = read(with_unit_text(caption))["scope1_total"]  # through the page reader: kt of 38,922, not t
    assert cell["unit"] == label and cell["normalized_value"] == 38922
    figure = rt.figure_of(item("scope1_total", 38922, label), accepted(), DOC)
    assert figure is not None and figure.value_t == 38922 * rt.UNITS[label].factor


@pytest.mark.parametrize("captions", [["Emissions (thousand ktCO2e)"], ["Emissions (thousand tCO2e)", "(in millions)"],
                                      ["Emissions (thousand kgCO2e)"]])
def test_an_ambiguous_scale_reads_no_unit_and_says_so(captions: list[str]) -> None:
    unit, _, problem = rt.read_unit(captions)
    assert unit is None and problem == "scale"
    cell = read(with_unit_text(captions[0]) + [block(91, c, 0.1, 0.46, 0.3) for c in captions[1:]])["scope1_total"]
    assert cell["unit"] is None and cell["normalized_value"] == 38922 and "unit_unclear" in cell["validation_flags"]


@pytest.mark.parametrize("caption", ["Emissions intensity (tCO2e per $M revenue)", "Emissions (tCO2e / $M revenue)",
                                     "tCO2e per employee", "Revenue-based emissions tCO2e", "Intensity tCO2e"])
def test_a_header_with_a_denominator_or_intensity_is_not_read_at_all(caption: str) -> None:
    assert rt.read_unit([caption])[2] == "measure"
    assert all(c["raw_value"] is None for c in read(with_unit_text(caption)).values())
    table = {"table_id": "t", "page_number": 1, "sheet_name": None, "source_reference_id": None,
             "rows": [[caption, "Total CO₂e"], ["Scope 1", "5"]]}
    assert all(c["raw_value"] is None for c in read([], [table]).values())


def test_a_column_about_another_measure_names_nothing_but_the_others_are_read() -> None:
    table = {"table_id": "t", "page_number": 1, "sheet_name": None, "source_reference_id": None, "rows": [
        ["tCO2e", "CO2", "Total CO2e", "tCO2e / $M revenue"], ["Scope 1", "10", "12", "3"]]}
    got = read([], [table])
    assert got["scope1_co2"]["normalized_value"] == 10 and got["scope1_total"]["normalized_value"] == 12
    assert all(got[f]["raw_value"] is None for f in ("scope2_total",) if f in got)


@pytest.mark.parametrize("text,label", [("MT CO2e", "tCO2e"), ("mT CO2e", "tCO2e"), ("MTCO2e", "tCO2e"),
                                        ("Mt CO2e", "MtCO2e"), ("MtCO2e", "MtCO2e"), ("million tonnes CO2e", "MtCO2e")])
def test_mt_is_metric_tonnes_and_mt_is_megatonnes(text: str, label: str) -> None:
    assert rt.read_unit([text])[:3:2] == (label, None)


@pytest.mark.parametrize("text", ["mt CO2e", "tons CO2e", "short tons CO2e", "tons of carbon dioxide equivalent"])
def test_an_unclear_unit_is_not_converted_and_is_flagged(text: str) -> None:
    assert rt.read_unit([text]) == (None, text, "unclear")
    cell = read(with_unit_text(text))["scope1_total"]
    assert cell["unit"] is None and "unit_unclear" in cell["validation_flags"] and cell["normalized_value"] == 38922


def test_a_single_value_column_is_a_total_only_when_it_says_so() -> None:
    def table(*header: list[str]) -> dict[str, Any]:
        return {"table_id": "t", "page_number": 1, "sheet_name": None, "source_reference_id": None,
                "rows": [*header, ["Scope 1", "2,100"]]}

    assert read([], [table(["Emissions (tCO2e)", "2023"])])["scope1_total"]["normalized_value"] == 2100
    assert read([], [table(["Total (metric tons CO2e)"])])["scope1_total"]["normalized_value"] == 2100
    for header in (["Biogenic emissions (tCO2e)", "2023"], ["Emissions intensity (tCO2e)", "2023"],
                   ["Change in emissions (tCO2e)", "2023"], ["Target emissions (tCO2e)", "2023"], ["Scope", "2023"],
                   ["Emissions", "2023"], ["Share of emissions (%)", "2023"]):
        assert read([], [table(header)])["scope1_total"]["raw_value"] is None, header
    assert any("not named as a total" in n for n in read.notes)  # type: ignore[attr-defined]


def test_two_tables_stacked_on_a_page_are_read_each_through_its_own_header() -> None:
    first = yum_blocks()
    second = [block(300, "Emissions (thousand tCO2e)", 0.40, 0.58, 0.4)]
    for i, head in enumerate(["CO\u2082", "N\u2082O", "Total CO\u2082e"]):  # other columns, in other places
        second.append(block(310 + i, head, [0.40, 0.55, 0.82][i], 0.62, 0.07))
    second += [block(320, "Scope 2 (market-based)", 0.10, 0.66, 0.2)] + [block(321 + i, t, [0.40, 0.55, 0.82][i], 0.66, 0.07)
                                                                       for i, t in enumerate(["7", "8", "9"])]
    got = read(first + second)
    assert got["scope1_co2"]["normalized_value"] == 34128 and got["scope1_n2o"]["normalized_value"] == 21
    assert got["scope1_total"]["unit"] == "tCO2e"  # the first table keeps its own unit
    assert (got["scope2_market_n2o"]["normalized_value"], got["scope2_market_total"]["normalized_value"]) == (8, 9)
    assert got["scope2_market_total"]["unit"] == "ktCO2e"  # the second has its own: nothing is shared
    assert got["scope2_market_ch4"]["raw_value"] is None  # CH4 is not a column of the second table


def test_stacked_tables_of_a_grid_do_not_share_a_header_or_a_unit() -> None:
    rows = [["Emissions (thousand tCO2e)", "CO2", "Total CO2e"], ["Scope 1", "1", "2"],
            ["Emissions (tCO2e)", "CH4", "Total CO2e"], ["Scope 2 (location-based)", "5", "6"]]
    got = read([], [{"table_id": "t", "page_number": 1, "sheet_name": None, "source_reference_id": None, "rows": rows}])
    assert got["scope1_total"]["unit"] == "ktCO2e" and got["scope1_co2"]["normalized_value"] == 1
    assert got["scope2_location_total"]["unit"] == "tCO2e" and got["scope2_ch4"]["normalized_value"] == 5
    assert got["scope2_co2"]["raw_value"] is None  # CO2 is not a column of the second table


# --- the reporting year ----------------------------------------------------------------------------------------
def test_a_figure_of_another_year_is_never_fed_and_says_so() -> None:
    old = rt.figure_of(item("scope1_total", 38922, year=2023), accepted(), DOC)
    assert old is not None and old.year == 2023
    reported, _, sources, _ = rt.overlay({}, {}, [old], {2025})
    assert reported == {} and sources["scope1_total"]["excluded"] == "Different year (2023) — not compared"
    assert sources["scope1_total"]["used"] is None and sources["scope1_total"]["document"]["year"] == 2023


def test_a_figure_with_no_year_is_not_fed_unless_the_document_states_one() -> None:
    bare = rt.figure_of(item("scope1_total", 38922, year=None), accepted(), DOC)
    assert bare is not None and bare.year is None
    assert rt.overlay({}, {}, [bare], {2025})[2]["scope1_total"]["excluded"] == "Year not stated"
    stated = rt.figure_of(item("scope1_total", 38922, year=None), accepted(), DOC, doc_year=2025)
    assert stated is not None and rt.overlay({}, {}, [stated], {2025})[0] == {"scope1_total": 38922}
    assert rt.overlay({}, {}, [rt.figure_of(item("scope1_total", 1, year=None), accepted(), DOC, doc_year=2023)], {2025})[0] == {}  # type: ignore[list-item]


def test_the_year_the_reviewer_accepted_for_the_document_is_used() -> None:
    items = [item("reporting_year", 2025, None, year=None), item("scope1_total", 5, year=None)]
    assert rt.document_year(items, [accepted(), accepted()]) == 2025
    assert rt.document_year(items, [{"decision": "rejected"}, accepted()]) is None
    assert rt.document_year(items, [None, None]) is None
    assert rt.document_year(items, [{"decision": "edited", "reviewed_value": 2024}, None]) == 2024


def test_without_a_reporting_period_nothing_is_compared() -> None:
    figure = rt.figure_of(item("scope1_total", 38922), accepted(), DOC)
    assert figure is not None and rt.overlay({}, {}, [figure], None)[0] == {}
    assert "period" in rt.overlay({}, {}, [figure], None)[2]["scope1_total"]["excluded"]


def test_the_periods_years() -> None:
    from datetime import date

    assert rt.period_years(date(2025, 1, 1), date(2025, 12, 31)) == {2025}
    assert rt.period_years(date(2024, 7, 1), date(2025, 6, 30)) == {2025}  # a fiscal year is named by the year it ends
    assert rt.period_years(None, None) is None


def test_a_wrong_year_figure_stays_off_the_reported_side_through_the_recalculation() -> None:
    store = summary_store("accepted")
    for it in store.results["sum"][0]["items"]:
        it["validation_flags"] = ["year:2023"]
    result = recalculate(store)
    assert comparison(result, "scope1_total")["reported"] is None
    shown = comparison(result, "scope1_total")["reported_source"]
    assert shown["excluded"] == "Different year (2023) — not compared" and shown["used"] is None
    for it in store.results["sum"][0]["items"]:
        it["validation_flags"] = []
    assert comparison(recalculate(store), "scope1_total")["reported_source"]["excluded"] == "Year not stated"


def test_a_bare_single_year_column_that_is_not_the_period_is_not_fed() -> None:
    table = {"table_id": "t", "page_number": 1, "sheet_name": None, "source_reference_id": None,
             "rows": [["Emissions (tCO2e)", "2023"], ["Scope 1", "2,100"]]}
    cell = read([], [table])["scope1_total"]
    assert "year:2023" in cell["validation_flags"] and read([], [table])["reporting_year"]["normalized_value"] == 2023
    figure = rt.figure_of({**cell, "field_name": "scope1_total"}, accepted(), DOC)
    assert figure is not None and rt.overlay({}, {}, [figure], {2025})[0] == {}


# --- a company's own GHG workbook: scope rows with facility columns and a Total column, or facility rows with a
# --- Total row (EXT-031). Synthetic sheets built by the workbook parser itself, so every cell has its coordinate. ----
def sheet_output(*sheets: tuple[str, list[list[Any]]]) -> dict[str, Any]:
    from backend.app.adapters.parsers.excel_parser import parser_output_from_sheets
    from openpyxl.utils import get_column_letter

    def cells(rows: list[list[Any]]) -> list[list[tuple[str | None, Any]]]:
        return [[(None if v is None else f"{get_column_letter(c + 1)}{r + 1}", v) for c, v in enumerate(row)]
                for r, row in enumerate(rows)]

    return parser_output_from_sheets([(name, cells(rows)) for name, rows in sheets], parser_name="openpyxl",
                                     document_id="d1", processing_run_id="r1")


def read_sheet(rows: list[list[Any]], sheet: str = "Summary") -> dict[str, dict[str, Any]]:
    outcome = rt.ReportedTotalsExtractor().extract(sheet_output((sheet, rows)), TARGETS, "ev1")
    read.notes = outcome.notes  # type: ignore[attr-defined]
    return {c["field_name"]: c for c in outcome.candidates}


def values(got: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {k: c["normalized_value"] for k, c in got.items() if c["raw_value"] is not None and k != "reporting_year"}


def cell_of(candidate: dict[str, Any]) -> tuple[str | None, str | None]:
    ref = candidate["source_reference"]
    return ref.get("sheet_name"), ref.get("cell_or_range")


STG = [
    ["Test Foods Inc. - GHG Inventory Summary, Reporting Year 01/01/2025 - 12/31/2025", None, None, None, None, None],
    ["Prepared by: Corporate Sustainability (internal). Status: DRAFT v3, 01/30/2026. Units: metric tonnes CO2e.",
     None, None, None, None, None],
    [None] * 6,
    ["Scope", "Category", "Riverside Plant", "Harbor Warehouse", "Total (tCO2e)", "Method / notes"],
    ["Scope 1", "Stationary combustion", 698.4, 176.2, 874.6, "Natural gas, propane; EPA factors"],
    ["Scope 1", "Mobile combustion", 0, 251.7, 251.7, "Fleet fuel"],
    ["Scope 1", "Fugitive (refrigerants)", 54, 127.3, 181.3, "Mass balance; AR5 GWPs"],
    ["Scope 2", "Location-based", 545.8, 46.1, 591.9, "eGRID factors"],
    ["Scope 2", "Market-based", 402.6, 38.9, 441.5, "Supplier-specific rates"],
    ["Scope 1", "Total Scope 1", 752.4, 555.2, 1307.6, None],
    ["Scope 1+2", "Total (location-based)", 1298.2, 601.3, 1899.5, None],
    ["Scope 1+2", "Total (market-based)", 1155, 594.1, 1749.1, None],
    [None] * 6,
    ["SAMPLE - FICTIONAL TEST DOCUMENT", None, None, None, None, None],
]

NPL = [
    ["Northgate Provisions Inc. - 2025 GHG Inventory Summary (DRAFT, internal)", None, None, None, None],
    ["Prepared by: Sustainability team - 02/10/2026 - Not verified - Basis: EPA emission factors hub 2025", None, None, None, None],
    [None] * 5,
    ["Facility", "Scope 1 (tCO₂e)", "Scope 2 location-based (tCO₂e)", "Scope 2 market-based (tCO₂e)", "Total Scope 1+2 (tCO₂e)"],
    ["Fresno Plant", 412.8, 1046.3, 978.5, 1459.1],
    ["Sacramento Warehouse", 236.4, 147.9, 131.2, 384.3],
    ["Tacoma Distribution Center", 318.7, 98.6, 22.4, 417.3],
    ["Total", 967.9, 1292.8, 1132.1, 2260.7],
    [None] * 5,
    ["SAMPLE - FICTIONAL TEST DOCUMENT", None, None, None, None],
]


def test_scope_rows_with_facility_columns_read_the_total_column_cell_only() -> None:
    got = read_sheet(STG)
    assert values(got) == {"scope1_total": 1307.6, "scope2_location_total": 591.9, "scope2_market_total": 441.5,
                           "stationary_combustion_total": 874.6, "mobile_combustion_total": 251.7, "fugitive_total": 181.3}
    assert got["scope1_total"]["unit"] == "tCO2e" and "year:2025" in got["scope1_total"]["validation_flags"]
    assert got["reporting_year"]["normalized_value"] == 2025
    assert cell_of(got["scope1_total"]) == ("Summary", "E10") and cell_of(got["scope2_location_total"]) == ("Summary", "E8")
    assert cell_of(got["scope2_market_total"]) == ("Summary", "E9")
    # 251.7 is printed twice in that row: the Total column's cell is the one pointed at, not the Harbor cell
    assert cell_of(got["mobile_combustion_total"]) == ("Summary", "E6")
    assert not any("intensity" in n for n in read.notes)  # type: ignore[attr-defined]


def test_facility_rows_with_scope_columns_read_the_total_row_only() -> None:
    got = read_sheet(NPL)
    assert values(got) == {"scope1_total": 967.9, "scope2_location_total": 1292.8, "scope2_market_total": 1132.1}
    assert got["scope1_total"]["unit"] == "tCO2e" and got["scope1_total"]["source_reference"]["cell_or_range"] == "B8"
    assert cell_of(got["scope2_location_total"]) == ("Summary", "C8") and cell_of(got["scope2_market_total"]) == ("Summary", "D8")
    assert got["scope1_total"]["validation_flags"].count("year:2025") == 1  # the preparation date is not the year


def test_the_scope_1_plus_2_rows_and_column_are_never_a_scope_total() -> None:
    got = read_sheet(STG)
    assert all(c["normalized_value"] not in (1899.5, 1749.1) for c in got.values())
    assert 2260.7 not in values(read_sheet(NPL)).values()


def test_several_columns_and_no_total_read_nothing_and_are_never_added_up() -> None:
    no_total = [[r[0], r[1], r[2], r[3], r[5]] for r in STG[3:10]]
    assert values(read_sheet(no_total)) == {}
    no_total_row = NPL[:7]
    assert values(read_sheet(no_total_row)) == {}
    assert any("total" in n.lower() for n in read.notes)  # type: ignore[attr-defined]


def test_one_value_column_is_the_total_only_by_the_existing_rule() -> None:
    rows = [["Emissions (tCO2e)", "", ""], ["Scope", "Category", "Emissions (tCO2e)"], ["Scope 1", "Stationary combustion", 10.5],
            ["Scope 1", "Total Scope 1", 10.5]]
    assert values(read_sheet(rows)) == {"scope1_total": 10.5, "stationary_combustion_total": 10.5}
    rows[1][2] = "Riverside Plant"
    rows[0][0] = "Summary"
    assert values(read_sheet(rows)) == {}


def test_two_total_columns_are_ambiguous_and_read_nothing() -> None:
    two_years = [["Scope", "Category", "Riverside", "Total 2025 (tCO2e)", "Total 2024 (tCO2e)"],
                 ["Scope 1", "Total Scope 1", 5, 5, 7]]
    assert values(read_sheet(two_years)) == {}
    two_units = [["Scope", "Category", "Total (tCO2e)", "Total (kgCO2e)"], ["Scope 1", "Total Scope 1", 5, 5000]]
    assert values(read_sheet(two_units)) == {}
    assert any("more than one" in n for n in read.notes)  # type: ignore[attr-defined]


def test_a_prior_year_column_beside_the_current_year_does_not_make_the_total_wrong() -> None:
    rows = [["Scope", "Category", "Riverside", "Harbor", "Total (tCO2e)", "Prior year (tCO2e)", "Change (%)"],
            ["Scope 1", "Total Scope 1", 5, 6, 11, 9, 22.2]]
    assert values(read_sheet(rows)) == {"scope1_total": 11}


def test_a_row_whose_total_is_not_the_sum_of_its_facilities_is_not_read() -> None:
    rows = [r[:] for r in STG]
    rows[4][4] = 900.6  # stationary combustion total no longer adds up
    got = values(read_sheet(rows))
    assert "stationary_combustion_total" not in got and got["scope2_market_total"] == 441.5
    assert any("add up" in n for n in read.notes)  # type: ignore[attr-defined]
    rows = [r[:] for r in STG]
    rows[9][4] = 1300.0  # Total Scope 1 disagrees with its category rows
    got = values(read_sheet(rows))
    assert "scope1_total" not in got and "mobile_combustion_total" not in got
    assert got["scope2_market_total"] == 441.5


def test_rounding_in_the_printed_parts_is_not_a_conflict() -> None:
    rows = [["Scope", "Category", "A", "B", "Total (tCO2e)"], ["Scope 1", "Total Scope 1", 10.0, 10.0, 20.5]]
    assert values(read_sheet(rows)) == {}  # 20.0 against 20.5 is beyond the rounding of one decimal
    rows = [["Scope", "Category", "A", "B", "Total (tCO2e)"], ["Scope 1", "Total Scope 1", 10.04, 10.04, 20.1]]
    assert values(read_sheet(rows)) == {"scope1_total": 20.1}  # 20.08 prints as 20.1


def test_two_total_rows_or_a_subtotal_row_are_handled_without_a_guess() -> None:
    two = [r[:] for r in NPL[3:8]] + [["Grand total", 1, 2, 3, 4]]
    assert values(read_sheet(two)) == {}
    sub = [NPL[3], NPL[4], ["Total Fresno", 412.8, 1046.3, 978.5, 1459.1], NPL[5], NPL[6], NPL[7]]
    assert values(read_sheet(sub)) == {"scope1_total": 967.9, "scope2_location_total": 1292.8, "scope2_market_total": 1132.1}
    only_subtotals = [NPL[3], NPL[4], ["Total Fresno", 412.8, 1046.3, 978.5, 1459.1]]
    assert values(read_sheet(only_subtotals)) == {}


def test_a_total_row_that_is_not_the_sum_of_the_facilities_reads_nothing_for_that_column() -> None:
    rows = [r[:] for r in NPL]
    rows[7][2] = 1500.0
    got = values(read_sheet(rows))
    assert "scope2_location_total" not in got and got["scope1_total"] == 967.9 and got["scope2_market_total"] == 1132.1


def test_a_facility_row_is_not_a_company_total() -> None:
    assert values(read_sheet(NPL[3:5])) == {}


def test_a_notes_column_or_a_date_is_not_an_intensity_but_a_real_denominator_still_is() -> None:
    assert values(read_sheet(STG))["scope1_total"] == 1307.6  # "Method / notes" and dates
    for header in ("Total (tCO2e / $M revenue)", "Total (tCO2e per unit)", "Total emissions intensity (tCO2e)"):
        rows = [["Scope", "Category", "Riverside", header], ["Scope 1", "Total Scope 1", 5, 5]]
        assert values(read_sheet(rows)) == {}, header
    caption = [["Emissions tCO2e / employee"], ["Scope", "Category", "Total"], ["Scope 1", "Total Scope 1", 5]]
    assert values(read_sheet(caption)) == {}
    assert rt.read_unit(["Prepared 01/30/2026. Units: metric tonnes CO2e."]) == ("tCO2e", "Prepared 01/30/2026. Units: metric tonnes CO2e.", None)
    assert rt.read_unit(["Total (tCO2e) / notes"])[2] is None
    assert rt.read_unit(["tCO2e/MWh"])[2] == "measure" and rt.read_unit(["kgCO2e / $M"])[2] == "measure"


def test_a_scope_2_row_without_its_basis_is_not_read_in_a_workbook_either() -> None:
    rows = [["Scope", "Category", "Total (tCO2e)"], ["Scope 2", "Total Scope 2", 5], ["Scope 1", "Total Scope 1", 3]]
    assert values(read_sheet(rows)) == {"scope1_total": 3}


def test_not_reported_in_a_total_cell_stays_not_reported_never_zero() -> None:
    rows = [["Scope", "Category", "Riverside", "Total (tCO2e)"], ["Scope 1", "Total Scope 1", 5, "N/A"]]
    got = read_sheet(rows)["scope1_total"]
    assert got["raw_value"] == "N/A" and got["normalized_value"] is None and "not_reported" in got["validation_flags"]


def test_subscript_units_and_a_merged_two_row_header_are_read() -> None:
    rows = [["Emissions summary", None, None, None], [None, None, "Facilities", None, "Total"],
            ["Scope", "Category", "Riverside", "Harbor", "(tCO₂e)"],
            ["Scope 1", "Total Scope 1", 5, 6, 11]]
    got = read_sheet(rows)
    assert values(got) == {"scope1_total": 11} and got["scope1_total"]["unit"] == "tCO2e"


def test_a_scope_cell_merged_down_the_rows_is_inherited_for_categories_only() -> None:
    rows = [["Scope", "Category", "A", "Total (tCO2e)"], ["Scope 1", "Stationary combustion", 1, 1], [None, "Mobile combustion", 2, 2],
            [None, "Total", 3, 3]]
    assert values(read_sheet(rows)) == {"stationary_combustion_total": 1, "mobile_combustion_total": 2}


def test_two_tables_on_one_sheet_keep_their_own_headers_and_units() -> None:
    rows = [["Scope", "Category", "A", "Total (tCO2e)"], ["Scope 1", "Total Scope 1", 5, 5], [None] * 4,
            ["Scope", "Category", "A", "Total (ktCO2e)"], ["Scope 2", "Location-based", 0.5, 0.5]]
    got = read_sheet(rows)
    assert (got["scope1_total"]["unit"], got["scope2_location_total"]["unit"]) == ("tCO2e", "ktCO2e")


def test_the_same_total_printed_with_two_values_on_two_sheets_reads_nothing() -> None:
    other = [r[:] for r in NPL]
    other[7][1] = 961.0
    other[4][1] = 405.9
    outcome = rt.ReportedTotalsExtractor().extract(sheet_output(("Summary", NPL), ("Old", other)), TARGETS, "ev1")
    got = {c["field_name"]: c for c in outcome.candidates}
    assert got["scope1_total"]["raw_value"] is None and got["scope2_market_total"]["normalized_value"] == 1132.1
