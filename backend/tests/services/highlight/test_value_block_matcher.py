"""Tests for the value->block matcher (step C) against a captured Textract JSON.

The fixture (fixtures/utility_bill_textract.json) is a realistic AnalyzeDocument
response — real block/geometry structure, normalized 0..1 boxes — built by hand
until a live capture is available. Each test asserts the exact block(s) matched
(word_ids), so a right box is proven, not just a non-null one. The confidence
gate is tested as hard as the matches: uncertainty must return None.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.services.highlight.textract_geometry import extract_page_lines
from backend.app.services.highlight.value_block_matcher import canonical_number, match_value_to_span

FIXTURE = Path(__file__).parent / "fixtures" / "utility_bill_textract.json"


@pytest.fixture(scope="module")
def page_lines():
    response = json.loads(FIXTURE.read_text())
    return extract_page_lines(response)


def match(page_lines, **kwargs):
    base = {"value": None, "unit": None, "source_snippet": None, "page_number": 1, "page_lines": page_lines}
    base.update(kwargs)
    return match_value_to_span(**base)


# ---- geometry reader (B) ----

def test_reader_carries_geometry_in_xywh(page_lines):
    lines = page_lines[1]
    assert lines, "expected LINE blocks on page 1"
    a_line = next(l for l in lines if "182,400" in l.text)
    assert 0.0 <= a_line.bbox.x <= 1.0 and 0.0 <= a_line.bbox.y <= 1.0
    assert a_line.bbox.w > 0 and a_line.bbox.h > 0
    assert a_line.words, "expected child WORD blocks"


# ---- canonical number normalization ----

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("182,400", "182400"),      # US thousands
        ("182.400", "182.4"),       # single dot -> decimal (documented convention)
        ("0.223", "0.223"),
        ("$48,220.15", "48220.15"), # currency + thousands + decimal
        ("1 240", "1240"),          # space thousands
        ("182.400,50", "182400.5"), # EU: dot thousands, comma decimal
    ],
)
def test_canonical_number(raw, expected):
    assert canonical_number(raw) == expected


# ---- matches (a right box, proven by word ids) ----

def test_thousands_value_single_word(page_lines):
    # "182,400" appears twice; the snippet points at the electricity line.
    out = match(page_lines, value="182400", unit="kWh",
                source_snippet="Electricity consumed 182,400 kWh")
    assert out is not None
    assert out["word_ids"] == ["w3_2"]  # the electricity-line occurrence, not the balance line


def test_repeated_value_disambiguated_the_other_way(page_lines):
    out = match(page_lines, value="182,400", source_snippet="Previous balance 182,400")
    assert out is not None
    assert out["word_ids"] == ["w4_2"]  # the previous-balance occurrence


def test_repeated_value_without_snippet_returns_none(page_lines):
    # Same value twice, no snippet to disambiguate -> a box could be wrong -> None.
    assert match(page_lines, value="182400", source_snippet=None) is None


def test_value_split_across_words(page_lines):
    # "1 240" is two WORD blocks; union them into 1240.
    out = match(page_lines, value="1240", unit="kW", source_snippet="Peak demand 1 240 kW")
    assert out is not None
    assert out["word_ids"] == ["w5_2", "w5_3"]
    assert out["match_kind"] == "word_run"


def test_decimal_value(page_lines):
    out = match(page_lines, value="0.223", unit="kgCO2e/kWh")
    assert out is not None
    assert out["word_ids"] == ["w6_2"]


def test_currency_thousands_decimal(page_lines):
    out = match(page_lines, value="48,220.15")
    assert out is not None
    assert out["word_ids"] == ["w7_2"]


def test_text_value_phrase(page_lines):
    out = match(page_lines, value="Pacific Grid Electric")
    assert out is not None
    assert out["word_ids"] == ["w0_0", "w0_1", "w0_2"]
    assert out["match_kind"] == "word_phrase"


# ---- the confidence gate: uncertainty returns None ----

def test_llm_derived_value_not_on_page_returns_none(page_lines):
    # 182,400 * 2 = 364,800 — a value the LLM derived, not read verbatim.
    assert match(page_lines, value="364800", source_snippet="derived total") is None


def test_substring_number_does_not_match_inside_a_larger_number(page_lines):
    # "400" must NOT match inside "182,400".
    assert match(page_lines, value="400") is None


def test_alphanumeric_code_does_not_get_a_numeric_box(page_lines):
    # "E-19" must not be mis-highlighted as the number 19 somewhere.
    out = match(page_lines, value="E-19")
    # Either no confident text match, or it matches the rate-schedule line — but
    # it must never return a numeric box drawn on an unrelated "19".
    assert out is None or "l8" in out["word_ids"] or out["word_ids"] == ["w8_2"]


def test_missing_page_number_returns_none(page_lines):
    assert match(page_lines, value="182400", page_number=None) is None


# ---- inline builders for edge cases (independent of the tidy fixture) ----

def _word(wid, text, left, top, width=0.06, height=0.028, conf=99.0, page=1):
    return {
        "Id": wid, "BlockType": "WORD", "Page": page, "Text": text, "Confidence": conf,
        "Geometry": {"BoundingBox": {"Left": left, "Top": top, "Width": width, "Height": height}},
    }


def _line(lid, text, word_ids, left=0.1, top=0.1, width=0.5, height=0.028, conf=99.0, page=1, geometry=True):
    block = {
        "Id": lid, "BlockType": "LINE", "Page": page, "Text": text, "Confidence": conf,
        "Relationships": [{"Type": "CHILD", "Ids": word_ids}],
    }
    if geometry:
        block["Geometry"] = {"BoundingBox": {"Left": left, "Top": top, "Width": width, "Height": height}}
    return block


def _resp(blocks):
    return {"Blocks": blocks}


def _m(pl, **kw):
    base = {"value": None, "unit": None, "source_snippet": None, "page_number": 1, "page_lines": pl}
    base.update(kw)
    return match_value_to_span(**base)


def test_blocks_present_but_no_geometry_returns_none_not_crash():
    # A LINE (and its WORD) with no Geometry at all — skipped, no exception.
    resp = _resp([
        _line("l0", "Electricity consumed 182,400 kWh", ["w0"], geometry=False),
        {"Id": "w0", "BlockType": "WORD", "Page": 1, "Text": "182,400", "Confidence": 99.0},
    ])
    pl = extract_page_lines(resp)
    assert pl == {}
    assert _m(pl, value="182400", page_number=1) is None


def test_value_on_a_different_page_than_the_llm_claimed():
    # Value only on page 2; the LLM said page 1.
    resp = _resp([
        _line("l2", "Electricity consumed 182,400 kWh", ["w2"], page=2),
        _word("w2", "182,400", 0.3, 0.1, page=2),
    ])
    pl = extract_page_lines(resp)
    assert _m(pl, value="182400", page_number=1) is None      # claimed page has nothing
    assert _m(pl, value="182400", page_number=2)["word_ids"] == ["w2"]


def test_low_confidence_block_is_dropped():
    resp = _resp([
        _line("l0", "Electricity consumed 182,400 kWh", ["w0"], conf=20.0),
        _word("w0", "182,400", 0.3, 0.1, conf=20.0),
    ])
    pl = extract_page_lines(resp)
    assert _m(pl, value="182400", page_number=1) is None                 # below the 50 gate
    assert _m(pl, value="182400", page_number=1, min_confidence=10.0)["word_ids"] == ["w0"]  # proves it was a real match


def test_same_value_on_two_pages_is_scoped_by_page():
    resp = _resp([
        _line("la", "Electricity consumed 182,400 kWh", ["wa"], page=1),
        _word("wa", "182,400", 0.3, 0.1, page=1),
        _line("lb", "Electricity consumed 182,400 kWh", ["wb"], page=2),
        _word("wb", "182,400", 0.3, 0.1, page=2),
    ])
    pl = extract_page_lines(resp)
    assert _m(pl, value="182400", page_number=1)["word_ids"] == ["wa"]
    assert _m(pl, value="182400", page_number=2)["word_ids"] == ["wb"]


def test_empty_or_malformed_response_is_handled():
    assert extract_page_lines({}) == {}
    assert extract_page_lines(None) == {}
    assert extract_page_lines({"Blocks": "garbage"}) == {}
    assert extract_page_lines({"Blocks": [{"BlockType": "LINE", "Text": "x"}]}) == {}  # no geometry -> skipped
    assert match_value_to_span(value="1", unit=None, source_snippet=None, page_number=1, page_lines={}) is None


def test_separator_split_across_words_is_bridged():
    # Real Textract can emit "182" "," "400" as three WORD blocks.
    resp = _resp([
        _line("l0", "Electricity consumed 182,400 kWh", ["w0", "w1", "w2", "w3", "w4"]),
        _word("w0", "Electricity", 0.10, 0.1),
        _word("w1", "consumed", 0.24, 0.1),
        _word("w2", "182", 0.36, 0.1, width=0.03),
        _word("w3", ",", 0.39, 0.1, width=0.008),
        _word("w4", "400", 0.40, 0.1, width=0.03),
    ])
    pl = extract_page_lines(resp)
    out = _m(pl, value="182400", page_number=1)
    assert out is not None
    assert out["word_ids"] == ["w2", "w3", "w4"]
    assert out["match_kind"] == "word_run"
