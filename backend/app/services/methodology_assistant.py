"""What the in-app assistant may read of the Methodology review: the explanation of a suggestion and a summary of what
Sustentra's AI found. Read-only, built from the stored records only (``methodology_explanation.explain``), so every
sentence the assistant can quote was stored with the suggestion. The model id is never returned. Pure functions: the
endpoints (``api/methodology_assistant.py``) check the organization and the engagement, then load the records.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from backend.app.services import methodology_explanation as ex
from backend.app.services import methodology_review as rules

NOT_FOUND_NOTE = ("No suggestion from Sustentra's AI is stored for that on this engagement. Say so plainly; "
                  "do not guess a reason.")
MAX_MATCHES = 3
MAX_SUMMARY = 80
_STOP = frozenset("why was were is are the a an and or of for to by in on at it its this that what which who how did "
                  "does do suggested suggest suggestion ai sustentra sustentras s find found say said".split())


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.casefold()) if w not in _STOP}


def value_text(value: Any) -> str:
    """A stored value as one short line."""

    if isinstance(value, Mapping):
        return "; ".join(f"{k}: {value_text(v)}" for k, v in value.items() if v not in (None, "", []))
    if isinstance(value, list):
        return ", ".join(value_text(v) for v in value)
    return "" if value is None else str(value)


def _field(field_id: str) -> dict[str, Any] | None:
    return rules.catalog_field(field_id) or rules.row_field(field_id)


def _item(field: Mapping[str, Any], record: Mapping[str, Any]) -> dict[str, Any] | None:
    suggestion = record.get("suggestion")
    shown = ex.explain(field, suggestion)
    if shown is None or not isinstance(suggestion, Mapping):
        return None
    shown = {k: v for k, v in shown.items() if k != "model"}  # the model id is not for the assistant to say
    return {"field_key": str(field["field_id"]), "field": str(field.get("label") or field["field_id"]),
            "suggested_value": value_text(suggestion.get("value")), "review_status": rules.status_of(record),
            "ref": f"doc:{suggestion.get('document_id')}" if suggestion.get("document_id") else None,
            "explanation": shown}


def explain_matches(records: Mapping[str, Mapping[str, Any]], query: str = "", field: str = "") -> dict[str, Any]:
    """The explanation of the suggestion the question is about: the field ``field`` (its id) when given, else the records
    whose field name or suggested value share the most words with ``query`` (at most three, the best ones)."""

    if field:
        definition, record = _field(field), records.get(field)
        found = _item(definition, record) if definition and record else None
        return {"matches": [found]} if found else {"matches": [], "note": NOT_FOUND_NOTE}
    wanted = _words(query)
    scored: list[tuple[int, dict[str, Any]]] = []
    for key, record in records.items():
        defined = _field(key)
        item = _item(defined, record) if defined else None
        if item is None or defined is None:
            continue
        label = _words(f"{defined.get('label', '')} {defined.get('group_label', '')}")
        score = 2 * len(wanted & label) + len(wanted & _words(item["suggested_value"]))
        if score:
            scored.append((score, item))
    scored.sort(key=lambda s: -s[0])
    best = [item for score, item in scored if scored and score == scored[0][0]][:MAX_MATCHES]
    return {"matches": best} if best else {"matches": [], "note": NOT_FOUND_NOTE}


def summary(records: Mapping[str, Mapping[str, Any]], document: str = "") -> dict[str, Any]:
    """Everything Sustentra's AI suggested on the page, one line each (limited to the documents whose file name
    contains ``document`` when given), in the page's order."""

    order = {f["field_id"]: i for i, f in enumerate(rules.CATALOG)}
    rows: list[dict[str, Any]] = []
    for key in sorted(records, key=lambda k: (order.get(k, len(order)), k)):
        field, record = _field(key), records[key]
        suggestion = record.get("suggestion")
        if not field or not isinstance(suggestion, Mapping) or record.get("removed"):
            continue
        sources = [e for e in (suggestion.get("evidence") or []) if isinstance(e, Mapping)] or [suggestion]
        names = {str(s.get("file_name") or "") for s in sources}
        if document and not any(document.casefold() in n.casefold() for n in names):
            continue
        item = _item(field, record)
        if item is None:
            continue
        first = item["explanation"]["items"][0]
        rows.append({"field_key": item["field_key"], "group": field.get("group_label"), "field": item["field"],
                     "suggested_value": item["suggested_value"], "review_status": item["review_status"],
                     "ref": item["ref"], "file": first["file_name"], "location": first["location"],
                     "reason_recorded": item["explanation"]["reason"] is not None})
    meta = records.get(rules.META_KEY) or {}
    out: dict[str, Any] = {"suggestions": rows[:MAX_SUMMARY], "count": len(rows),
                           "read_at": meta.get("prefill_ran_at")}
    if not rows:
        out["note"] = ("Sustentra's AI has no stored suggestions" + (f" from a document named like '{document}'" if document else "")
                       + " on this engagement. Say so; do not guess.")
    return out
