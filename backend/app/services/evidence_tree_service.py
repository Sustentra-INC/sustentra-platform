"""The Evidence tree and a calculation line's schedule, built from the same reads the
recalculation uses (documents, extraction results, review decisions: injected seams).

All rules live in ``calculation_lines`` (pure); this module gathers the inputs and shapes
the two responses. It writes nothing and logs nothing.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from backend.app.domain import fuel_units
from backend.app.reference.emission_factor_loader import EmissionFactorReference, default_emission_factor_reference
from backend.app.services import calculation_lines as cl
from backend.app.services.engagement_recalculation_service import (
    EngagementRecalculationService,
    parse_inputs,
    setup_facilities,
)
from backend.app.services.reviewed_evidence import (
    REVIEWED,
    THERMAL,
    ReviewedRecord,
    all_decisions,
    group_reviewed_records,
    latest_decisions,
    set_aside_reason,
    superseded_ids,
    to_date,
    to_number,
)

IDENTIFIERS = (("Facility", "facility_name"), ("Service address", "service_address"),
               ("Account number", "account_number"), ("Meter number", "meter_number"))
# The schedule's optional columns, in order: (key, label, extracted field name). A column shows
# only when a row on the line has a value. No extractor produces these fields yet (a column
# appears as soon as one does).
EXTRA_COLUMNS = (("heat_content", "Heat content (HHV)", "heat_content"),
                 ("carbon_content", "Carbon content", "carbon_content"),
                 ("vehicle_type", "Vehicle type", "vehicle_type"),
                 ("model_year", "Model year", "model_year"),
                 ("on_or_non_road", "On-road or non-road", "on_or_non_road"),
                 ("distance", "Distance", "distance"))
THERMAL_LEVEL2 = tuple(level2 for level2, _ in cl.THERMAL_LEVEL2.values())
ACTIVITY_NOTES = {
    "stationary": "fuel quantity combusted", "biogenic": "fuel quantity combusted",
    "mobile": "fuel use quantity", "fugitive": "refrigerant quantity added or recovered",
}
# Plain labels for the fields a record can still be waiting on (the recalculation's awaiting_review).
FIELD_LABELS = {"fuel_type": "Fuel type", "activity_quantity": "Activity quantity", "energy_type": "Energy type",
                "refrigerant_type": "Refrigerant type", "refrigerant_added": "Refrigerant added",
                "equipment_capacity": "Equipment capacity", "refrigerant_recovered": "Refrigerant recovered",
                "service_type": "Service type"}
VERBS = {"accepted": "accepted", "edited": "edited", "rejected": "rejected",
         "needs_more_evidence": "asked for more evidence on"}


@dataclass
class DocState:
    document: dict[str, Any]
    document_id: str
    canonical_type_id: str | None
    extracted_at: str | None
    records: list[ReviewedRecord]
    slots: list[cl.Slot] = field(default_factory=list)
    facility_ids: list[str | None] = field(default_factory=list)  # the Setup facility of each record


@dataclass
class Loaded:
    docs: list[DocState]
    set_aside: list[dict[str, Any]]
    system: list[cl.CalculationLine]
    lines: list[cl.CalculationLine]
    facilities: list[dict[str, Any]]
    period: tuple[date | None, date | None]
    vehicle_groups: list[dict[str, Any]] = field(default_factory=list)


def _iso(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


class EvidenceTreeService:
    def __init__(self, upload_service: Any, pipeline_service: Any, review_service: Any,
                 reference: EmissionFactorReference | None = None) -> None:
        self._upload = upload_service
        self._pipeline = pipeline_service
        self._reviews = review_service
        self._reference = reference

    @property
    def reference(self) -> EmissionFactorReference:
        if self._reference is None:
            self._reference = default_emission_factor_reference()
        return self._reference

    # ------------------------------------------------------------------------------------
    def load(self, engagement: dict[str, Any], can_see: Callable[[dict], bool],
             decisions: dict[str, dict[str, Any]] | None = None) -> Loaded:
        """Every visible document with its records, its default and moved placements, and the
        engagement's lines (system and reviewer-made)."""

        decisions = decisions or {}
        settings = engagement.get("settings") or {}
        facilities = setup_facilities(settings)
        inputs = parse_inputs(settings)
        engagement_id = str(engagement.get("id") or engagement.get("engagement_id"))
        docs: list[DocState] = []
        set_aside: list[dict[str, Any]] = []
        superseded = superseded_ids(decisions)
        for document in self._upload.list_documents(engagement_id):
            if not can_see(document):
                continue
            document_id = str(document.get("document_id"))
            reason = set_aside_reason(decisions, document_id, superseded)
            if reason is not None:
                set_aside.append({"document_id": document_id, "file_name": document.get("file_name"),
                                  "reason": reason})
                continue
            results = [r for r in self._pipeline.list_extraction_results_by_document(document_id) if can_see(r)]
            latest = results[-1] if results else {}
            canonical = str(latest.get("canonical_type_id") or "") or None
            reviews = [d for d in self._reviews.list_by_document(document_id) if can_see(d)]
            records = group_reviewed_records(document, canonical or "", latest.get("items") or [],
                                             latest_decisions(reviews), all_decisions(reviews))
            docs.append(DocState(document, document_id, canonical, _iso(latest.get("created_at")), records))
        placements = {
            id(record): cl.place_record(record, ref=self.reference, facilities=facilities, decisions=decisions,
                                        vehicle_groups=inputs.vehicle_groups, fuel_choices=inputs.fuel_choices)
            for doc in docs for record in doc.records
        }
        system = cl.default_lines(placements.values(), facilities, inputs.vehicle_groups)
        lines = cl.merge_lines(system, cl.user_lines(settings))
        known = {line.key for line in lines}
        filed = cl.file_documents(
            [(doc.document_id, doc.canonical_type_id, [placements[id(r)] for r in doc.records]) for doc in docs],
            decisions, known)
        for doc in docs:
            doc.slots = filed[doc.document_id]
            doc.facility_ids = [cl.facility_anchor_id(f) if (f := placements[id(r)].facility) else None
                                for r in doc.records]
        period = (to_date(engagement.get("reporting_period_start")), to_date(engagement.get("reporting_period_end")))
        return Loaded(docs, set_aside, system, lines, facilities, period, inputs.vehicle_groups)

    def system_line_keys(self, engagement: dict[str, Any], can_see: Callable[[dict], bool],
                         decisions: dict[str, dict[str, Any]] | None = None) -> set[str]:
        return {line.key for line in self.load(engagement, can_see, decisions).system}

    # ------------------------------------------------------------------------------------
    def tree(self, engagement: dict[str, Any], can_see: Callable[[dict], bool],
             decisions: dict[str, dict[str, Any]] | None = None, facility_id: str | None = None) -> dict[str, Any]:
        """The tree. With ``facility_id`` every level shows only placements at that Setup facility
        (rows whose ``facility_id`` and lines whose ``facility_id`` match) and every count is
        recomputed for that view."""

        loaded = self.load(engagement, can_see, decisions)
        by_key = {line.key: line for line in loaded.lines}
        shown_lines = [ln for ln in loaded.lines if facility_id is None or ln.facility_id == facility_id]
        facility_names = {cl.facility_anchor_id(f): str(f.get("name")) for f in loaded.facilities}
        rows: dict[str, list[tuple[dict[str, Any], DocState, cl.Slot]]] = {}
        for doc in loaded.docs:
            for slot in doc.slots:
                row = self._row(doc, slot, by_key, facility_names)
                if facility_id is None or row["facility_id"] == facility_id:
                    rows.setdefault(slot.target, []).append((row, doc, slot))

        def documents(target: str) -> list[dict[str, Any]]:
            return sorted((r for r, _, _ in rows.get(target, [])),
                          key=lambda r: (r["period_start"] or "9999", str(r["file_name"] or "")))

        by_id = {d.document_id: d for d in loaded.docs}

        def counts_of(targets: list[str]) -> dict[str, Any]:
            """Documents distinct; values once per (document, record), however many places show them."""

            seen: set[tuple[str, int]] = set()
            ids: set[str] = set()
            for target in targets:
                for _, doc, slot in rows.get(target, []):
                    ids.add(doc.document_id)
                    seen |= {(doc.document_id, i) for i in slot.records}
            total = {"values": 0, "accepted": 0, "to_review": 0, "issues": 0}
            for document_id, index in seen:
                for name, number in cl.tally([by_id[document_id].records[index]]).items():
                    total[name] += number
            return cl.with_percentage({"documents": len(ids), **total})

        scopes = []
        for scope, scope_label in cl.SCOPES:
            categories = []
            for category, label, owner in cl.CATEGORIES:
                if owner != scope:
                    continue
                in_category = [ln for ln in shown_lines if ln.category == category]
                level2s: dict[str, dict[str, Any]] = {}
                for line in in_category:
                    level2 = level2s.setdefault(line.level2, {"level2": line.level2, "label": line.level2_label,
                                                              "lines": []})
                    level2["lines"].append({"line": line.to_dict(), "counts": counts_of([line.key]),
                                            "documents": documents(line.key)})
                for level2 in level2s.values():
                    level2["counts"] = counts_of([entry["line"]["key"] for entry in level2["lines"]])
                categories.append({
                    "category": category, "label": label, "counts": counts_of([ln.key for ln in in_category]),
                    "level2s": [{k: level2[k] for k in ("level2", "label", "counts", "lines")}
                                for level2 in level2s.values()]})
            in_scope = [ln.key for ln in shown_lines if cl.CATEGORY_SCOPE[ln.category] == scope]
            scopes.append({"scope": scope, "label": scope_label, "categories": categories,
                           "counts": counts_of(in_scope)})
        return {
            "blocks": {
                "summary": documents(cl.BLOCK_SUMMARY), "summary_counts": counts_of([cl.BLOCK_SUMMARY]),
                "unassigned": documents(cl.BLOCK_UNASSIGNED), "unassigned_counts": counts_of([cl.BLOCK_UNASSIGNED]),
                "supporting": {"scopes": scopes, "unassigned": documents(cl.SUPPORTING_UNASSIGNED),
                               "unassigned_counts": counts_of([cl.SUPPORTING_UNASSIGNED])},
            },
            "facilities": [{"facility_id": cl.facility_anchor_id(f), "name": f.get("name"),
                            "address": f.get("address")} for f in loaded.facilities],
            "lines": [line.to_dict() for line in shown_lines],
            # the ids a client uses to create a mobile line (anchor_kind "vehicle_group"), built here
            "vehicle_groups": [{"anchor_id": anchor_id, "label": cl.vehicle_group_label(group),
                                "fuel": group.get("fuel")}
                               for anchor_id, group in cl.vehicle_group_anchors(loaded.vehicle_groups)],
            "anchors_for_contractual": cl.COMPANY_ANCHOR,  # contractual lines: anchor_kind "company"
            "set_aside": loaded.set_aside,
        }

    def _row(self, doc: DocState, slot: cl.Slot, lines: dict[str, cl.CalculationLine],
             facility_names: dict[str, str]) -> dict[str, Any]:
        records = [doc.records[i] for i in sorted(slot.records)]
        periods = [cl.record_period(r) for r in records]
        starts = [p[0] for p in periods if p[0]]
        ends = [p[1] for p in periods if p[1]]
        line = lines.get(slot.target)
        facility_id = line.facility_id if line else None
        if facility_id is None:  # blocks and unassigned: the Setup facility of the shown records, if any
            facility_id = next((doc.facility_ids[i] for i in sorted(slot.records) if doc.facility_ids[i]), None)
        facility_name = facility_names.get(facility_id) if facility_id else None
        if facility_id is None and records:
            name = records[0].best("facility_name")
            facility_name = " ".join(str(name).split()) if name else None
        counts = cl.tally(records)
        return {
            "document_id": doc.document_id, "file_name": doc.document.get("file_name"),
            "period_start": min(starts).isoformat() if starts else None,
            "period_end": max(ends).isoformat() if ends else None,
            "facility_id": facility_id, "facility_name": facility_name,
            "processing_status": doc.document.get("processing_status"),
            "detected_type": cl.type_name(doc.canonical_type_id),
            "also_in": [s.target for s in doc.slots if s.target != slot.target and s.target in lines],
            "values": counts["values"], "accepted": counts["accepted"], "flags": list(slot.flags),
            # what the UI sends as a move's "from" to move this row
            "placement_from": slot.target,
        }

    # ------------------------------------------------------------------------------------
    def schedule(self, engagement: dict[str, Any], can_see: Callable[[dict], bool], key: str,
                 decisions: dict[str, dict[str, Any]] | None = None,
                 name_of: Callable[[str], str] = lambda login: login) -> dict[str, Any] | None:
        """The line's schedule, or None when the engagement has no such line."""

        loaded = self.load(engagement, can_see, decisions)
        line = next((ln for ln in loaded.lines if ln.key == key), None)
        if line is None:
            return None
        # The recalculation decides what counts: a record it lists as awaiting review does not, and
        # the line is calculated only when the recalculation has it.
        recalculation = EngagementRecalculationService(
            self._upload, self._pipeline, self._reviews, self._reference).recalculate(engagement, can_see, decisions)
        waiting_by_record = {(str(a["document_id"]), str(a["record"])): list(a["fields"])
                             for a in recalculation["awaiting_review"]}
        calculated = key in {str(ln["key"]) for ln in recalculation["calculation_lines"]}
        on_line = [(doc, [doc.records[i] for i in sorted(slot.records)])
                   for doc in loaded.docs for slot in doc.slots if slot.target == key]
        values: list[dict[str, Any]] = []
        rows: list[dict[str, Any]] = []
        covered: list[cl.Covered] = []
        history: list[dict[str, Any]] = []
        for doc, records in on_line:
            for record in records:
                name = cl.quantity_field(record)
                item = record.fields.get(name) if name else None
                start, end = cl.record_period(record)
                open_fields = [f for f in waiting_by_record.get((doc.document_id, record.label), []) if f != name]

                def label_of(f: str) -> str:
                    return FIELD_LABELS.get(f, f.replace("_", " ").capitalize())

                rejected = [label_of(f) for f in open_fields if f in record.fields and record.fields[f].status == "rejected"]
                waiting = [label_of(f) for f in open_fields if label_of(f) not in rejected]
                if item is None:
                    rows.append(self._row_of(doc, record, None, None, None, (start, end), name_of, [], []))
                    continue
                thermal = record.canonical_type_id == THERMAL
                unit_text = item.unit or record.best("activity_unit")
                unit = (fuel_units.canonical_unit(str(unit_text), thermal) or str(unit_text)) if unit_text else None
                shown = item.value if item.status in REVIEWED else item.extracted
                reviewed = item.status in REVIEWED
                waiting, rejected = (waiting, rejected) if reviewed else ([], [])
                held = bool(waiting or rejected)  # the recalculation does not count this record yet
                rows.append(self._row_of(doc, record, item, shown, unit, (start, end), name_of, waiting, rejected))
                covered.append(cl.Covered(start, end, to_number(shown), unit, reviewed and not held,
                                          doc.document_id, tuple(waiting)))
                who = name_of(item.reviewer) if item.reviewer else None
                page = (item.source_reference or {}).get("page_number")
                decision = item.status if item.status != "unreviewed" else "not_reviewed"
                if held:
                    decision = "awaiting_other_fields"
                values.append({
                    "service_period_start": _iso(start), "service_period_end": _iso(end),
                    "days": (end - start).days + 1 if start and end and end >= start else None,
                    "quantity": shown, "unit": unit, "document_id": doc.document_id,
                    "file_name": doc.document.get("file_name"), "page": page, "candidate_id": item.candidate_id,
                    "decided_by": who, "decided_at": _iso(item.reviewed_at), "decision": decision,
                    "waiting_on": waiting, "rejected_fields": rejected,
                })
                # every decision on this value, not only the latest
                past = item.history or ([{"decision": item.status, "reviewer_id": item.reviewer,
                                          "reviewed_at": item.reviewed_at, "reviewed_value": item.value,
                                          "reviewed_unit": item.unit}] if item.status in VERBS else [])
                for entry in past:
                    verb = VERBS.get(str(entry.get("decision")))
                    if verb is None:
                        continue
                    reviewed = str(entry.get("decision")) in REVIEWED
                    number = entry.get("reviewed_value") if reviewed else item.extracted
                    entry_unit = (entry.get("reviewed_unit") or unit) if reviewed else unit
                    amount = f"{number} {entry_unit or ''}".strip() if number is not None else "a value"
                    login = entry.get("reviewer_id")
                    history.append({"at": _iso(entry.get("reviewed_at")), "text": (
                        f"{name_of(login) if login else 'A reviewer'} {verb} {amount} from "
                        f"{doc.document.get('file_name')}" + (f", page {page}" if page else ""))})
        values.sort(key=lambda v: (v["service_period_start"] or "9999", str(v["file_name"] or "")))
        rows.sort(key=lambda r: (r["date"]["start"] or "9999", str(r["file_name"] or ""), r["record_key"]))
        extracted = [d.extracted_at for d, _ in on_line if d.extracted_at]
        if values:
            history.append({"at": max(extracted) if extracted else None,
                            "text": f"System extracted {len(values)} {'value' if len(values) == 1 else 'values'} "
                                    f"from {len(on_line)} {'document' if len(on_line) == 1 else 'documents'}"})
        history.sort(key=lambda h: h["at"] or "", reverse=True)
        return {
            "line": line.to_dict(),
            "calculated": calculated,
            "reporting_period": {"start": _iso(loaded.period[0]), "end": _iso(loaded.period[1])},
            "coverage": cl.month_coverage(loaded.period, covered),
            "identifiers": self._identifiers(on_line),
            "identifier_groups": self._identifier_groups(on_line, loaded.facilities, decisions or {}),
            "values": values,
            "rows": rows,
            "columns": self._columns(rows),
            "activity_quantity_note": self._activity_note(line),
            "history": history,
        }

    @staticmethod
    def _row_of(doc: DocState, record: ReviewedRecord, item: Any, shown: Any, unit: str | None,
                period: tuple[date | None, date | None], name_of: Callable[[str], str],
                waiting: list[str], rejected: list[str]) -> dict[str, Any]:
        """One record of the line as a schedule row: every extracted value, accepted or not.
        ``waiting`` / ``rejected``: labels of the record's other required fields the recalculation still
        awaits, or that the reviewer rejected (only for a reviewed quantity); such a row does not count."""

        start, end = period
        reviewed = item is not None and item.status in REVIEWED
        accepted = reviewed and not (waiting or rejected)
        cells: dict[str, dict[str, Any]] = {}
        for key, _, field_name in EXTRA_COLUMNS:
            extra = record.fields.get(field_name)
            value = (extra.value if extra.status in REVIEWED else extra.extracted) if extra is not None else None
            if extra is not None and value not in (None, ""):
                cells[key] = {"value": value, "unit": extra.unit}
        index = record.record_index
        return {
            "record_key": f"{doc.document_id}:{0 if index is None else index}", "record_index": index,
            "accepted": accepted,
            "decision": ("awaiting_other_fields" if waiting or rejected else
                         "not_reviewed" if item is None or item.status == "unreviewed" else item.status),
            "waiting_on": waiting, "rejected_fields": rejected,
            "date": {"start": _iso(start), "end": _iso(end),
                     "days": (end - start).days + 1 if start and end and end >= start else None,
                     "label": cl.date_label(record.canonical_type_id)},
            "activity_quantity": {"value": shown, "unit": unit},
            "cells": cells,
            "saved_by": ({"name": name_of(item.reviewer), "at": _iso(item.reviewed_at)}
                         if reviewed and item.reviewer else None),
            "document_id": doc.document_id, "file_name": doc.document.get("file_name"),
            "page": (item.source_reference or {}).get("page_number") if item is not None else None,
            "candidate_id": item.candidate_id if item is not None else None,
        }

    @staticmethod
    def _columns(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        columns = [{"key": "date", "label": "Date", "unit_in_cells": True},
                   {"key": "activity_quantity", "label": "Activity quantity", "unit_in_cells": True}]
        columns.extend({"key": key, "label": label, "unit_in_cells": True}
                       for key, label, _ in EXTRA_COLUMNS if any(key in row["cells"] for row in rows))
        return columns

    @staticmethod
    def _activity_note(line: cl.CalculationLine) -> str | None:
        if line.category == "purchased_energy":
            what: str | None = ("thermal energy purchased" if line.level2 in THERMAL_LEVEL2
                                else "electricity quantity purchased")
        else:
            what = ACTIVITY_NOTES.get(line.category)
        return f"Activity quantity: {what}" if what else None

    @staticmethod
    def _identifier_groups(on_line: list[tuple[DocState, list[ReviewedRecord]]], facilities: list[dict[str, Any]],
                           decisions: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        """Each identifier with its documents grouped by value, and the documents without it."""

        out: list[dict[str, Any]] = []
        for label, field_name in IDENTIFIERS:
            is_facility = field_name == "facility_name"
            groups: dict[str, dict[str, dict[str, Any]]] = {}
            for doc, records in on_line:
                for record in records:
                    how: str | None = None
                    if is_facility:
                        found = cl.facility_match(facilities, decisions, doc.document_id, record)
                        text, how = (str(found[0].get("name")), found[1]) if found else ("", None)
                    else:
                        raw = record.best(field_name)
                        text = " ".join(str(raw).split()) if raw not in (None, "") else ""
                    if not text:
                        continue
                    entry = {"document_id": doc.document_id, "file_name": doc.document.get("file_name")}
                    if is_facility:
                        entry["matched_by"] = how
                    groups.setdefault(text, {}).setdefault(doc.document_id, entry)
            with_value = {d for docs in groups.values() for d in docs}
            item: dict[str, Any] = {
                "label": label,
                "values": [{"value": value, "documents": sorted(docs.values(), key=lambda d: str(d["file_name"]))}
                           for value, docs in sorted(groups.items())],
                "not_found": [{"document_id": d.document_id, "file_name": d.document.get("file_name")}
                              for d, _ in on_line if d.document_id not in with_value],
                "documents_with": len(with_value), "documents_total": len(on_line),
            }
            if is_facility:
                item["matched_by"] = sorted({str(d["matched_by"]) for g in groups.values() for d in g.values()})
            out.append(item)
        return out

    @staticmethod
    def _identifiers(on_line: list[tuple[DocState, list[ReviewedRecord]]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for label, field_name in IDENTIFIERS:
            found: dict[str, set[str]] = {}
            for doc, records in on_line:
                for record in records:
                    value = record.best(field_name)
                    text = " ".join(str(value).split()) if value not in (None, "") else ""
                    if text:
                        found.setdefault(text, set()).add(doc.document_id)
            out.extend({"label": label, "value": value, "documents_with": len(ids), "documents_total": len(on_line)}
                       for value, ids in sorted(found.items()))
        return out
