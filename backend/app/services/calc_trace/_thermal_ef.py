"""The four emission factor options of purchased steam (C9) and heat (C10), boards 07 and 09.

    Supplier-specific      the factors the supplier states for the energy it sells (kg CO2, g CH4, g N2O per MMBtu)
    CHP allocated          the factors a combined heat and power plant allocates to its steam or heat, as stated by
                           the supplier (the allocation method is the supplier's: Sustentra does not work it yet)
    Fuel and efficiency    the boiler fuel's factors (EPA Hub Table 1) ÷ the boiler's thermal efficiency
    EPA default            EPA Hub Table 7, steam and heat: natural gas at 80% efficiency (66.33 kg, 1.25 g, 0.125 g)

Every option is per gas and per MMBtu delivered. An option is *detected* when the values it needs are in hand: the
supplier's or CHP factors entered for the line (with the document they come from), or the boiler's efficiency (the fuel
defaults to natural gas, shown as an assumption until a reviewer confirms or changes it). EPA Table 7 needs nothing.
With several detected, the line uses the first of: supplier-specific, CHP allocated, fuel and efficiency, EPA Table 7
(rulings for C9). A reviewer can choose another; an option whose values are missing then blocks the line until they are
entered ("Awaiting review").

EPA prints Table 7 rounded: natural gas at 80% is 53.06 ÷ 0.80 = 66.325 kg CO2 per MMBtu, which Table 7 prints as
66.33 (CH4 1.0 ÷ 0.80 = 1.25 g and N2O 0.10 ÷ 0.80 = 0.125 g are exact). So "fuel and efficiency" on natural gas at 80%
gives 66.325, not Table 7's 66.33; the panel says why (``TABLE7_NOTE``).

``factors`` resolves the option a line uses into per-gas factors; ``blocks`` lays Step 3 out (one block per option and
gas, each tagged "Detected from the evidence" or "Not used for this line"). The panel module (``steam``, later ``heat``)
owns the rest of its working.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from backend.app.reference.emission_factor_loader import EmissionFactorReference
from backend.app.services.calc_trace import ops
from backend.app.services.calc_trace._line import GAS_LABEL, GASES, _annotate, reference_source
from backend.app.services.calc_trace.model import (
    Choice, ChoiceOption, Column, Operand, Operation, Side, SourceRef, Term, TraceBlock, TraceInput,
)

CHOICE_ID = "ef_option"
SUPPLIER, CHP, FUEL, TABLE7 = "supplier_specific", "chp_allocated", "fuel_and_efficiency", "epa_table7"
OPTIONS = (SUPPLIER, CHP, FUEL, TABLE7)  # the priority order when several are detected (rulings for C9)
LABEL = {SUPPLIER: "Supplier-specific", CHP: "CHP allocated", FUEL: "Calculated from fuel and efficiency",
         TABLE7: "EPA default"}
PREFIX = {SUPPLIER: "supplier_ef.", CHP: "chp_ef.", FUEL: "fuel_ef."}
EFFICIENCY = "efficiency"
TABLE7_ID = "table7."  # the reference factors: never decided for a line (choose another option instead)
UNIT = {"CO2": "kg/MMBtu", "CH4": "g/MMBtu", "N2O": "g/MMBtu"}
TO_T = {"kg/MMBtu": 0.001, "g/MMBtu": 0.000001}  # the factor's mass to metric tons
INPUTS = (*(f"{PREFIX[o]}{gas}" for o in (SUPPLIER, CHP, FUEL) for gas in GASES), EFFICIENCY)
DEFAULT_FUEL = "Natural Gas"
CHP_FLAG = "chp_allocation_as_stated_by_supplier"
TABLE7_NOTE = ("EPA Table 7 is natural gas at 80% efficiency, rounded: 53.06 ÷ 0.80 = 66.325 kg CO₂ per MMBtu, "
               "printed as 66.33.")
EFFICIENCY_RANGE = (0.0, 100.0)  # % (above 0, at most 100)


@dataclass(frozen=True)
class Factor:
    value: float | None  # None: awaiting review
    unit: str
    source: SourceRef | None
    input_id: str | None  # the input the value is read from (None: worked, e.g. fuel ÷ efficiency)


def _number(values: Mapping[str, float], key: str) -> float | None:
    found = values.get(key)
    return float(found) if found is not None else None


def detected(values: Mapping[str, float]) -> list[str]:
    """The options whose values are in hand (``values``: the line's decided inputs, by id), in priority order."""

    out = [o for o in (SUPPLIER, CHP) if all(f"{PREFIX[o]}{gas}" in values for gas in GASES)]
    if EFFICIENCY in values:
        out.append(FUEL)
    return [*out, TABLE7]


def default_option(values: Mapping[str, float]) -> str:
    return detected(values)[0]


def fuel_factors(ref: EmissionFactorReference) -> dict[str, tuple[float, SourceRef | None]]:
    """The default boiler fuel's factors per MMBtu of fuel (EPA Hub Table 1, natural gas)."""

    row = ref.stationary_fuel(DEFAULT_FUEL)
    per = row["per_energy"]
    cite = reference_source(ref.cite(row))
    return {"CO2": (float(per["co2_kg_per_mmbtu"]), cite), "CH4": (float(per["ch4_g_per_mmbtu"]), cite),
            "N2O": (float(per["n2o_g_per_mmbtu"]), cite)}


def table7(ref: EmissionFactorReference) -> dict[str, tuple[float, SourceRef | None]]:
    found = ref.steam_heat()
    return {gas: (float(found[gas].value), reference_source(found[gas].source)) for gas in GASES}


def factors(option: str, values: Mapping[str, float], sides: Mapping[str, Side], ref: EmissionFactorReference
            ) -> dict[str, Factor]:
    """The per-gas factors ``option`` gives with the line's values (``sides``: the decided sides, for their source).
    A value the option needs and does not have is ``None`` (awaiting review)."""

    out: dict[str, Factor] = {}
    if option == TABLE7:
        for gas, (value, source) in table7(ref).items():
            out[gas] = Factor(value, UNIT[gas], source, f"{TABLE7_ID}{gas}")
        return out
    if option in (SUPPLIER, CHP):
        for gas in GASES:
            input_id = f"{PREFIX[option]}{gas}"
            side = sides.get(input_id)
            out[gas] = Factor(_number(values, input_id), UNIT[gas], side.source if side else None, input_id)
        return out
    fuel = fuel_factors(ref)
    efficiency = _number(values, EFFICIENCY)
    for gas in GASES:
        input_id = f"{PREFIX[FUEL]}{gas}"
        own = _number(values, input_id)
        value = own if own is not None else fuel[gas][0]
        out[gas] = Factor(value / (efficiency / 100.0) if efficiency else None, UNIT[gas],
                          SourceRef("derived", from_=[input_id, EFFICIENCY]), None)
    return out


def inputs(chosen: str, values: Mapping[str, float], sides: Mapping[str, Side], ref: EmissionFactorReference,
           company: Mapping[str, float]) -> dict[str, TraceInput]:
    """Every value an option reads, so each can be entered for the line (the decision POST needs it in the trace)."""

    out: dict[str, TraceInput] = {}
    fuel = fuel_factors(ref)
    for gas, (value, source) in table7(ref).items():
        out[f"{TABLE7_ID}{gas}"] = TraceInput(f"{TABLE7_ID}{gas}", f"EPA Table 7 {GAS_LABEL[gas]} factor", "reference",
                                      symbol="EF", required_for=[TABLE7],
                                      recomputed=Side(value, UNIT[gas], "reference", source))
    for option in (SUPPLIER, CHP, FUEL):
        for gas in GASES:
            input_id = f"{PREFIX[option]}{gas}"
            given = company.get(input_id)
            if option == FUEL:
                own = sides.get(input_id)
                side = own if own is not None else Side(fuel[gas][0], UNIT[gas], "reference", fuel[gas][1])
                label = f"Boiler fuel {GAS_LABEL[gas]} factor"
                kind = "reference"
            else:
                side = sides.get(input_id) or Side(None, UNIT[gas], "awaiting_review")
                label = f"{LABEL[option]} {GAS_LABEL[gas]} factor"
                kind = "reviewer_entered"
            item = TraceInput(input_id, label, kind, symbol="EF", required_for=[option], recomputed=side,
                              company=Side(given, UNIT[gas], "accepted") if given is not None else None)
            if option == FUEL and chosen == FUEL and input_id not in values:
                item.assumption = (f"Default: natural gas, {_g(fuel[gas][0])} {UNIT[gas]} (EPA Hub Table 1) · not "
                                   "confirmed")
            if given is not None and isinstance(side.value, (int, float)):
                item.difference = float(side.value) - given
                item.differs = ops.differs(item.difference, float(side.value))
            out[input_id] = item
    given = company.get(EFFICIENCY)
    out[EFFICIENCY] = TraceInput(EFFICIENCY, "Boiler thermal efficiency", "reviewer_entered", symbol="η",
                                 required_for=[FUEL],
                                 recomputed=sides.get(EFFICIENCY) or Side(None, "%", "awaiting_review"),
                                 company=Side(given, "%", "accepted") if given is not None else None)
    return out


def choice(chosen: str, chosen_by: str, values: Mapping[str, float], company_option: str | None) -> Choice:
    """Every option can be chosen (each has a route); ``detection`` says which the evidence gives."""

    found = set(detected(values))
    options = []
    for option in OPTIONS:
        needs = [f"{PREFIX[option]}{gas}" for gas in GASES] if option in (SUPPLIER, CHP) else (
            [EFFICIENCY] if option == FUEL else [])
        options.append(ChoiceOption(
            option, LABEL[option], equation="Emissions = MMBtu × EF", required_inputs=needs,
            detection=None if option == TABLE7 else (
                "detected_from_evidence" if option in found else "not_used_for_this_line")))
    return Choice(CHOICE_ID, "Emission factor", options, chosen=chosen, chosen_by=chosen_by, company=company_option)


def company_option(company: Mapping[str, float]) -> str | None:
    """The option the company used, from the factors a reviewer entered for its side; None when none is given."""

    found = detected(company)
    return found[0] if found[0] != TABLE7 else None


def _g(value: float) -> str:
    return format(value, ",.6g")


def blocks(chosen: str, values: Mapping[str, float], sides: Mapping[str, Side], ref: EmissionFactorReference,
           company: Mapping[str, float], their_option: str | None) -> list[TraceBlock]:
    """Step 3: each option's factors per gas. The option used is tagged "Detected from the evidence" (EPA Table 7,
    which needs nothing from the evidence, carries no tag when used); every other "Not used for this line"."""

    out: list[TraceBlock] = []
    fuel = fuel_factors(ref)
    for option in OPTIONS:
        mine = factors(option, values, sides, ref)
        theirs = factors(option, company, {}, ref) if their_option == option else None
        tag = ("not_used_for_this_line" if option != chosen else
               None if option == TABLE7 else "detected_from_evidence")
        for gas in GASES:
            unit = UNIT[gas]
            if option == FUEL:
                fuel_id = f"{PREFIX[FUEL]}{gas}"
                efficiency = _number(values, EFFICIENCY)
                own_fuel = _number(values, fuel_id)
                fuel_value = own_fuel if own_fuel is not None else fuel[gas][0]

                def worked(fuel_v: float, eff: float | None) -> Operation:
                    terms = [Term(None, Operand("fuel_ef", fuel_v, unit, input_id=fuel_id)),
                             Term("÷", Operand("share", eff / 100.0 if eff else None, None, input_id=EFFICIENCY))]
                    if eff is None:
                        return Operation(terms, Operand("ef", None, unit))
                    return ops.make_operation(terms, "ef", unit)

                rec = worked(fuel_value, efficiency)
                co = None
                if theirs is not None:
                    their_fuel = company.get(fuel_id, fuel[gas][0])
                    co = worked(their_fuel, company.get(EFFICIENCY))
                    _annotate(rec, co)
                columns = [Column("fuel_ef", f"Boiler fuel {GAS_LABEL[gas]} factor", unit),
                           Column("share", "Thermal efficiency"), Column("ef", "Emission factor", unit, True, {"sig": 6})]
            else:
                factor = mine[gas]
                rec = Operation([Term(None, Operand("ef", factor.value, unit, input_id=factor.input_id))],
                                Operand("ef", factor.value, unit, input_id=factor.input_id))
                co = None
                if theirs is not None and theirs[gas].value is not None:
                    co = Operation([Term(None, Operand("ef", theirs[gas].value, unit, input_id=factor.input_id))],
                                   Operand("ef", theirs[gas].value, unit, input_id=factor.input_id))
                    _annotate(rec, co)
                what = {SUPPLIER: "Factor stated by the supplier", CHP: "CHP allocation stated by the supplier",
                        TABLE7: "EPA Hub Table 7, steam and heat"}[option]
                columns = [Column("ef", what, unit, True, {"sig": 6})]
            out.append(TraceBlock(f"ef.{option}.{gas}", f"{LABEL[option]} · {GAS_LABEL[gas]}", columns,
                                  company=co, recomputed=rec, tag=tag))
    return out
