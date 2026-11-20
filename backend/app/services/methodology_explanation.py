"""Why Sustentra's AI suggested what it did, for a Methodology field: the explanation shown beside "Suggested by
Sustentra's AI" and read back by the in-app assistant.

Every line of it comes from what is stored with the suggestion, and nothing is invented:

* the AI's own ``reason`` (at most 240 characters; absent on a suggestion saved before reasons were kept);
* the document, the page and the exact quote;
* the checks the suggestion passed, worked out again from the stored value and quote with the same rules the
  server used to keep it (a check that does not hold on the stored data is not listed);
* when it was read and by which model;
* what was implied and how (a start date worked out from "year ended ...", a year taken from the title).

Pure functions: no database, no model call, no document is read.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from backend.app.services import methodology_prefill as mp
from backend.app.services import methodology_review as rules
from backend.app.services.ai_locator import norm, value_in_quote
from backend.app.services.ai_reason import NO_REASON



def _location(reference: Any) -> tuple[int | None, str]:
    """The page (when the reference has one) and the plain location text ("page 4", "Sheet1, B12", "")."""

    if isinstance(reference, str):
        return None, reference.strip()
    if not isinstance(reference, Mapping):
        return None, ""
    sheet = str(reference.get("sheet_name") or "").strip()
    cell = str(reference.get("cell_or_range") or "").strip()
    raw = reference.get("page_number")
    page = raw if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0 else None
    if sheet or cell:
        return page, ", ".join(x for x in (sheet, cell) if x)
    return page, f"page {page}" if page else ""


def _matched(terms: tuple[str, ...], quote: str) -> str | None:
    """The first of ``terms`` the quote names as a whole word or phrase, not negated."""

    return next((t for t in terms if mp.names_option(quote, (t,)) == "yes"), None)


def _num(number: Any) -> str:
    return format(number, "g") if isinstance(number, (int, float)) and not isinstance(number, bool) else str(number)


def _choice_checks(field_id: str, value: Any, quote: str) -> list[str]:
    if field_id == "consolidation_approach":
        term = next((t for t in mp._CHOICE_TERMS.get(str(value), ()) if t in norm(quote)), None)
        return [f"The wording matched: '{term}' → {value}."] if term else []
    if field_id in mp._GAS_TERMS:
        term = next((t for t in mp._GAS_TERMS[field_id] if t in norm(quote)), None)
        return [f"The quote names the gas: matched '{term}' → {value}."] if term else []
    return []


def _option_checks(field_id: str, entry: Any, quote: str) -> list[str]:
    option = str(entry.get("option") or "") if isinstance(entry, Mapping) else ""
    if not option:
        return []
    if field_id == rules.SCOPES_ID:
        if mp.names_scope(quote, option) == "yes":
            return [f"The quote names {option} as covered, with no negation or future wording before or after it."]
        return []
    term = _matched(mp._OPTION_TERMS.get(option, ()), quote)
    out = [f"The wording matched: '{term}' → {option}."] if term else []
    wording = str(entry.get("wording") or "")
    if wording and norm(wording) in norm(quote):
        out.append(f"The company's own wording, “{wording}”, is printed in the quote.")
    return out


def _period_checks(value: Any, quote: str) -> tuple[list[str], list[str]]:
    """Checks and implied notes for a reporting period (``value`` is {start, end, ...})."""

    checks: list[str] = []
    implied: list[str] = []
    if not isinstance(value, Mapping):
        return checks, implied
    start, end = rules.parse_iso_date(value.get("start")), rules.parse_iso_date(value.get("end"))
    if start is None or end is None:
        return checks, implied
    printed = mp.dates_in(quote)
    if value.get("implied_from") == rules.IMPLIED_FROM_TITLE:
        implied.append(
            f"Start and end implied: the quote says “calendar year” and prints no date, so the year {start.year} "
            f"is taken from the document's title and the period is {start.isoformat()} to {end.isoformat()}.")
        return checks, implied
    if end in printed:
        checks.append(f"The end date, {end.isoformat()}, is printed in the quote.")
    if start in printed:
        checks.append(f"The start date, {start.isoformat()}, is printed in the quote.")
    elif value.get("start_implied") and end in printed and start == rules.year_start_for(end) and mp.states_a_year(quote, end):
        implied.append(
            f"Start date implied: the quote states a year ended {end.isoformat()} and prints no start, "
            f"so the start is the first day of that year, {start.isoformat()}.")
    basis = value.get("basis")
    if basis and mp.basis_in_words(quote) == basis:
        checks.append(f"The period basis, {basis}, is the quote's own wording.")
    return checks, implied


def _gwp_checks(value: Any, quote: str) -> list[str]:
    if not isinstance(value, Mapping):
        return []
    set_, horizon = str(value.get("set") or ""), str(value.get("horizon") or "")
    if set_ not in mp._GWP_TERMS or not mp.set_named(quote, set_):
        return []
    out = [f"The quote names the {set_} set."]
    if horizon == "Not stated":
        if mp.set_without_horizon(quote, set_):
            out.append(f"The quote gives no time horizon for {set_}, so none is recorded.")
    elif mp.set_has_horizon(quote, set_, horizon):
        out.append(f"The {horizon} horizon is named beside {set_} in the quote.")
    return out


def _entity_checks(value: Any, quote: str) -> list[str]:
    if not isinstance(value, Mapping):
        return []
    name = str(value.get("name") or "")
    out: list[str] = []
    if name and value_in_quote(name, quote):
        out.append(f"The entity's name, {name}, is printed in the quote.")
    for key, label in (("equity_share_pct", "equity share"), ("financial_control", "financial control")):
        number = value.get(key)
        if number is not None and value_in_quote(_num(number), quote):
            out.append(f"The {label} figure, {_num(number)}%, is printed in the quote.")
    included, _ = mp.entity_statement(quote, name)
    if included:
        out.append("The quote says the entity is inside the boundary (it is not a sentence that leaves it out).")
    if value.get("control_quoted") in ("Yes", "No"):
        out.append(f"The quote itself states operational control: {value['control_quoted']}.")
    return out


def _factor_checks(value: Any, quote: str) -> list[str]:
    edition = str(value.get("edition") or "") if isinstance(value, Mapping) else ""
    if edition and any(ch.isdigit() for ch in edition) and value_in_quote(edition, quote):
        return [f"The edition, {edition}, is printed in the quote."]
    return []


def _text_checks(field_id: str, value: Any, quote: str) -> list[str]:
    if field_id == rules.BOUNDARY_SENTENCE_ID and isinstance(value, str):
        if norm(value) in norm(quote) and mp.states_boundary_coverage(value):
            return ["The sentence is printed in the quote and says what the boundary covers, not what it leaves out."]
    return []


def _entry_checks(entry: Any, quote: str) -> list[str]:
    source = str(entry.get("source_type") or "") if isinstance(entry, Mapping) else ""
    return [f"The quote names the source type, {source}."] if source and value_in_quote(source, quote) else []


def _checks(field: Mapping[str, Any], value: Any, quote: str, index: int) -> tuple[list[str], list[str]]:
    """The field-specific checks of one quote and the things implied in it."""

    field_id, kind = str(field["field_id"]), str(field.get("kind"))
    entry = value[index] if isinstance(value, list) and index < len(value) else None
    if kind == "enum":
        return _choice_checks(field_id, value, quote), []
    if kind == "multiselect":
        return _option_checks(field_id, entry, quote), []
    if kind == "entry_list":
        return _entry_checks(entry, quote), []
    if kind == "date_range":
        return _period_checks(value, quote)
    if kind == "gwp":
        return _gwp_checks(value, quote), []
    if kind == "entity":
        return _entity_checks(value, quote), []
    if kind == "factor":
        return _factor_checks(value, quote), []
    if kind == "text":
        return _text_checks(field_id, value, quote), []
    return [], []


def explain(field: Mapping[str, Any], suggestion: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The explanation of one stored suggestion, or None when the field has none. ``field`` is the catalog or
    row definition. Safe on a suggestion saved before reasons were kept: ``reason`` is then None and
    ``reason_note`` says so."""

    if not isinstance(suggestion, Mapping):
        return None
    value = suggestion.get("value")
    evidence = [e for e in (suggestion.get("evidence") or []) if isinstance(e, Mapping)]
    # A reporting period's evidence repeats its own quote first, then adds the title line (when the year came from it).
    if str(field.get("kind")) == "date_range":
        sources: list[Mapping[str, Any]] = [suggestion, *evidence[1:]]
    else:
        sources = evidence or [suggestion]
    items: list[dict[str, Any]] = []
    for index, source in enumerate(sources):
        quote = str(source.get("quote") or "")
        page, location = _location(source.get("source_reference"))
        file_name = str(source.get("file_name") or "")
        checks: list[str] = []
        implied: list[str] = []
        if quote and file_name:
            where = f", {location}" if location else ""
            checks.append(f"The quote was found on the document ({file_name}{where}) when it was read.")
        if index == 0 or str(field.get("kind")) != "date_range":
            more, notes = _checks(field, value, quote, index)
            checks += more
            implied += notes
        elif source.get("label"):
            year = rules.parse_iso_date((value or {}).get("start")) if isinstance(value, Mapping) else None
            if year is not None and mp.single_year_of(quote) == year.year:
                checks.append(
                    f"The title-year rule holds: this heading prints the single year {year.year}, and it is the "
                    "document's first heading.")
        reason = " ".join(str(source.get("reason") or "").split()) or None
        items.append({"label": str(source.get("label") or "") or None, "reason": reason, "quote": quote,
                      "document_id": str(source.get("document_id") or ""), "file_name": file_name,
                      "page": page, "location": location, "checks": checks, "implied": implied})
    reason = next((i["reason"] for i in items if i["reason"]), None)
    return {"field_id": str(field["field_id"]), "label": str(field.get("label") or field["field_id"]),
            "reason": reason, "reason_note": None if reason else NO_REASON,
            "read_at": suggestion.get("suggested_at"), "model": suggestion.get("model"), "items": items}


def as_text(explanation: Mapping[str, Any]) -> str:
    """The explanation as plain sentences, for the assistant (and anywhere text is wanted)."""

    lines = [f"Field: {explanation['label']}"]
    for item in explanation["items"]:
        head = f"{item['label']}: " if item.get("label") else ""
        lines.append(f"{head}Reason (Sustentra's AI, as recorded): {item['reason'] or NO_REASON}")
        where = f"{item['file_name']}, {item['location']}" if item["location"] else item["file_name"]
        lines.append(f"{head}Evidence: “{item['quote']}” ({where})")
        for check in item["checks"]:
            lines.append(f"{head}Check passed: {check}")
        for note in item["implied"]:
            lines.append(f"{head}{note}")
    if explanation.get("read_at"):
        lines.append(f"Read on {explanation['read_at']}.")
    return "\n".join(lines)
