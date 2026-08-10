"""Runtime verification rule loader for Subsystem 2 PR10."""

from __future__ import annotations

import re
from pathlib import Path

from backend.app.domain.methodology import MethodologyBundle, VerificationRule
from backend.app.domain.verification_rule import RuntimeVerificationRule
from backend.app.reference.methodology_loader import load_default_methodology_bundle
from backend.app.services.methodology_registry_service import MethodologyRegistryService

FIELD_ID_PATTERN = re.compile(r"\b(?:S[12]-[A-Z0-9]+-\d+|[A-Z]{3}-\d+)\b")


def load_default_verification_rules(
    repo_root: Path | None = None,
) -> tuple[RuntimeVerificationRule, ...]:
    """Load runtime verification rules from the default methodology bundle."""

    bundle = load_default_methodology_bundle(repo_root=repo_root)
    return load_verification_rules(bundle)


def load_verification_rules(
    bundle: MethodologyBundle,
) -> tuple[RuntimeVerificationRule, ...]:
    """Convert methodology workbook rules into runtime verification rules."""

    registry = MethodologyRegistryService(bundle)
    return tuple(_runtime_rule(rule, registry) for rule in bundle.rules)


def _runtime_rule(
    rule: VerificationRule,
    registry: MethodologyRegistryService,
) -> RuntimeVerificationRule:
    resolvable: list[str] = []
    unresolved: list[str] = []
    for applies_to in rule.applies_to:
        refs = FIELD_ID_PATTERN.findall(applies_to)
        if not refs:
            unresolved.append(applies_to)
            continue
        for ref in refs:
            if registry.get_row(ref) is None:
                unresolved.append(ref)
            elif ref not in resolvable:
                resolvable.append(ref)
    status = (rule.status or "").strip().casefold()
    return RuntimeVerificationRule(
        rule_id=rule.rule_id,
        layer=rule.layer,
        rule_type=rule.rule_type,
        assertion=rule.assertion,
        applies_to=rule.applies_to,
        grain_key=rule.grain_key,
        rule_expression=rule.rule_expression,
        source=rule.source,
        status=rule.status,
        notes=rule.notes,
        is_provisional=status == "confirm",
        resolvable_applies_to=tuple(resolvable),
        unresolved_applies_to=tuple(unresolved),
        source_workbook=rule.source_workbook,
        source_sheet=rule.source_sheet,
        source_row_number=rule.source_row_number,
    )
