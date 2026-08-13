"""Validate the intake profile schema seed.

Phase A gate. Proves three things about ``intake/config/profile_schema.json``:

1. Structure - it matches its contract, ``intake/contracts/profile_schema.schema.json``.
2. Reality - every methodology field ID, data schema field name, calculation-method
   route and J2 evidence type it references actually exists. This is CLAUDE.md
   rule 3 ("never invent data fields") made executable.
3. Coverage - every numbered row of ``intake/profile_schema_mapping.md`` sections
   1-6 has exactly one seed entry, and sections 7-8 are fully represented.

Run:

    python intake/scripts/validate_profile_schema.py          # human-readable report
    python intake/scripts/validate_profile_schema.py --quiet  # errors only

Exits 0 when everything passes, 1 otherwise.

The referential and coverage checks are pure Python and always run. Full
JSON-Schema validation of the contract runs when the optional ``jsonschema``
package is installed (see intake/requirements.txt); without it the script still
performs its own structural checks and reports that the deep check was skipped.

Read-only: this script never modifies any file.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

SEED_PATH = "intake/config/profile_schema.json"
CONTRACT_PATH = "intake/contracts/profile_schema.schema.json"
INDEX_PATH = "intake/config/methodology_field_index.json"
MAPPING_PATH = "intake/profile_schema_mapping.md"
EVIDENCE_LIBRARY_PATH = "reference-data/config/libraries/evidence_type_library.json"

# Rows of the mapping's markdown tables begin "| 1.1 |". Sections 7 and 8 are
# unnumbered tables and are covered by explicit expectations instead.
MAPPING_ROW_PATTERN = re.compile(r"^\|\s*(?:\*\*)?(\d\.\d+)(?:\*\*)?\s*\|", re.MULTILINE)
NUMBERED_REF_PATTERN = re.compile(r"^\d\.\d+$")

EXPECTED_METHOD_ROUTE_COUNT = 5
EXPECTED_PROVENANCE_COUNT = 2


class Report:
    """Collects pass/fail results so every check runs before the script exits."""

    def __init__(self, quiet: bool = False) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.checks_run = 0
        self._quiet = quiet

    def check(self, name: str, failures: list[str]) -> None:
        self.checks_run += 1
        if failures:
            self.errors.extend(f"{name}: {failure}" for failure in failures)
            print(f"FAIL  {name} ({len(failures)} problem(s))")
            for failure in failures:
                print(f"        - {failure}")
        elif not self._quiet:
            print(f"ok    {name}")

    def warn(self, message: str) -> None:
        self.warnings.append(message)
        if not self._quiet:
            print(f"warn  {message}")


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"missing required file: {path}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path}: invalid JSON - {exc}")


def _resolve_legacy_path(schema: dict[str, Any], dotted_path: str) -> bool:
    """Return True if a dotted property path resolves inside a JSON Schema document."""
    node = schema
    for part in dotted_path.split("."):
        properties = node.get("properties")
        if not isinstance(properties, dict) or part not in properties:
            return False
        node = properties[part]
    return True


def check_contract(seed: dict[str, Any], contract: dict[str, Any], report: Report) -> None:
    """Validate the seed against its JSON-Schema contract, if jsonschema is present."""
    try:
        import jsonschema
    except ImportError:
        report.warn(
            "jsonschema not installed - deep contract validation skipped "
            "(pip install -r intake/requirements.txt). Structural checks below still ran."
        )
        return

    validator_class = jsonschema.validators.validator_for(contract)
    validator_class.check_schema(contract)
    validator = validator_class(contract)
    failures = []
    for error in sorted(validator.iter_errors(seed), key=lambda e: list(e.absolute_path)):
        location = "/".join(str(part) for part in error.absolute_path) or "<root>"
        failures.append(f"{location}: {error.message}")
    report.check("seed matches its contract (JSON Schema)", failures)


def check_structure(seed: dict[str, Any], report: Report) -> None:
    """Structural checks that do not depend on the optional jsonschema package."""
    datapoints = seed["datapoints"]

    seen: dict[str, int] = {}
    duplicates = []
    for datapoint in datapoints:
        datapoint_id = datapoint["datapoint_id"]
        seen[datapoint_id] = seen.get(datapoint_id, 0) + 1
    duplicates = [f"duplicate datapoint_id {key}" for key, count in seen.items() if count > 1]
    report.check("datapoint IDs are unique", duplicates)

    section_ids = {section["section_id"] for section in seed["sections"]}
    unknown_sections = [
        f"{datapoint['datapoint_id']} references unknown section {datapoint['section']!r}"
        for datapoint in datapoints
        if datapoint["section"] not in section_ids
    ]
    report.check("every datapoint belongs to a declared section", unknown_sections)

    conditions = set(seed["applicability_conditions"])
    unknown_conditions = []
    for datapoint in datapoints:
        condition_ref = datapoint["applicability"]["condition_ref"]
        if condition_ref not in conditions:
            unknown_conditions.append(
                f"{datapoint['datapoint_id']} applicability references undefined condition "
                f"{condition_ref!r}"
            )
        for trigger in datapoint["escalation_triggers"]:
            if trigger["condition_ref"] not in conditions:
                unknown_conditions.append(
                    f"{datapoint['datapoint_id']} escalation trigger references undefined "
                    f"condition {trigger['condition_ref']!r}"
                )
    report.check("applicability and escalation conditions are defined", unknown_conditions)

    valid_classes = {"AUTO", "HUMAN", "SYSTEM"}
    bad_classes = [
        f"{datapoint['datapoint_id']} has class {datapoint['class']!r}"
        for datapoint in datapoints
        if datapoint["class"] not in valid_classes
    ]
    report.check("escalation classes are AUTO / HUMAN / SYSTEM", bad_classes)


def check_methodology_references(
    seed: dict[str, Any], index: dict[str, Any], report: Report
) -> None:
    """CLAUDE.md rule 3: every methodology reference must already exist."""
    fields = index["methodology_fields"]
    failures = []
    for datapoint in seed["datapoints"]:
        for entry in datapoint["populates"]:
            if entry["target_type"] != "methodology_field":
                continue
            field_id = entry["field_id"]
            known = fields.get(field_id)
            if known is None:
                failures.append(
                    f"{datapoint['datapoint_id']} populates unknown methodology field {field_id}"
                )
                continue
            real_fields = set(known["schema_fields"])
            for schema_field in entry["schema_fields"]:
                if schema_field not in real_fields:
                    failures.append(
                        f"{datapoint['datapoint_id']} populates {field_id}.{schema_field}, "
                        f"which is not a data schema field of {field_id}"
                    )
    report.check("every methodology field and sub-field exists", failures)


def check_evidence_references(
    seed: dict[str, Any], index: dict[str, Any], repo_root: Path, report: Report
) -> None:
    """Every J2 reference must exist in the evidence type library."""
    library = _load_json(repo_root / EVIDENCE_LIBRARY_PATH)
    live_ids = {
        str(entry["evidence_type_id"]).strip()
        for entry in library["evidence_types"]
        if entry.get("evidence_type_id")
    }

    indexed_ids = set(index["evidence_type_ids"])
    staleness = []
    if indexed_ids != live_ids:
        staleness.append(
            "methodology_field_index.json evidence types differ from the live library; "
            "re-run intake/scripts/extract_methodology_field_index.py"
        )
    report.check("evidence type index is in sync with the library", staleness)

    failures = []
    for datapoint in seed["datapoints"]:
        for evidence_id in datapoint["evidence_triggered"]:
            if evidence_id not in live_ids:
                failures.append(
                    f"{datapoint['datapoint_id']} triggers unknown evidence type {evidence_id}"
                )
    report.check("every triggered evidence type exists", failures)


def check_legacy_references(seed: dict[str, Any], repo_root: Path, report: Report) -> None:
    """Legacy field paths must resolve inside the referenced legacy schema."""
    failures = []
    cache: dict[str, dict[str, Any]] = {}
    for datapoint in seed["datapoints"]:
        for entry in datapoint["populates"]:
            if entry["target_type"] != "legacy_field":
                continue
            source = entry["source_schema"]
            schema_path = repo_root / source
            if not schema_path.exists():
                failures.append(
                    f"{datapoint['datapoint_id']} references missing legacy schema {source}"
                )
                continue
            if source not in cache:
                cache[source] = _load_json(schema_path)
            if not _resolve_legacy_path(cache[source], entry["field_path"]):
                failures.append(
                    f"{datapoint['datapoint_id']} legacy path {entry['field_path']!r} "
                    f"does not resolve in {source}"
                )
    report.check("legacy field paths resolve", failures)


def check_method_routes(seed: dict[str, Any], index: dict[str, Any], report: Report) -> None:
    """Method-route values must be controlled Calculation_Method values."""
    known_methods = set(index["calculation_methods"])
    failures = []
    for datapoint in seed["datapoints"]:
        route = datapoint.get("method_route")
        if not route:
            continue
        candidates = [route["default_route"]]
        candidates += [item["route"] for item in route["conditional_routes"]]
        candidates += list(route["routes_not_exposed"])
        for value in candidates:
            if value not in known_methods:
                failures.append(
                    f"{datapoint['datapoint_id']} uses route {value!r}, which is not a "
                    f"controlled Calculation_Method value"
                )
    report.check("method routes use controlled calculation methods", failures)


def check_open_items(seed: dict[str, Any], report: Report) -> None:
    """Flagged items must be real, and every provisional entry must be flagged."""
    datapoints = {datapoint["datapoint_id"]: datapoint for datapoint in seed["datapoints"]}
    open_items = seed["open_items"]

    failures = []
    referenced: list[str] = []
    referenced += open_items["pending_expert_signoff"]["datapoint_ids"]
    referenced += open_items["pending_class_confirmation"]["datapoint_ids"]
    referenced += open_items["not_in_scope_v1"]["datapoint_ids"]
    referenced += [item["datapoint_id"] for item in open_items["mapping_shorthand_resolved"]]
    for datapoint_id in referenced:
        if datapoint_id not in datapoints:
            failures.append(f"open_items references unknown datapoint {datapoint_id}")
    report.check("open items reference real datapoints", failures)

    signoff_ids = set(open_items["pending_expert_signoff"]["datapoint_ids"])
    provisional_failures = []
    for datapoint_id, datapoint in datapoints.items():
        if datapoint["provisional"]:
            if not datapoint.get("requires_signoff"):
                provisional_failures.append(f"{datapoint_id} is provisional but names no sign-off owner")
            if datapoint_id not in signoff_ids:
                provisional_failures.append(
                    f"{datapoint_id} is provisional but is not listed in open_items."
                    "pending_expert_signoff"
                )
        elif datapoint_id in signoff_ids:
            provisional_failures.append(
                f"{datapoint_id} is listed as pending sign-off but is not marked provisional"
            )
    report.check("provisional defaults are flagged for expert sign-off", provisional_failures)

    class_ids = set(open_items["pending_class_confirmation"]["datapoint_ids"])
    class_failures = []
    for datapoint_id, datapoint in datapoints.items():
        inferred = datapoint["class_source"] == "inferred_pending_confirmation"
        if inferred and datapoint_id not in class_ids:
            class_failures.append(
                f"{datapoint_id} has an inferred class but is not listed for confirmation"
            )
        if not inferred and datapoint_id in class_ids:
            class_failures.append(
                f"{datapoint_id} is listed for class confirmation but its class came from the mapping"
            )
    report.check("inferred escalation classes are flagged for confirmation", class_failures)


def check_completeness_vs_exclusion(seed: dict[str, Any], report: Report) -> None:
    """A screening 'no' must never be recorded as an EXC-010 exclusion."""
    failures = []
    for datapoint in seed["datapoints"]:
        if datapoint["kind"] != "completeness_rule":
            continue
        for entry in datapoint["populates"]:
            if entry["target_type"] == "methodology_field" and entry["field_id"] == "EXC-010":
                failures.append(
                    f"{datapoint['datapoint_id']} is a completeness rule but writes EXC-010; "
                    "'screened, not present' must never become an exclusion"
                )
    report.check("completeness records are kept separate from EXC-010 exclusions", failures)


def check_mapping_coverage(seed: dict[str, Any], repo_root: Path, report: Report) -> None:
    """Every numbered mapping row must have exactly one seed entry."""
    mapping_text = (repo_root / MAPPING_PATH).read_text(encoding="utf-8")
    expected_refs = set(MAPPING_ROW_PATTERN.findall(mapping_text))

    seed_refs: dict[str, list[str]] = {}
    for datapoint in seed["datapoints"]:
        ref = datapoint["mapping_ref"]
        if NUMBERED_REF_PATTERN.match(ref):
            seed_refs.setdefault(ref, []).append(datapoint["datapoint_id"])

    failures = []
    for ref in sorted(expected_refs - set(seed_refs)):
        failures.append(f"mapping row {ref} has no seed entry")
    for ref in sorted(set(seed_refs) - expected_refs):
        failures.append(f"seed entry claims mapping row {ref}, which is not in the mapping")
    for ref, ids in sorted(seed_refs.items()):
        if len(ids) > 1:
            failures.append(f"mapping row {ref} is claimed by multiple entries: {', '.join(ids)}")
    report.check(
        f"all {len(expected_refs)} numbered mapping rows are represented exactly once", failures
    )

    method_routes = [dp for dp in seed["datapoints"] if dp["kind"] == "method_route"]
    provenance = [dp for dp in seed["datapoints"] if dp["kind"] == "provenance_layer"]
    section_failures = []
    if len(method_routes) != EXPECTED_METHOD_ROUTE_COUNT:
        section_failures.append(
            f"expected {EXPECTED_METHOD_ROUTE_COUNT} method-route entries (mapping section 7), "
            f"found {len(method_routes)}"
        )
    if len(provenance) != EXPECTED_PROVENANCE_COUNT:
        section_failures.append(
            f"expected {EXPECTED_PROVENANCE_COUNT} provenance entries (mapping section 8), "
            f"found {len(provenance)}"
        )
    report.check("mapping sections 7 and 8 are fully represented", section_failures)


def validate(repo_root: Path, quiet: bool = False) -> Report:
    """Run every check and return the report."""
    seed = _load_json(repo_root / SEED_PATH)
    contract = _load_json(repo_root / CONTRACT_PATH)
    index = _load_json(repo_root / INDEX_PATH)

    report = Report(quiet=quiet)
    check_contract(seed, contract, report)
    check_structure(seed, report)
    check_methodology_references(seed, index, report)
    check_evidence_references(seed, index, repo_root, report)
    check_legacy_references(seed, repo_root, report)
    check_method_routes(seed, index, report)
    check_open_items(seed, report)
    check_completeness_vs_exclusion(seed, report)
    check_mapping_coverage(seed, repo_root, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--quiet", action="store_true", help="print failures only")
    args = parser.parse_args(argv)

    report = validate(REPO_ROOT, quiet=args.quiet)

    print()
    if report.errors:
        print(f"FAILED: {len(report.errors)} problem(s) across {report.checks_run} checks")
        return 1
    summary = f"PASSED: {report.checks_run} checks"
    if report.warnings:
        summary += f" ({len(report.warnings)} warning(s))"
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
