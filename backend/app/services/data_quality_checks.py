"""Data quality checks on the evidence (formula library Q-001, Q-003, Q-004, Q-005, N-003).

An auditor looks for the same problems in every set of bills: a month nobody billed, the
same bill counted twice, two bills covering the same days, and bills that run across the
reporting year. Each check here is a signal for the reviewer, never a conclusion: it names
the documents and says what to look at. The numbers are unchanged by it.

- Q-001 Calendar-year completeness: per facility and source, the reporting-period months
  no bill covers (``missing_month``), or days not covered (``incomplete_year``).
- Q-003 Duplicate evidence: records in different documents with the same facility,
  source, dates and amounts (``duplicate_counting_risk``); a whole document repeated
  under another name (``same_document_reuploaded_with_different_file_name``); one statement
  printed twice in a file (``duplicate_statement_in_same_file``).
- Q-004 Overlapping periods: two bills for the same facility and source covering the same
  days (``overlap_same_source_different_document_id`` / ``overlapping_period``).
- Q-005 Cross-year allocation: a bill running across the reporting period's start or end,
  counted by its share of days (``cross_year_without_allocation_support``).
- Q-003 Revised bill: a bill that says it replaces an earlier one (its reference is on the record),
  while that earlier bill is also in the evidence (``revised_bill_replaces_earlier``). The finding
  suggests marking the earlier bill as superseded; the reviewer decides, nothing is marked here.
- N-003 Period normalization: a bill with no service period, counted in full
  (``date_missing``).

Pure: the recalculation builds the records (after the reviewer's withdrawn / duplicate /
superseded decisions) and passes them in.
"""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from collections.abc import Iterator
from backend.app.services.facility_identifiers import same_number
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

# Bills are read on meter-read days, so consecutive bills share a day or leave a short gap.
OVERLAP_MIN_DAYS = 2  # a single shared day is the meter read, not an overlap
GAP_TOLERANCE_DAYS = 3  # gaps this short between bills are read-date drift, not missing days
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
CATEGORY_LABEL = {
    "stationary_combustion": "fuel",
    "mobile_combustion": "vehicle fuel",
    "fugitive_refrigerants": "refrigerant",
    "purchased_electricity": "electricity",
}


@dataclass(frozen=True)
class EvidenceRecord:
    """One record of reviewed or extracted evidence, as the checks need it."""

    category: str  # roll-up source key, e.g. "purchased_electricity"
    document_id: str
    file_name: str
    label: str  # "bill.pdf" or "log.xlsx (record 3)"
    facility: str  # the Setup facility, else the name or address on the document
    item: str | None  # what is measured: the fuel, or refrigerant and equipment
    account: str | None  # account / meter / card number when the document gives one
    start: date | None
    end: date | None
    amounts: tuple[float | None, ...]  # quantity (and for refrigerants: added, recovered, capacity)
    unit: str | None
    periodic: bool  # a bill for a service period, rather than a dated purchase or service
    revises: str | None = None  # the earlier bill this one says it replaces (its number or date), if it says so
    revises_key: str | None = None  # that reference as a key: a date as ISO, a number upper-cased; None if not given
    bill_ids: tuple[str, ...] = ()  # this bill's own statement date (ISO) and invoice or statement number
    meter: str | None = None  # the meter or line id the record was read under, when it has one
    page: int | None = None  # the page the quantity was read from, when known
    total_check: str | None = None  # a statement of account whose total differs from its invoices' (kept, flagged)


def _span(record: EvidenceRecord) -> tuple[date, date] | None:
    first = record.start or record.end
    last = record.end or record.start
    if first is None or last is None or last < first:
        return None
    return first, last


def _overlap_days(a: tuple[date, date], b: tuple[date, date]) -> int:
    return max(0, (min(a[1], b[1]) - max(a[0], b[0])).days + 1)


def _month(day: date) -> str:
    return f"{MONTHS[day.month - 1]} {day.year}"


def _source_name(record: EvidenceRecord) -> str:
    what = CATEGORY_LABEL.get(record.category, record.category.replace("_", " "))
    item = f" ({record.item.replace('_', ' ')})" if record.item and record.category != "purchased_electricity" else ""
    return f"{record.facility} {what}{item}"


def _finding(check: str, trigger: str, severity: str, records: list[EvidenceRecord], message: str,
             **detail: Any) -> dict[str, Any]:
    first = records[0]
    return {
        "check": check, "trigger": trigger, "severity": severity, "category": first.category,
        "facility": first.facility,
        "documents": list(dict.fromkeys(r.document_id for r in records)),
        "records": list(dict.fromkeys(r.label for r in records)),
        "message": message, "detail": detail,
    }


# =========================================================================================
# Q-001 calendar-year completeness
# =========================================================================================
def _completeness(groups: dict[tuple[str, str, str | None], list[EvidenceRecord]],
                  period: tuple[date, date]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    total_days = (period[1] - period[0]).days + 1
    for records in groups.values():
        spans = sorted(s for s in (_span(r) for r in records) if s is not None)
        clipped = [(max(a, period[0]), min(b, period[1])) for a, b in spans if b >= period[0] and a <= period[1]]
        if not clipped:
            continue  # nothing inside the period: listed as outside the reporting period instead
        # Merge, treating short gaps between bills as covered.
        merged: list[list[date]] = []
        for a, b in clipped:
            if merged and (a - merged[-1][1]).days <= GAP_TOLERANCE_DAYS + 1:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        # Gaps at the period's edges within the tolerance are covered too.
        if (merged[0][0] - period[0]).days <= GAP_TOLERANCE_DAYS:
            merged[0][0] = period[0]
        if (period[1] - merged[-1][1]).days <= GAP_TOLERANCE_DAYS:
            merged[-1][1] = period[1]
        covered = sum((b - a).days + 1 for a, b in merged)
        if covered >= total_days:
            continue
        missing_months: list[str] = []
        month_start = date(period[0].year, period[0].month, 1)
        while month_start <= period[1]:
            next_month = date(month_start.year + month_start.month // 12, month_start.month % 12 + 1, 1)
            span = (max(month_start, period[0]), min(next_month - timedelta(days=1), period[1]))
            if not any(_overlap_days(span, (a, b)) for a, b in merged):
                missing_months.append(_month(month_start))
            month_start = next_month
        coverage = round(100 * covered / total_days, 1)
        name = _source_name(records[0])
        if missing_months:
            message = (f"{name}: no bill covers {', '.join(missing_months)} "
                       f"({coverage}% of the reporting period is covered). Request the missing bills, "
                       "or record why there was no use.")
            out.append(_finding("Q-001", "missing_month", "warning", records, message,
                                missing_months=missing_months, coverage_percent=coverage))
        else:
            uncovered = [(period[0], merged[0][0] - timedelta(days=1))] if merged[0][0] > period[0] else []
            uncovered += [(prev[1] + timedelta(days=1), nxt[0] - timedelta(days=1))
                          for prev, nxt in zip(merged, merged[1:])]
            if merged[-1][1] < period[1]:
                uncovered.append((merged[-1][1] + timedelta(days=1), period[1]))
            gaps = [f"{a.isoformat()} to {b.isoformat()}" if a != b else a.isoformat() for a, b in uncovered]
            message = (f"{name}: the bills cover {coverage}% of the reporting period"
                       + (f"; days not covered: {', '.join(gaps)}." if gaps else ".")
                       + " Check for a missing or short bill.")
            out.append(_finding("Q-001", "incomplete_year", "review", records, message,
                                coverage_percent=coverage, gaps=gaps))
    return out


# =========================================================================================
# Q-003 duplicates and Q-004 overlaps
# =========================================================================================
def _repeat_in_file(first: EvidenceRecord, other: EvidenceRecord) -> bool:
    """Two records of one file that read as the same statement printed twice: the same account, and the same
    meter, or (when a meter is missing from either) on different pages: a statement of account that repeats an
    invoice's period and usage has no meter of its own, and is still a repeat. Two meters of one bill share its account, period and
    maybe a reading; that is not a repeat."""

    if not first.account or not same_number(first.account, other.account):
        return False
    if first.meter and other.meter:
        return first.meter == other.meter
    return first.page is not None and other.page is not None and first.page != other.page


def _duplicate_key(record: EvidenceRecord) -> tuple[Any, ...] | None:
    if record.start is None and record.end is None:
        return None
    if all(a is None for a in record.amounts):
        return None
    amounts = tuple(None if a is None else round(a, 6) for a in record.amounts)
    return (record.category, record.facility.lower(), (record.item or "").lower(), record.start, record.end,
            amounts, (record.unit or "").lower())


def _duplicates(records: list[EvidenceRecord]) -> tuple[list[dict[str, Any]], set[frozenset[str]]]:
    """Same facility, source, dates and amounts in different documents."""

    by_key: dict[tuple[Any, ...], list[EvidenceRecord]] = defaultdict(list)
    for record in records:
        key = _duplicate_key(record)
        if key is not None:
            by_key[key].append(record)
    out: list[dict[str, Any]] = []
    for group in by_key.values():  # one statement printed twice in one file (a bundle repeating a month)
        in_file: dict[str, list[EvidenceRecord]] = defaultdict(list)
        for found in group:
            in_file[found.document_id].append(found)
        for same in in_file.values():
            for n, one in enumerate(same):
                other = next((r for r in same[n + 1:] if _repeat_in_file(one, r)), None)
                if other is not None:
                    out.append(_finding(
                        "Q-003", "duplicate_statement_in_same_file", "warning", [one, other],
                        f"{one.label} and {other.label} are the same statement printed twice in one file (same "
                        f"{_source_name(one)} dates, amounts and account): it may be counted twice. "
                        "Check the file.", matching_records=2))
    # Pairs of documents sharing records, with the records they share.
    shared: dict[tuple[str, str], list[tuple[EvidenceRecord, EvidenceRecord]]] = defaultdict(list)
    for group in by_key.values():
        documents = sorted({r.document_id for r in group})
        for i, first in enumerate(documents):
            for second in documents[i + 1:]:
                a = next(r for r in group if r.document_id == first)
                b = next(r for r in group if r.document_id == second)
                shared[(first, second)].append((a, b))
    per_document: dict[str, int] = defaultdict(int)
    for record in records:
        per_document[record.document_id] += 1
    pairs: set[frozenset[str]] = set()
    for (first, second), matches in shared.items():
        a, b = matches[0]
        pairs.add(frozenset((first, second)))
        whole = len(matches) == per_document[first] == per_document[second]
        shown: list[str] = []  # one entry per account: two are one only when same_number says so, as in the pairing
        for pair in matches:
            for r in pair:
                if r.account and not any(same_number(r.account, seen) for seen in shown):
                    shown.append(r.account)
        accounts = set(shown)
        if whole and a.file_name != b.file_name:
            trigger = "same_document_reuploaded_with_different_file_name"
            message = (f"{a.file_name} and {b.file_name} hold the same {len(matches)} "
                       f"record{'s' if len(matches) > 1 else ''} (same dates and amounts): the same document "
                       "seems to be uploaded twice. Mark one as a duplicate on the Evidence screen.")
        elif len(accounts) > 1:
            trigger = "duplicate_period_amount_with_different_invoice_id"
            message = (f"{a.label} and {b.label} have the same dates and amounts but different accounts "
                       f"({', '.join(sorted(accounts))}). Confirm they are separate meters, not one bill counted twice.")
        else:
            trigger = "duplicate_counting_risk"
            message = (f"{a.label} and {b.label} have the same {_source_name(a)} dates and amounts: "
                       "it may be counted twice. Mark one as a duplicate on the Evidence screen if so.")
        severity = "review" if trigger == "duplicate_period_amount_with_different_invoice_id" else "warning"
        out.append(_finding("Q-003", trigger, severity, [r for pair in matches for r in pair], message,
                            matching_records=len(matches)))
    return out, pairs


def _revisions(records: list[EvidenceRecord]) -> tuple[list[dict[str, Any]], set[frozenset[str]]]:
    """A revised bill and the earlier bill it replaces: same source, same account (or facility) and the same
    days, in another document. A bill that itself says it replaces another is never "the earlier one". When the
    revised bill prints a date or number, only the bill with that statement date or invoice number counts; if
    several bills could be the one, none is named and the reviewer is asked which. A suggestion, never a
    decision: nothing is marked superseded here."""

    out: list[dict[str, Any]] = []
    pairs: set[frozenset[str]] = set()
    for revised in records:
        if not revised.revises or (span := _span(revised)) is None:
            continue
        pool: dict[str, EvidenceRecord] = {}
        for earlier in records:
            if (earlier.document_id == revised.document_id or earlier.revises or earlier.category != revised.category
                    or (earlier.item or "").lower() != (revised.item or "").lower()):
                continue
            same_account = bool(earlier.account and revised.account and same_number(earlier.account, revised.account))
            same_site = earlier.facility.lower() == revised.facility.lower()
            other = _span(earlier)
            if not (same_account or (same_site and not (earlier.account and revised.account))) or other is None:
                continue
            if _overlap_days(span, other) >= OVERLAP_MIN_DAYS:
                pool.setdefault(earlier.document_id, earlier)
        if revised.revises_key:
            pool = {d: e for d, e in pool.items() if revised.revises_key in e.bill_ids}
        if not pool:
            continue
        what = _printed(revised)
        if len(pool) == 1:
            earlier = next(iter(pool.values()))
            message = (f"{revised.label} says it replaces {what}. {earlier.label} covers the same days for "
                       f"{_source_name(revised)}: if it is the earlier bill, mark it as superseded on the Evidence "
                       "screen, so that only the revised bill is counted.")
            out.append(_finding("Q-003", "revised_bill_replaces_earlier", "review", [revised, earlier], message,
                                suggestion="mark_superseded", original_document_id=earlier.document_id,
                                reference=revised.revises))
            if revised.revises_key:  # the printed reference matched: it is this pair, not also an overlap
                pairs.add(frozenset((earlier.document_id, revised.document_id)))
        else:
            candidates = list(pool.values())
            names = ", ".join(e.label for e in candidates)
            message = (f"{revised.label} says it replaces {what}, and more than one bill covers the same days for "
                       f"{_source_name(revised)} ({names}). Mark which one it replaces as superseded on the "
                       "Evidence screen, so that only the revised bill is counted.")
            out.append(_finding("Q-003", "revised_bill_replaces_earlier", "review", [revised, *candidates], message,
                                suggestion="mark_which", candidates=[e.document_id for e in candidates],
                                reference=revised.revises))
    return out, pairs


def _printed(revised: EvidenceRecord) -> str:
    """How the revised bill names the bill it replaces, in the reviewer's words."""

    if revised.revises_key is None:
        return "an earlier bill"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", revised.revises_key):
        return f"the earlier statement dated {revised.revises}"
    return f"the earlier bill number {revised.revises}"


def _later_candidates(spans: list[tuple[EvidenceRecord, tuple[date, date]]]
                      ) -> Iterator[tuple[int, tuple[EvidenceRecord, tuple[date, date]],
                                          list[tuple[EvidenceRecord, tuple[date, date]]]]]:
    """For each span in order, the spans after it (in order) that could overlap it: those that start no later than
    it ends and no earlier than its start less the longest span. Every pair the plain all-pairs loop would find an
    overlap in is here, in the same order; only pairs that cannot overlap are left out, so a group of hundreds of
    records of different periods costs near-linear time, not a comparison of every pair."""

    if not spans:
        return
    order = sorted(range(len(spans)), key=lambda k: spans[k][1][0])
    starts = [spans[k][1][0] for k in order]
    longest = max((end - start for _, (start, end) in spans), default=timedelta(0))
    for i, entry in enumerate(spans):
        first, last = entry[1]
        low = bisect_left(starts, first - longest)
        high = bisect_right(starts, last)
        yield i, entry, [spans[j] for j in sorted(k for k in order[low:high] if k > i)]


def _overlaps(groups: dict[tuple[str, str, str | None], list[EvidenceRecord]],
              duplicate_pairs: set[frozenset[str]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for records in groups.values():
        spans = [(r, s) for r in records if (s := _span(r)) is not None]
        for i, (a, span_a), later in _later_candidates(spans):
            for b, span_b in later:
                days = _overlap_days(span_a, span_b)
                if days < OVERLAP_MIN_DAYS:
                    continue
                if a.document_id != b.document_id and frozenset((a.document_id, b.document_id)) in duplicate_pairs:
                    continue  # already reported as a duplicate
                if a.document_id == b.document_id and _duplicate_key(a) == _duplicate_key(b) and _repeat_in_file(a, b):
                    continue  # the same statement twice in one file: reported as a duplicate
                start = max(span_a[0], span_b[0]).isoformat()
                end = min(span_a[1], span_b[1]).isoformat()
                if a.document_id == b.document_id:
                    trigger, severity = "overlapping_period", "warning"
                    message = (f"{a.label} and {b.label} both cover {start} to {end} ({days} days) for "
                               f"{_source_name(a)}: those days may be counted twice.")
                elif a.account and b.account and not same_number(a.account, b.account):
                    trigger, severity = "overlapping_period", "review"
                    message = (f"{a.label} and {b.label} both cover {start} to {end} ({days} days) for "
                               f"{_source_name(a)} on different accounts ({a.account}, {b.account}). Confirm they "
                               "are separate meters; if one bill repeats the other, mark it as a duplicate.")
                else:
                    trigger, severity = "overlap_same_source_different_document_id", "warning"
                    message = (f"{a.label} and {b.label} both cover {start} to {end} ({days} days) for "
                               f"{_source_name(a)}: those days are counted twice. If one bill replaces or repeats "
                               "the other, mark it as superseded or a duplicate.")
                out.append(_finding("Q-004", trigger, severity, [a, b], message, overlap_days=days,
                                    overlap_start=start, overlap_end=end))
    return out


# =========================================================================================
# Q-005 cross-year, N-003 missing service period
# =========================================================================================
def _cutoff(records: list[EvidenceRecord], period: tuple[date, date] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for record in records:
        if not record.periodic:
            continue
        if record.start is None and record.end is None:
            message = (f"{record.label}: the bill gives no service period, so it is counted in full. Check the "
                       "dates it covers.")
            out.append(_finding("N-003", "date_missing", "review", [record], message))
            continue
        span = _span(record)
        if period is None or span is None:
            continue
        crosses = span[0] < period[0] <= span[1] or span[0] <= period[1] < span[1]
        if not crosses:
            continue
        days = (span[1] - span[0]).days + 1
        inside = _overlap_days(span, period)
        share = round(100 * inside / days, 1)
        message = (f"{record.label} runs {span[0].isoformat()} to {span[1].isoformat()} ({days} days); "
                   f"{inside} days ({share}%) fall in the reporting period and are counted, prorated by days. "
                   "Confirm that splitting by days is reasonable for this bill.")
        out.append(_finding("Q-005", "cross_year_without_allocation_support", "info", [record], message,
                            allocation_method="days_in_service_period", share_percent=share))
    return out


# =========================================================================================
# Public
# =========================================================================================
def run_checks(records: list[EvidenceRecord], period: tuple[date | None, date | None]) -> list[dict[str, Any]]:
    """Every finding, warnings first."""

    reporting = (period[0], period[1]) if period[0] is not None and period[1] is not None else None
    periodic: dict[tuple[str, str, str | None], list[EvidenceRecord]] = defaultdict(list)
    for record in records:
        if record.periodic:
            periodic[(record.category, record.facility.lower(), (record.item or "").lower() or None)].append(record)
    duplicates, duplicate_pairs = _duplicates(records)
    revisions, revision_pairs = _revisions(records)
    findings = [
        *duplicates,
        *revisions,
        *_overlaps(periodic, duplicate_pairs | revision_pairs),
        *(_completeness(periodic, reporting) if reporting else []),
        *_cutoff(records, reporting),
    ]
    order = {"warning": 0, "review": 1, "info": 2}
    return sorted(findings, key=lambda f: order[f["severity"]])
