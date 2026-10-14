"""Emissions roll-up: category results -> Scope 1, Scope 2 and inventory totals -> final outputs.

Claire's roll-up chart (GHG Required Data, Structure Breakdown): once each emission category
has its result, the system adds them up and checks the company's reported numbers.

    Step 1a   category results to Scope 1: each Scope 1 category, each gas (CO2, CH4, N2O,
              HFCs, PFCs, SF6, NF3, plus "other" so the gases reconcile), the Scope 1 total,
              and biogenic CO2 as a memo outside every total.
    Step 1b   category results to Scope 2, location-based and market-based.
    Step 2    inventory totals: Scope 1 + Scope 2, once per Scope 2 basis.
    Final     the values companies must report (workbook rows 22-50), each compared with its
    outputs   node: difference, difference %, and within the materiality threshold or not.

Honesty rules:
- A category not built yet, or built but without evidence, is null ("not available"), never
  a silent 0. A total missing one is "partial" and names what is missing.
- Only the reviewer's confirmation that the company has no such source (with a reason,
  ``settings.recalculation.absent_sources``) makes a category a true 0.
- A partial total is never "within tolerance": it is "incomplete", unless it already exceeds
  the reported value by more than the threshold and every contribution is >= 0 (missing
  categories can then only add).

Pure: no I/O. The tables below are the whole contract; re-mapping to the chart means editing
``LAYOUT`` (steps, labels, order), not the keys or the logic.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from backend.app.domain.refrigerants import find_refrigerant
from backend.app.reference.emission_factor_loader import (
    GAS_GROUPS,
    EmissionFactorNotFoundError,
    EmissionFactorReference,
)
from backend.app.services import emissions_calculator as calc

ROLLUP_VERSION = 1
GROUPS: tuple[str, ...] = GAS_GROUPS + ("other",)
COMBUSTION_GASES = ("CO2", "CH4", "N2O")
EPSILON = 1e-12


# =========================================================================================
# Sources: one per workbook emission source, built or not
# =========================================================================================
@dataclass(frozen=True)
class Source:
    key: str
    label: str
    scope: str  # "scope1" | "scope2"
    workbook_row: int
    built: bool
    backend: Mapping[str, str]  # basis ("location" / "market") -> recalculation category key
    gases: tuple[str, ...]  # gas groups it can emit


SOURCES: tuple[Source, ...] = (
    Source("stationary_combustion", "Stationary combustion", "scope1", 42, True,
           {"location": "stationary_combustion"}, COMBUSTION_GASES),
    Source("mobile_combustion", "Mobile combustion", "scope1", 43, True,
           {"location": "mobile_combustion"}, COMBUSTION_GASES),
    Source("process_sources", "Process sources", "scope1", 44, False, {}, GAS_GROUPS),
    Source("fugitive_refrigerants", "Fugitive: refrigeration, AC and fire suppression", "scope1", 45, True,
           {"location": "fugitive_refrigerants"}, ("CO2", "HFCs", "PFCs", "SF6", "NF3", "other")),
    Source("fugitive_purchased_gases", "Fugitive: purchased industrial gases", "scope1", 45, False, {},
           GROUPS),
    Source("agricultural_sources", "Agricultural sources", "scope1", 46, False, {}, COMBUSTION_GASES),
    Source("purchased_electricity", "Purchased electricity", "scope2", 47, True,
           {"location": "purchased_electricity_location_based", "market": "purchased_electricity_market_based"},
           COMBUSTION_GASES),
    Source("purchased_steam", "Purchased steam", "scope2", 48, True,
           {"location": "purchased_steam_location_based", "market": "purchased_steam_market_based"},
           COMBUSTION_GASES),
    Source("purchased_heating", "Purchased heating", "scope2", 49, True,
           {"location": "purchased_heating_location_based", "market": "purchased_heating_market_based"},
           COMBUSTION_GASES),
    Source("purchased_cooling", "Purchased cooling", "scope2", 50, False, {}, COMBUSTION_GASES),
)
SOURCE_BY_KEY = {s.key: s for s in SOURCES}
SOURCE_KEYS = frozenset(SOURCE_BY_KEY)
SCOPE1_SOURCES = tuple(s.key for s in SOURCES if s.scope == "scope1")
SCOPE2_SOURCES = tuple(s.key for s in SOURCES if s.scope == "scope2")


# =========================================================================================
# Nodes: Steps 1a, 1b and 2
# =========================================================================================
@dataclass(frozen=True)
class Node:
    key: str
    label: str
    kind: str  # "category" | "gas" | "total" | "memo"
    scope: str  # "scope1" | "scope2_location" | "scope2_market" | "inventory_location" | "inventory_market"
    basis: str  # "location" | "market": which Scope 2 result a source contributes
    terms: tuple[str, ...]  # "category:<source>" or "node:<key>" (gas nodes add contributors at runtime)
    formula: str
    gas: str | None = None
    structural_zero: bool = False

    @property
    def unit(self) -> str:
        if self.kind == "gas":
            return "t and t CO2e"
        return "t CO2" if self.kind == "memo" else "t CO2e"


def _category(key: str, label: str, scope: str, basis: str, sources: tuple[str, ...]) -> Node:
    return Node(key, label, "category", scope, basis, tuple(f"category:{s}" for s in sources), " + ".join(sources))


def _gas_nodes(prefix: str, scope: str, basis: str, sources: tuple[str, ...], gases: tuple[str, ...],
               label_prefix: str, suffix: str = "") -> tuple[Node, ...]:
    out = []
    for gas in gases:
        capable = tuple(s for s in sources if gas in SOURCE_BY_KEY[s].gases)
        name = "other gases" if gas == "other" else gas
        out.append(Node(f"{prefix}_{'other_gases' if gas == 'other' else gas.lower()}",
                        f"{label_prefix} {name}{suffix}", "gas", scope, basis,
                        tuple(f"category:{s}" for s in capable),
                        f"sum of {name} over {label_prefix} sources", gas=gas))
    return tuple(out)


_S1_CATEGORY_NODES = (
    _category("stationary_combustion_total", "Direct emissions from stationary combustion", "scope1", "location",
              ("stationary_combustion",)),
    _category("mobile_combustion_total", "Direct emissions from mobile combustion", "scope1", "location",
              ("mobile_combustion",)),
    _category("process_total", "Direct emissions from process sources", "scope1", "location", ("process_sources",)),
    _category("fugitive_total", "Direct emissions from fugitive sources", "scope1", "location",
              ("fugitive_refrigerants", "fugitive_purchased_gases")),
    _category("agricultural_total", "Direct emissions from agricultural sources", "scope1", "location",
              ("agricultural_sources",)),
)
_S2_LOCATION_NODES = (
    _category("purchased_electricity_total", "Indirect emissions from purchased electricity (location-based)",
              "scope2_location", "location", ("purchased_electricity",)),
    _category("purchased_steam_total", "Indirect emissions from purchased steam", "scope2_location", "location",
              ("purchased_steam",)),
    _category("purchased_heating_total", "Indirect emissions from purchased heating", "scope2_location", "location",
              ("purchased_heating",)),
    _category("purchased_cooling_total", "Indirect emissions from purchased cooling", "scope2_location", "location",
              ("purchased_cooling",)),
)
_S2_MARKET_NODES = (
    _category("purchased_electricity_market_total", "Indirect emissions from purchased electricity (market-based)",
              "scope2_market", "market", ("purchased_electricity",)),
    _category("purchased_steam_market_total", "Indirect emissions from purchased steam (market-based)",
              "scope2_market", "market", ("purchased_steam",)),
    _category("purchased_heating_market_total", "Indirect emissions from purchased heating (market-based)",
              "scope2_market", "market", ("purchased_heating",)),
    _category("purchased_cooling_market_total", "Indirect emissions from purchased cooling (market-based)",
              "scope2_market", "market", ("purchased_cooling",)),
)


def _total(key: str, label: str, scope: str, basis: str, children: tuple[str, ...]) -> Node:
    return Node(key, label, "total", scope, basis, tuple(f"node:{c}" for c in children), " + ".join(children))


NODES: tuple[Node, ...] = (
    # Step 1a
    *_S1_CATEGORY_NODES,
    *_gas_nodes("scope1", "scope1", "location", SCOPE1_SOURCES, GROUPS, "Scope 1"),
    _total("scope1_total", "Scope 1 (Total)", "scope1", "location", tuple(n.key for n in _S1_CATEGORY_NODES)),
    Node("biogenic_co2", "CO2 emissions from biogenic combustion", "memo", "scope1", "location",
         ("category:stationary_combustion", "category:mobile_combustion"),
         "biogenic CO2 of stationary + mobile combustion (reported separately, in no total)"),
    # Step 1b
    *_S2_LOCATION_NODES,
    _total("scope2_location_total", "Scope 2 (Total), location-based", "scope2_location", "location",
           tuple(n.key for n in _S2_LOCATION_NODES)),
    *_gas_nodes("scope2", "scope2_location", "location", SCOPE2_SOURCES, COMBUSTION_GASES, "Scope 2",
                " (location-based)"),
    *(Node(f"scope2_{gas.lower()}", f"Scope 2 {gas}", "gas", "scope2_location", "location", (),
           "0: no Scope 2 method emits fluorinated gases", gas=gas, structural_zero=True)
      for gas in ("HFCs", "PFCs", "SF6", "NF3")),
    *_S2_MARKET_NODES,
    _total("scope2_market_total", "Scope 2 (Total), market-based", "scope2_market", "market",
           tuple(n.key for n in _S2_MARKET_NODES)),
    *_gas_nodes("scope2_market", "scope2_market", "market", SCOPE2_SOURCES, COMBUSTION_GASES, "Scope 2",
                " (market-based)"),
    # Step 2
    _total("inventory_location_total", "Inventory total, location-based (Scope 1 + Scope 2)", "inventory_location",
           "location", ("scope1_total", "scope2_location_total")),
    _total("inventory_market_total", "Inventory total, market-based (Scope 1 + Scope 2)", "inventory_market",
           "market", ("scope1_total", "scope2_market_total")),
)
NODE_BY_KEY = {n.key: n for n in NODES}

LAYOUT: tuple[dict[str, Any], ...] = (
    {"key": "step_1a", "label": "Step 1a · Category results to Scope 1", "order": 1,
     "node_keys": [n.key for n in NODES if n.scope == "scope1"]},
    {"key": "step_1b", "label": "Step 1b · Category results to Scope 2 (location-based and market-based)", "order": 2,
     "node_keys": [n.key for n in NODES if n.scope.startswith("scope2")]},
    {"key": "step_2", "label": "Step 2 · Inventory totals", "order": 3,
     "node_keys": [n.key for n in NODES if n.scope.startswith("inventory")]},
)
STEP_OF = {key: step["key"] for step in LAYOUT for key in step["node_keys"]}


# =========================================================================================
# Final outputs: the reported data points (workbook "Data from summary documents")
# =========================================================================================
@dataclass(frozen=True)
class FinalOutput:
    key: str
    label: str
    workbook_row: int
    requirement: str  # "Required" | "Optional"
    node: str
    default_measure: str | None  # "co2e_t" | "mass_t" | None (unit to be confirmed)

    @property
    def gas_row(self) -> bool:
        return NODE_BY_KEY[self.node].kind == "gas"


FINAL_OUTPUTS: tuple[FinalOutput, ...] = (
    FinalOutput("scope1_total", "Scope 1 (Total)", 22, "Required", "scope1_total", "co2e_t"),
    FinalOutput("scope1_co2", "Scope 1 CO2", 23, "Required", "scope1_co2", "mass_t"),
    FinalOutput("scope1_ch4", "Scope 1 CH4", 24, "Required", "scope1_ch4", "mass_t"),
    FinalOutput("scope1_n2o", "Scope 1 N2O", 25, "Required", "scope1_n2o", "mass_t"),
    FinalOutput("scope1_hfcs", "Scope 1 HFCs", 26, "Required", "scope1_hfcs", None),
    FinalOutput("scope1_pfcs", "Scope 1 PFCs", 27, "Required", "scope1_pfcs", None),
    FinalOutput("scope1_sf6", "Scope 1 SF6", 28, "Required", "scope1_sf6", None),
    FinalOutput("scope2_location_total", "Scope 2 (Total), location-based", 29, "Required", "scope2_location_total",
                "co2e_t"),
    FinalOutput("scope2_market_total", "Scope 2 (Total), market-based", 29, "Required", "scope2_market_total",
                "co2e_t"),
    FinalOutput("scope2_co2", "Scope 2 CO2 (location-based)", 30, "Required", "scope2_co2", "mass_t"),
    FinalOutput("scope2_ch4", "Scope 2 CH4 (location-based)", 31, "Required", "scope2_ch4", "mass_t"),
    FinalOutput("scope2_n2o", "Scope 2 N2O (location-based)", 32, "Required", "scope2_n2o", "mass_t"),
    FinalOutput("scope2_hfcs", "Scope 2 HFCs", 33, "Required", "scope2_hfcs", None),
    FinalOutput("scope2_pfcs", "Scope 2 PFCs", 34, "Required", "scope2_pfcs", None),
    FinalOutput("scope2_sf6", "Scope 2 SF6", 35, "Required", "scope2_sf6", None),
    FinalOutput("scope2_nf3", "Scope 2 NF3", 36, "Required", "scope2_nf3", None),
    FinalOutput("biogenic_co2", "CO2 emissions from biogenic combustion", 37, "Required", "biogenic_co2", "co2e_t"),
    FinalOutput("stationary_combustion_total", "Direct emissions from stationary combustion", 42, "Optional",
                "stationary_combustion_total", "co2e_t"),
    FinalOutput("mobile_combustion_total", "Direct emissions from mobile combustion", 43, "Optional",
                "mobile_combustion_total", "co2e_t"),
    FinalOutput("process_total", "Direct emissions from process sources", 44, "Optional", "process_total", "co2e_t"),
    FinalOutput("fugitive_total", "Direct emissions from fugitive sources", 45, "Optional", "fugitive_total",
                "co2e_t"),
    FinalOutput("agricultural_total", "Direct emissions from agricultural sources", 46, "Optional",
                "agricultural_total", "co2e_t"),
    FinalOutput("purchased_electricity_total", "Indirect emissions from purchased electricity (location-based)", 47,
                "Optional", "purchased_electricity_total", "co2e_t"),
    FinalOutput("purchased_steam_total", "Indirect emissions from purchased steam", 48, "Optional",
                "purchased_steam_total", "co2e_t"),
    FinalOutput("purchased_heating_total", "Indirect emissions from purchased heating", 49, "Optional",
                "purchased_heating_total", "co2e_t"),
    FinalOutput("purchased_cooling_total", "Indirect emissions from purchased cooling", 50, "Optional",
                "purchased_cooling_total", "co2e_t"),
)
FINAL_OUTPUT_KEYS = frozenset(o.key for o in FINAL_OUTPUTS)
# Rows whose unit (tonnes of gas or t CO2e) the reviewer can set: the per-gas rows 23-28, 30-36.
UNIT_KEYS = frozenset(o.key for o in FINAL_OUTPUTS if o.gas_row)
OUTPUT_STATUSES = ("within_tolerance", "exceeds_tolerance", "incomplete", "needs_unit", "not_reported",
                   "no_evidence", "not_recalculated", "not_in_scope")


# =========================================================================================
# Evaluation
# =========================================================================================
@dataclass
class _Line:
    key: str
    groups: dict[str, dict[str, float]]
    flags: list[str]


@dataclass
class _SourceState:
    source: Source
    status: str
    open_items: int
    absent_reason: str | None
    gaps: list[dict[str, Any]] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)  # the source's own flags plus every line's
    source_flags: list[str] = field(default_factory=list)  # the source's own flags only
    vectors: dict[str, dict[str, dict[str, float]] | None] = field(default_factory=dict)  # basis -> group vector
    biogenic: float | None = None
    lines: list[_Line] = field(default_factory=list)
    # Gas groups (and "biogenic") with a negative line: a partial value that includes one is no lower bound.
    negative: set[str] = field(default_factory=set)

    @property
    def backed(self) -> bool:
        return self.status in ("calculated", "partial")

    @property
    def contributes(self) -> bool:
        return self.backed or self.status == "confirmed_absent"


def _zeros() -> dict[str, dict[str, float]]:
    return {g: {"mass_t": 0.0, "co2e_t": 0.0} for g in GROUPS}


def _combustion_vector(result: calc.CategoryResult) -> dict[str, dict[str, float]]:
    vector = _zeros()
    for gas in COMBUSTION_GASES:
        vector[gas] = {"mass_t": float(result.total_mass_t.get(gas, 0.0)),
                       "co2e_t": float(result.total_co2e_t.get(gas, 0.0))}
    return vector


def _hub_gwp_ar5(ref: EmissionFactorReference, gas: str) -> float | None:
    try:
        return ref.gwp(gas, "AR5").value
    except EmissionFactorNotFoundError:
        return None


def _fugitive_vector(result: calc.CategoryResult, ref: EmissionFactorReference, gwp_set: str
                     ) -> tuple[dict[str, dict[str, float]], list[_Line]]:
    """Each refrigerant line split into gas groups: mass by weight %, CO2e by each component's
    share of the blend's CO2e; what no group takes stays in "other" so the total is exact."""

    vector = _zeros()
    lines: list[_Line] = []
    for line in result.lines:
        mass = float(line.mass_t.get(line.key, 0.0))
        co2e = float(line.steps[-1].result) if line.steps else 0.0
        groups = ref.gas_groups(line.key)
        split: dict[str, dict[str, float]] = {}
        flags: list[str] = []
        if groups is None:
            split["other"] = {"mass_t": mass, "co2e_t": co2e}
            found = find_refrigerant(line.key)
            flags.append("non_kyoto_gas_in_total" if found is not None and found.family == "other"
                         else "gas_split_unknown")
        else:
            if not groups:
                flags.append("blend_without_kyoto_gases")
            hub = _hub_gwp_ar5(ref, line.key)
            used = result.gwp.get(line.key, {}).get("value")
            entered = hub is None or used is None or abs(float(used) - hub) > 1e-9  # not the Hub AR5 GWP
            grouped = co2e
            if entered and hub is not None and groups and sum(g["mass_fraction"] for g in groups.values()) < 1 - 1e-9:
                # An entered GWP (safety data sheet, AR6) for a blend with HCFCs or hydrocarbons may
                # count those too: only the Kyoto components' Table 12 share goes to the gas groups.
                kyoto = mass * hub
                grouped = kyoto if abs(kyoto) < abs(co2e) else co2e
                flags.append("gas_split_uses_ar5_ratios")
            elif entered and len(groups) > 1:
                flags.append("gas_split_uses_ar5_ratios")
            for group, share in groups.items():
                split[group] = {"mass_t": mass * share["mass_fraction"], "co2e_t": grouped * share["co2e_fraction"]}
            residual = co2e - sum(v["co2e_t"] for v in split.values())
            if abs(residual) > EPSILON:
                split["other"] = {"mass_t": 0.0, "co2e_t": residual}
        for group, amounts in split.items():
            vector[group]["mass_t"] += amounts["mass_t"]
            vector[group]["co2e_t"] += amounts["co2e_t"]
        lines.append(_Line(line.key, split, flags))
    return vector, lines


def _source_states(categories: Mapping[str, calc.CategoryResult | None], open_items: Mapping[str, int],
                   absent: Mapping[str, str], ref: EmissionFactorReference, gwp_set: str) -> dict[str, _SourceState]:
    states: dict[str, _SourceState] = {}
    for source in SOURCES:
        results = {basis: categories.get(key) for basis, key in source.backend.items()}
        primary = results.get("location")
        items = int(open_items.get(source.key, 0))
        state = _SourceState(source, "", items, absent.get(source.key))
        if primary is not None:
            if source.key == "fugitive_refrigerants":
                vector, lines = _fugitive_vector(primary, ref, gwp_set)
                state.lines = lines
                state.vectors = {"location": vector, "market": vector}
                if any("gas_split_unknown" in line.flags for line in lines):
                    state.gaps.append({"gap": "gas_split_unknown", "gases": ["HFCs", "PFCs"], "affects_total": False})
                state.flags.extend(sorted({f for line in lines for f in line.flags}))
                state.negative = {g for line in lines for g, v in line.groups.items()
                                  if v["mass_t"] < 0 or v["co2e_t"] < 0}
            else:
                location = _combustion_vector(primary)
                market = results.get("market")
                state.vectors = {"location": location,
                                 "market": _combustion_vector(market) if market is not None else location}
                state.negative = {gas for result in results.values() if result is not None
                                  for line in result.lines for gas, mass in line.mass_t.items() if mass < 0}
                if any(line.biogenic_co2_t < 0 for line in primary.lines):
                    state.negative.add("biogenic")
            if source.key == "mobile_combustion" and any(
                    "ch4_n2o_need_vehicle_groups" in line.flags for line in primary.lines):
                state.gaps.append({"gap": "vehicle_groups_missing", "gases": ["CH4", "N2O"], "affects_total": True})
            state.biogenic = float(primary.biogenic_co2_t)
            state.status = "partial" if items or any(g["affects_total"] for g in state.gaps) else "calculated"
            if state.absent_reason is not None:
                state.source_flags.append("marked_absent_but_evidence_found")
        elif source.built and items:
            state.status = "awaiting_inputs"
            if state.absent_reason is not None:
                state.source_flags.append("marked_absent_but_evidence_found")
        elif state.absent_reason is not None:
            state.status = "confirmed_absent"
            state.vectors = {"location": _zeros(), "market": _zeros()}
            state.biogenic = 0.0
        else:
            state.status = "no_evidence" if source.built else "not_built"
        state.flags.extend(state.source_flags)
        states[source.key] = state
    return states


@dataclass
class _NodeValue:
    co2e_t: float | None
    mass_t: float | None
    status: str  # "complete" | "partial" | "not_available"
    backed: bool
    terms: list[dict[str, Any]]
    missing: list[dict[str, str]]
    lower_bound: bool
    flags: list[str]
    gases: dict[str, dict[str, float]] | None = None


def _missing_for(state: _SourceState, node: Node) -> list[dict[str, str]]:
    out = []
    if state.status in ("not_built", "no_evidence", "awaiting_inputs"):
        out.append({"source": state.source.key, "reason": state.status})
    elif state.status == "partial" and state.open_items:
        out.append({"source": state.source.key, "reason": "inputs_open"})
    for gap in state.gaps if state.backed else []:
        if _gap_touches(gap, node):
            out.append({"source": state.source.key, "reason": gap["gap"]})
    return out


def _complete_for(state: _SourceState, node: Node) -> bool:
    """Whether a source's contribution to ``node`` is final: absent, or calculated with no open
    items and no gap touching this node (no vehicle groups leaves CH4 and N2O open, not CO2)."""

    if state.status == "confirmed_absent":
        return True
    if not state.backed or state.open_items:
        return False
    return not any(_gap_touches(g, node) for g in state.gaps)


def _flags_for(state: _SourceState, node: Node) -> list[str]:
    """A gas node takes the flags of the lines that add to its gas, not every line's."""

    if node.kind != "gas" or not state.lines:
        return state.flags
    gas = node.gas or ""
    lines = [line for line in state.lines
             if gas in line.groups and (abs(line.groups[gas]["co2e_t"]) > EPSILON
                                        or abs(line.groups[gas]["mass_t"]) > EPSILON)]
    return [*state.source_flags, *sorted({f for line in lines for f in line.flags})]


def _no_negative(state: _SourceState, node: Node) -> bool:
    if node.kind == "gas":
        return node.gas not in state.negative
    if node.kind == "memo":
        return "biogenic" not in state.negative
    return not state.negative - {"biogenic"}


def _gap_touches(gap: dict[str, Any], node: Node) -> bool:
    if node.kind == "gas":
        return node.gas in gap["gases"]
    if node.kind == "memo":
        return False
    return bool(gap["affects_total"])


def _dedupe(items: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    out = []
    for item in items:
        key = (item["source"], item["reason"])
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


class _Evaluator:
    def __init__(self, states: dict[str, _SourceState]) -> None:
        self.states = states
        self.values: dict[str, _NodeValue] = {}

    def node(self, key: str) -> _NodeValue:
        if key not in self.values:
            self.values[key] = self._evaluate(NODE_BY_KEY[key])
        return self.values[key]

    def _source_term(self, node: Node, state: _SourceState) -> tuple[dict[str, Any], float | None, float | None]:
        """(term, co2e, mass) a source contributes to ``node``; None when it is not available."""

        co2e: float | None = None
        mass: float | None = None
        if state.contributes:
            vector = state.vectors.get(node.basis) or _zeros()
            if node.kind == "gas":
                assert node.gas is not None
                co2e, mass = vector[node.gas]["co2e_t"], vector[node.gas]["mass_t"]
            elif node.kind == "memo":
                co2e = state.biogenic if state.biogenic is not None else 0.0
            else:
                co2e = sum(v["co2e_t"] for v in vector.values())
        term: dict[str, Any] = {"ref": f"category:{state.source.key}", "co2e_t": co2e, "status": state.status}
        if node.kind == "gas":
            term["mass_t"] = mass
        return term, co2e, mass

    def _gas_contributors(self, node: Node) -> list[_SourceState]:
        """Sources that can emit the node's gas, plus any that actually report some of it."""

        assert node.gas is not None
        pool = SCOPE1_SOURCES if node.scope == "scope1" else SCOPE2_SOURCES
        out = []
        for key in pool:
            state = self.states[key]
            vector = state.vectors.get(node.basis)
            reports = vector is not None and (abs(vector[node.gas]["co2e_t"]) > EPSILON
                                              or abs(vector[node.gas]["mass_t"]) > EPSILON)
            if node.gas in state.source.gases or reports:
                out.append(state)
        return out

    def _evaluate(self, node: Node) -> _NodeValue:
        if node.structural_zero:
            parent = self.node("scope2_location_total")
            available = parent.co2e_t is not None
            return _NodeValue(0.0 if available else None, 0.0 if available else None,
                              "complete" if available else "not_available", parent.backed, [],
                              [] if available else list(parent.missing), True, [])
        terms: list[dict[str, Any]] = []
        missing: list[dict[str, str]] = []
        flags: list[str] = []
        co2e_values: list[float] = []
        mass_values: list[float] = []
        backed = False
        complete = True
        lower_bound = True
        if node.kind == "total":
            for ref in node.terms:
                child = self.node(ref.split(":", 1)[1])
                terms.append({"ref": ref, "co2e_t": child.co2e_t, "status": child.status})
                missing.extend(child.missing)
                flags.extend(f for f in child.flags if f not in flags)
                lower_bound = lower_bound and child.lower_bound
                backed = backed or child.backed
                complete = complete and child.status == "complete"
                if child.co2e_t is not None:
                    co2e_values.append(child.co2e_t)
        else:
            states = (self._gas_contributors(node) if node.kind == "gas"
                      else [self.states[ref.split(":", 1)[1]] for ref in node.terms])
            for state in states:
                term, co2e, mass = self._source_term(node, state)
                terms.append(term)
                missing.extend(_missing_for(state, node))
                if state.contributes:
                    flags.extend(f for f in _flags_for(state, node) if f not in flags)
                lower_bound = lower_bound and _no_negative(state, node)
                backed = backed or state.backed
                complete = complete and _complete_for(state, node)
                if co2e is not None:
                    co2e_values.append(co2e)
                if mass is not None:
                    mass_values.append(mass)
        if backed:
            co2e_t: float | None = sum(co2e_values)
            mass_t: float | None = sum(mass_values) if node.kind == "gas" else None
            status = "complete" if complete else "partial"
        elif terms and all(t["status"] in ("confirmed_absent", "complete") for t in terms) and complete:
            co2e_t, mass_t, status = 0.0, (0.0 if node.kind == "gas" else None), "complete"
        else:
            co2e_t, mass_t, status = None, None, "not_available"
        gases = None
        if node.kind == "category" and backed:
            gases = {g: {"mass_t": 0.0, "co2e_t": 0.0} for g in GROUPS}
            for ref in node.terms:
                state = self.states[ref.split(":", 1)[1]]
                vector = state.vectors.get(node.basis) if state.contributes else None
                for g, amounts in (vector or {}).items():
                    gases[g]["mass_t"] += amounts["mass_t"]
                    gases[g]["co2e_t"] += amounts["co2e_t"]
            gases = {g: v for g, v in gases.items() if abs(v["co2e_t"]) > EPSILON or abs(v["mass_t"]) > EPSILON}
        return _NodeValue(co2e_t, mass_t, status, backed, terms, _dedupe(missing), lower_bound, flags, gases)


# =========================================================================================
# Final outputs
# =========================================================================================
def _output(output: FinalOutput, value: _NodeValue, reported: float | None, unit_choice: str | None,
            out_of_scope: bool, tolerance: float) -> dict[str, Any]:
    candidates: dict[str, float | None] = {"mass_t": value.mass_t, "co2e_t": value.co2e_t} if output.gas_row else {}
    both_zero = bool(candidates) and candidates["mass_t"] == 0 and candidates["co2e_t"] == 0
    if output.gas_row:
        measure = {"t": "mass_t", "t CO2e": "co2e_t"}.get(unit_choice or "", output.default_measure)
        if measure is None and both_zero:
            measure = "mass_t"
    else:
        measure = output.default_measure
    recalculated = (value.co2e_t if measure == "co2e_t" else value.mass_t) if measure else None
    item: dict[str, Any] = {
        "key": output.key, "label": output.label, "workbook_row": output.workbook_row,
        "requirement": output.requirement, "unit": {"co2e_t": "t CO2e", "mass_t": "t"}.get(measure or ""),
        "node": output.node, "measure": measure, "reported": reported, "reported_unit": unit_choice,
        "recalculated": recalculated, "difference": None, "difference_pct": None, "tolerance_pct": tolerance,
        "within_threshold": None, "status": "", "reason": None, "completeness": value.status,
        "missing": value.missing, "flags": list(value.flags),
    }
    if candidates:
        item["candidates"] = candidates
    if reported is not None and recalculated is not None:
        compared = calc.compare(output.label, reported, recalculated, tolerance)
        item["difference"], item["difference_pct"] = compared["difference"], compared["difference_pct"]
        pct = compared["difference_pct"]
        item["within_threshold"] = (abs(pct) <= tolerance) if pct is not None else False
    # Status: the first rule that applies.
    if out_of_scope:
        item["status"], item["reason"] = "not_in_scope", "set_out_of_scope"
    elif value.status == "not_available":
        if value.missing and all(m["reason"] == "not_built" for m in value.missing):
            item["status"], item["reason"] = "not_recalculated", "not_built"
        else:
            reasons = {m["reason"] for m in value.missing}
            item["status"] = "no_evidence"
            item["reason"] = "awaiting_inputs" if "awaiting_inputs" in reasons else "no_evidence"
    elif reported is None:
        item["status"] = "not_reported"
    elif measure is None:
        item["status"], item["reason"] = "needs_unit", "unit_unconfirmed"
        hints = [unit for unit, key in (("t", "mass_t"), ("t CO2e", "co2e_t"))
                 if (candidate := candidates.get(key)) is not None and _within(reported, candidate, tolerance)]
        item["unit_hint"] = hints[0] if len(hints) == 1 else None
    else:
        assert recalculated is not None
        exceeds = item["within_threshold"] is False
        if value.status == "complete":
            item["status"] = "exceeds_tolerance" if exceeds else "within_tolerance"
            if reported == 0 and recalculated != 0:
                item["reason"] = "reported_zero"
        elif value.lower_bound and recalculated > reported * (1 + tolerance / 100):
            item["status"] = "exceeds_tolerance"
            item["reason"] = "reported_zero" if reported == 0 else "lower_bound"
        else:
            item["status"], item["reason"] = "incomplete", "partial_total"
        if candidates and unit_choice:
            other = "co2e_t" if measure == "mass_t" else "mass_t"
            other_value = candidates[other]
            if exceeds and other_value is not None and _within(reported, other_value, tolerance):
                item["flags"].append("reported_matches_other_unit")
    return item


def _within(reported: float, recalculated: float, tolerance: float) -> bool:
    if reported == 0:
        return recalculated == 0
    return abs((recalculated - reported) / reported * 100) <= tolerance


# =========================================================================================
# Public
# =========================================================================================
def build_rollup(categories: Mapping[str, calc.CategoryResult | None], *, open_items: Mapping[str, int],
                 absent: Mapping[str, str], reported: Mapping[str, float], reported_units: Mapping[str, str],
                 out_of_scope: frozenset[str] | set[str], tolerance: float, gwp_set: str,
                 ref: EmissionFactorReference) -> dict[str, Any]:
    """The roll-up for one recalculation (see the module docstring)."""

    states = _source_states(categories, open_items, absent, ref, gwp_set)
    evaluator = _Evaluator(states)
    nodes: dict[str, Any] = {}
    for node in NODES:
        value = evaluator.node(node.key)
        entry: dict[str, Any] = {
            "step": STEP_OF[node.key], "label": node.label, "kind": node.kind, "scope": node.scope,
            "unit": node.unit, "formula": node.formula, "co2e_t": value.co2e_t, "status": value.status,
            "terms": value.terms, "missing": value.missing, "lower_bound": value.lower_bound, "flags": value.flags,
        }
        if node.kind == "gas":
            entry["gas"] = node.gas
            entry["mass_t"] = value.mass_t
        if node.structural_zero:
            entry["basis"] = "structural_zero"
        if value.gases is not None:
            entry["gases"] = value.gases
        nodes[node.key] = entry

    sources: dict[str, Any] = {}
    for key, state in states.items():
        source = state.source
        entry = {
            "label": source.label, "scope": source.scope, "workbook_row": source.workbook_row, "built": source.built,
            "backend_categories": dict(source.backend), "gases": list(source.gases), "status": state.status,
            "open_items": state.open_items, "gaps": state.gaps, "absent_reason": state.absent_reason,
            "flags": state.flags,
        }
        if state.lines:
            entry["gas_split"] = {line.key: {"groups": line.groups, "flags": line.flags} for line in state.lines}
        sources[key] = entry

    final_outputs = [
        _output(o, evaluator.node(o.node), reported.get(o.key), reported_units.get(o.key), o.key in out_of_scope,
                tolerance)
        for o in FINAL_OUTPUTS
    ]
    return {
        "version": ROLLUP_VERSION, "gwp_set": gwp_set, "tolerance_pct": tolerance, "gas_groups": list(GAS_GROUPS),
        "steps": [*LAYOUT, {"key": "final_outputs", "label": "Final outputs · reported vs recalculated", "order": 4,
                            "output_keys": [o.key for o in FINAL_OUTPUTS]}],
        "categories": sources, "nodes": nodes, "final_outputs": final_outputs, "checks": _checks(evaluator),
    }


def _checks(evaluator: _Evaluator) -> list[dict[str, Any]]:
    """Each total against the sum of its gases, and each inventory total against its scopes."""

    def value(key: str) -> float | None:
        return evaluator.node(key).co2e_t

    def gas_sum(keys: list[str]) -> float:
        return sum(v for v in (value(k) for k in keys) if v is not None)

    rows = [
        ("scope1_total_equals_gas_sum", "scope1_total",
         [n.key for n in NODES if n.scope == "scope1" and n.kind == "gas"]),
        ("scope2_location_total_equals_gas_sum", "scope2_location_total",
         [n.key for n in NODES if n.scope == "scope2_location" and n.kind == "gas"]),
        ("scope2_market_total_equals_gas_sum", "scope2_market_total",
         [n.key for n in NODES if n.scope == "scope2_market" and n.kind == "gas"]),
        ("inventory_location_equals_scope_sum", "inventory_location_total", ["scope1_total", "scope2_location_total"]),
        ("inventory_market_equals_scope_sum", "inventory_market_total", ["scope1_total", "scope2_market_total"]),
    ]
    out = []
    for key, total_key, parts in rows:
        total = value(total_key)
        if total is None:
            continue
        summed = gas_sum(parts)
        out.append({"key": key, "total": total, "sum": summed,
                    "ok": abs(total - summed) <= 1e-9 * max(1.0, abs(total))})
    return out


def rollup_layout() -> dict[str, Any]:
    """The static roll-up (no values): what Claire's screen draws before any data exists."""

    return {
        "version": ROLLUP_VERSION,
        "steps": [*LAYOUT, {"key": "final_outputs", "label": "Final outputs · reported vs recalculated", "order": 4,
                            "output_keys": [o.key for o in FINAL_OUTPUTS]}],
        "sources": [{"key": s.key, "label": s.label, "scope": s.scope, "workbook_row": s.workbook_row,
                     "built": s.built, "gases": list(s.gases)} for s in SOURCES],
        "nodes": [{"key": n.key, "step": STEP_OF[n.key], "label": n.label, "unit": n.unit, "kind": n.kind,
                   "scope": n.scope, "gas": n.gas, "formula": n.formula, "terms": list(n.terms),
                   "structural_zero": n.structural_zero} for n in NODES],
        "final_outputs": [{"key": o.key, "label": o.label, "workbook_row": o.workbook_row,
                           "requirement": o.requirement, "node": o.node, "default_measure": o.default_measure,
                           "unit": {"co2e_t": "t CO2e", "mass_t": "t"}.get(o.default_measure or ""),
                           "unit_settable": o.gas_row} for o in FINAL_OUTPUTS],
    }
