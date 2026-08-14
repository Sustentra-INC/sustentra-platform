"""GEN <-> Scope edge resolution service for Subsystem 2 PR8."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from backend.app.domain.methodology import MethodologyEdge
from backend.app.services.methodology_registry_service import MethodologyRegistryService

EdgeRuntimeTreatment = Literal[
    "foreign_key_join",
    "rule_input",
    "applicability_scope",
    "scope_writes_to_gen",
    "scope_disclosed_via_gen",
    "unsupported_reference_type",
]

REFERENCE_TYPE_TREATMENTS: dict[str, EdgeRuntimeTreatment] = {
    "fk": "foreign_key_join",
    "rule_input": "rule_input",
    "scope": "applicability_scope",
    "writes_to": "scope_writes_to_gen",
    "disclosed_via": "scope_disclosed_via_gen",
}


@dataclass(frozen=True)
class ResolvedMethodologyEdge:
    edge: MethodologyEdge
    treatment: EdgeRuntimeTreatment
    is_join: bool
    field_id: str
    reason: str | None = None


class EdgeResolutionService:
    """Resolves methodology edges relevant to a field."""

    def __init__(self, methodology_registry: MethodologyRegistryService) -> None:
        self._registry = methodology_registry

    def list_edges_for_field(
        self,
        field_id: str,
    ) -> tuple[ResolvedMethodologyEdge, ...]:
        return tuple(
            self._resolve_edge(edge, field_id)
            for edge in self._registry.list_edges_for_field(field_id)
        )

    def list_join_edges_for_field(
        self,
        field_id: str,
    ) -> tuple[ResolvedMethodologyEdge, ...]:
        return tuple(
            edge for edge in self.list_edges_for_field(field_id) if edge.is_join
        )

    def list_non_join_edges_for_field(
        self,
        field_id: str,
    ) -> tuple[ResolvedMethodologyEdge, ...]:
        return tuple(
            edge for edge in self.list_edges_for_field(field_id) if not edge.is_join
        )

    def _resolve_edge(
        self,
        edge: MethodologyEdge,
        field_id: str,
    ) -> ResolvedMethodologyEdge:
        reference_type = (edge.reference_type or "").strip().casefold()
        treatment = REFERENCE_TYPE_TREATMENTS.get(
            reference_type,
            "unsupported_reference_type",
        )
        return ResolvedMethodologyEdge(
            edge=edge,
            treatment=treatment,
            is_join=treatment == "foreign_key_join",
            field_id=field_id,
            reason=None
            if treatment != "unsupported_reference_type"
            else f"Unsupported Reference_Type '{edge.reference_type}'.",
        )
