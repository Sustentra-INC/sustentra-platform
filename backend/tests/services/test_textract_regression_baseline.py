"""The Textract baseline replayed offline: the recorded responses still read as recorded.

backend/scripts/textract_regression.py records live Textract responses for scanned
samples and the values our pipeline extracts from them. Replaying those responses here
catches a change in our own reading rules that would alter what is read from scans; the
script's `compare` mode catches a change on Textract's side (a model update).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from backend.scripts.textract_regression import BASELINE, SAMPLES, ReplayClient, extract, sample_file

BASELINE_DATA: dict[str, Any] = json.loads(BASELINE.read_text(encoding="utf-8"))


def test_every_sample_has_a_recorded_baseline() -> None:
    assert set(BASELINE_DATA["samples"]) == set(SAMPLES)
    for sample in BASELINE_DATA["samples"].values():
        assert sample["responses"] and sample["model_versions"]


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_recorded_textract_responses_read_the_recorded_values(name: str) -> None:
    recorded = BASELINE_DATA["samples"][name]
    replay = ReplayClient(recorded["responses"])
    with sample_file(SAMPLES[name]) as path:
        now = extract(path, lambda *_args, **_kwargs: replay)
    assert (now["type"], now["halt"]) == (recorded["type"], recorded["halt"])
    assert now["values"] == recorded["values"]


def test_the_scanned_gas_bill_reads_its_key_values() -> None:
    values = BASELINE_DATA["samples"]["scanned_gas_bill_png"]["values"]
    assert values["activity_quantity"] == {"value": 32400, "unit": "MMBtu"}
    assert values["account_number"]["value"] == "ACC-2023-BWV-001"
    assert values["facility_name"]["value"] == "Anheuser-Busch Baldwinsville Brewery"
