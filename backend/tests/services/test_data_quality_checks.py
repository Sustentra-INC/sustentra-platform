"""Data quality checks: missing months, duplicates, overlapping and cross-year bills."""

from __future__ import annotations

from datetime import date

from backend.app.services.data_quality_checks import EvidenceRecord, run_checks

YEAR = (date(2025, 1, 1), date(2025, 12, 31))


def bill(document: str, start: str | None, end: str | None, quantity: float | None = 100.0, *,
         facility: str = "Facility A", account: str | None = "ACCT-1", category: str = "purchased_electricity",
         item: str | None = None, record: int | None = None, file_name: str | None = None,
         periodic: bool = True) -> EvidenceRecord:
    name = file_name or f"{document}.pdf"
    return EvidenceRecord(
        category=category, document_id=document, file_name=name,
        label=name if record is None else f"{name} (record {record})", facility=facility, item=item,
        account=account, start=date.fromisoformat(start) if start else None,
        end=date.fromisoformat(end) if end else None, amounts=(quantity,), unit="kWh", periodic=periodic,
    )


def monthly(document: str, months: list[int], **kwargs) -> list[EvidenceRecord]:
    ends = {2: 28, 4: 30, 6: 30, 9: 30, 11: 30}
    return [bill(document, f"2025-{m:02d}-01", f"2025-{m:02d}-{ends.get(m, 31)}", 100.0 + m, record=m, **kwargs)
            for m in months]


def triggers(findings: list[dict]) -> list[tuple[str, str]]:
    return [(f["check"], f["trigger"]) for f in findings]


def test_a_full_year_of_bills_raises_nothing() -> None:
    assert run_checks(monthly("BILLS", list(range(1, 13))), YEAR) == []
    # Two half-year bills sharing the meter-read day, and a bill a few days short at year end.
    assert run_checks([bill("A1", "2025-01-01", "2025-07-01"), bill("A2", "2025-07-01", "2025-12-29")], YEAR) == []


def test_missing_months_are_named_per_facility_and_source() -> None:
    findings = run_checks(monthly("BILLS", [1, 2, 5, 6, 7, 8, 9, 10, 11, 12]), YEAR)
    assert triggers(findings) == [("Q-001", "missing_month")]
    assert findings[0]["detail"]["missing_months"] == ["Mar 2025", "Apr 2025"]
    assert findings[0]["detail"]["coverage_percent"] == 83.3
    assert "Facility A electricity: no bill covers Mar 2025, Apr 2025" in findings[0]["message"]
    # Another facility's bills do not fill this one's gap.
    other = monthly("OTHER", [3, 4], facility="Facility B")
    assert ("Q-001", "missing_month") in triggers(run_checks(monthly("BILLS", [1, 2, 5, 6, 7, 8, 9, 10, 11, 12]) + other, YEAR))


def test_a_short_gap_inside_a_month_is_an_incomplete_year() -> None:
    findings = run_checks([bill("A1", "2025-01-01", "2025-06-10"), bill("A2", "2025-06-20", "2025-12-31")], YEAR)
    assert triggers(findings) == [("Q-001", "incomplete_year")]
    assert findings[0]["detail"]["gaps"] == ["2025-06-11 to 2025-06-19"]
    assert findings[0]["severity"] == "review"


def test_the_same_bill_in_two_documents_is_a_duplicate_not_also_an_overlap() -> None:
    findings = run_checks([bill("A1", "2025-01-01", "2025-12-31", file_name="bill.pdf"),
                           bill("A2", "2025-01-01", "2025-12-31", file_name="bill (1).pdf")], YEAR)
    assert triggers(findings) == [("Q-003", "same_document_reuploaded_with_different_file_name")]
    assert findings[0]["documents"] == ["A1", "A2"] and findings[0]["severity"] == "warning"


def test_a_repeated_record_inside_a_larger_log_is_a_duplicate_counting_risk() -> None:
    log = monthly("LOG", list(range(1, 13)))
    statement = [bill("MARCH", "2025-03-01", "2025-03-31", 103.0)]
    findings = run_checks(log + statement, YEAR)
    assert triggers(findings) == [("Q-003", "duplicate_counting_risk")]
    assert findings[0]["records"] == ["LOG.pdf (record 3)", "MARCH.pdf"]


def test_overlapping_bills_for_the_same_account_count_days_twice() -> None:
    findings = run_checks([bill("ANNUAL", "2025-01-01", "2025-12-31", 800.0),
                           bill("Q1", "2025-01-01", "2025-03-31", 96.0)], YEAR)
    assert triggers(findings) == [("Q-004", "overlap_same_source_different_document_id")]
    assert findings[0]["detail"] == {"overlap_days": 90, "overlap_start": "2025-01-01", "overlap_end": "2025-03-31"}


def test_overlapping_bills_on_different_accounts_ask_whether_they_are_separate_meters() -> None:
    findings = run_checks([bill("ANNUAL", "2025-01-01", "2025-12-31", account="DVE-5520-B"),
                           bill("Q1", "2025-01-01", "2025-03-31", 96.0, account="KGE-7781-B")], YEAR)
    assert triggers(findings) == [("Q-004", "overlapping_period")]
    assert findings[0]["severity"] == "review" and "separate meters" in findings[0]["message"]


def test_different_fuels_at_one_site_do_not_overlap() -> None:
    gas = bill("GAS", "2025-01-01", "2025-12-31", category="stationary_combustion", item="natural_gas")
    oil = bill("OIL", "2025-01-01", "2025-12-31", category="stationary_combustion", item="fuel_oil_no_2")
    assert run_checks([gas, oil], YEAR) == []


def test_a_bill_across_the_year_end_says_how_it_was_split() -> None:
    findings = run_checks([bill("DEC", "2024-12-15", "2025-01-14"), *monthly("REST", list(range(2, 13)))], YEAR)
    cutoff = [f for f in findings if f["check"] == "Q-005"]
    assert len(cutoff) == 1 and cutoff[0]["severity"] == "info"
    assert cutoff[0]["detail"] == {"allocation_method": "days_in_service_period", "share_percent": 45.2}
    assert "14 days (45.2%)" in cutoff[0]["message"]


def test_a_bill_without_a_service_period_is_flagged_and_deliveries_are_events() -> None:
    findings = run_checks([bill("NODATES", None, None)], YEAR)
    assert triggers(findings) == [("N-003", "date_missing")]
    # Fuel delivered on two days: no "missing month", but the same delivery in two files is a duplicate.
    deliveries = [bill("LOG", "2025-02-10", "2025-02-10", 450.0, category="stationary_combustion", item="diesel",
                       periodic=False),
                  bill("LOG2", "2025-02-10", "2025-02-10", 450.0, category="stationary_combustion", item="diesel",
                       periodic=False, file_name="LOG.csv")]
    assert triggers(run_checks(deliveries, YEAR)) == [("Q-003", "same_document_reuploaded_with_different_file_name")]
    assert run_checks(deliveries[:1], YEAR) == []


def test_without_a_reporting_period_only_the_document_checks_run() -> None:
    findings = run_checks(monthly("BILLS", [1, 2]) + [bill("COPY", "2025-01-01", "2025-01-31", 101.0)], (None, None))
    assert triggers(findings) == [("Q-003", "duplicate_counting_risk")]
