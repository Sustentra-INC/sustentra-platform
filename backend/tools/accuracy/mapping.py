"""The explicit map from answer-key field names to extractor fields.

One table, read top to bottom: the first rule whose pattern matches the key's *base name* (the label
with the record selector and the bracketed qualifier removed, see ``keys.parse_label``) decides the
field family. Each family says

* ``kind``: how values are compared (``number`` with unit conversion, ``date``, ``id``, ``name``,
  ``text``, ``address``, ``year``);
* ``fields``: the extractor field(s) that carry it, in priority order; the first one in the
  document's extraction targets is used. No such field -> the cell is ``not_targeted`` (the
  extractor does not read it yet), never ``wrong``;
* ``aggregate``: for totals, how the document's records are combined (``sum``);
* ``scope``: ``document`` when one value covers the whole document, ``record`` when the key cell
  names a record (a bill in a bundle, a log row, a vehicle).

Families that are not extraction fields at all (notes, page counts, platform actions) are ``meta``
and are ``unscored``: the key says something about the document, not a value to read.

Anything that matches no rule is ``unmapped`` (counted and listed by label, never wrong). To teach
the harness a new key field, add a rule here and a test in ``test_accuracy_mapping.py``.

Known scoring artefact handled here: a fleet-card statement has per-transaction dates, no service
period. The MOBFUEL type therefore has no ``service_period_start`` / ``service_period_end`` target,
so the key's statement period is ``not_targeted`` and a transaction date is never compared to it
(the 13 Nov scoring did, and made 22 correct values look wrong).
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class FamilySpec:
    id: str
    kind: str
    fields: tuple[str, ...] = ()
    aggregate: str | None = None  # "sum": the key value is a total over the selected records
    filter_fuel: str | None = None  # restrict a total to records of this fuel
    description: str = ""


FAMILIES: dict[str, FamilySpec] = {f.id: f for f in (
    FamilySpec("supplier", "name", ("supplier_name", "merchant_or_supplier", "service_provider"), description="Supplier / utility / service provider"),
    FamilySpec("account", "id", ("account_number",), description="Account number"),
    FamilySpec("meter", "id", ("meter_number",), description="Meter number"),
    FamilySpec("statement_date", "date", ("statement_date",), description="Statement / bill date"),
    FamilySpec("period_start", "date", ("service_period_start",), description="Service period start"),
    FamilySpec("period_end", "date", ("service_period_end",), description="Service period end"),
    FamilySpec("activity_quantity", "number", ("activity_quantity", "refrigerant_added"), description="Activity quantity (energy, fuel, refrigerant added)"),
    FamilySpec("activity_total", "number", ("activity_quantity", "refrigerant_added"), aggregate="sum", description="Activity quantity total over records"),
    FamilySpec("refrigerant_recovered", "number", ("refrigerant_recovered",), description="Refrigerant recovered"),
    FamilySpec("refrigerant_recovered_total", "number", ("refrigerant_recovered",), aggregate="sum", description="Refrigerant recovered, total over records"),
    FamilySpec("equipment_capacity", "number", ("equipment_capacity",), description="Equipment full charge"),
    FamilySpec("distance", "number", ("distance",), description="Distance travelled"),
    FamilySpec("distance_total", "number", ("distance",), aggregate="sum", description="Distance total over records"),
    FamilySpec("fuel_type", "text", ("fuel_type",), description="Fuel type"),
    FamilySpec("vehicle_type", "text", ("vehicle_type",), description="Vehicle type"),
    FamilySpec("model_year", "year", ("model_year",), description="Vehicle model year"),
    FamilySpec("refrigerant_type", "text", ("refrigerant_type",), description="Refrigerant type"),
    FamilySpec("technician", "text", ("technician",), description="Technician"),
    FamilySpec("equipment_id", "id", ("equipment_id", "vehicle_or_equipment_id"), description="Equipment id"),
    FamilySpec("heat_content", "number", ("heat_content",), description="Heat content / conversion factor"),
    FamilySpec("service_address", "address", ("service_address",), description="Service address"),
    # Key fields the extractor has no field for yet (`not_targeted`): listed so they are counted by name.
    FamilySpec("meter_read_start", "number", (), description="Meter start read"),
    FamilySpec("meter_read_end", "number", (), description="Meter end read"),
    FamilySpec("billed_demand", "number", (), description="Billed / peak demand"),
    FamilySpec("period_usage", "number", (), description="On/off/part-peak usage"),
    FamilySpec("total_amount", "number", (), description="Total amount due / charges"),
    FamilySpec("converted_quantity", "number", (), description="Converted quantity (MMBtu, kWh from MWh, ...)"),
    FamilySpec("run_hours", "number", (), description="Generator run hours"),
    FamilySpec("conversion_factor", "number", (), description="Therm factor, CCF usage and similar bill arithmetic"),
    FamilySpec("document_reference", "id", (), description="Invoice, ticket, tank and delivery references"),
)}

# Families that are about the document, not a value to read: unscored.
META = "meta"
REPORTING = "reporting"  # emission factors, gas splits, scope totals: the recalculation, not a reading
UNMAPPED = "unmapped"

# (pattern on the base name, family id), first match wins. Base names are lower-case with single spaces.
_Q = r"(?:activity quantity|activity_quantity)"
RULES: list[tuple[re.Pattern[str], str]] = [(re.compile(p), f) for p, f in (
    # Not extraction fields: notes and facts about the file or the platform's handling.
    (r"^(note|platform action|page count|total page count|statement count|row count|data row count|document type|"
     r"document role|supersedes|unit note|billing cycle note|read type|email date|email date header|days in reporting year|"
     r"approximate .*|reference .*|sum of .*|cylinder count|cylinders|"
     r"transaction count|delivery \d date|delivery \d quantity|tank serial|contract number|effective date|"
     r"gallons \d+ rows .*|file total gallons added|total amount all rows|annual total amount|prorated .*|.*prorated.*)\b.*$", META),
    (r"^(emission factor|co2 location|ch4 location|n2o location|hfc location|total location based|total market based|"
     r"activity|activity total|supplier ef .*|chiller intensity|scope \d.*|reported .*|.* scope\d reported)$", REPORTING),
    (r"^(supplier|supplier from meter face)$", "supplier"),
    (r"^(account number|account)$", "account"),
    (r"^meter number$", "meter"),
    (r"^statement date$", "statement_date"),
    (r"^service period start$", "period_start"),
    (r"^service period end$", "period_end"),
    (r"^(meter start read|meter read start|meter reading previous|meter start)$", "meter_read_start"),
    (r"^(meter end read|meter read end|meter reading current|meter end|meter reading)$", "meter_read_end"),
    (r"^(billed demand|demand|max demand|peak kw)$", "billed_demand"),
    (r"^((on|off|part) peak (usage|kwh)|peak kwh|meter subtotal)$", "period_usage"),
    (r"^(total amount|total amount due|taxes and fees|charges before credit|credit adjustment|annual total amount)$", "total_amount"),
    (r"^(fuel converted|distance converted|converted quantity|converted quantity therms|annual converted quantity|total converted quantity)$", "converted_quantity"),
    (r"^(run hours|total run hours|run hours total|total hours run)$", "run_hours"),
    (r"^(therm factor|usage ccf|usage mcf|tier\d .*|conversion factor|heat content factor)$", "conversion_factor"),
    (r"^(heat content|heat content conversion factor)$", "heat_content"),
    (r"^(invoice number|ticket number|delivery ticket number|tank id|delivery date|certificate number)$", "document_reference"),
    (rf"^{_Q} (diesel|gasoline)$", "activity_total"),
    (r"^(total (fuel )?(diesel|gasoline)|total fuel|total activity quantity|total activity quantity all meters|"
     r"annual activity quantity|annual fuel quantity|vehicle total gallons|total gallons|total added)$", "activity_total"),
    (rf"^{_Q}$", "activity_quantity"),
    (r"^(fuel added|fuel|added|gallons|gallons added|diesel gallons|fuel quantity|amount added|lb added|refrigerant added)$", "activity_quantity"),
    (r"^(amount recovered|lb recovered|refrigerant recovered)$", "refrigerant_recovered"),
    (r"^total recovered$", "refrigerant_recovered_total"),
    (r"^full charge$", "equipment_capacity"),
    (r"^(distance|distance odometer end start)$", "distance"),
    (r"^annual distance$", "distance_total"),
    (r"^fuel type$", "fuel_type"),
    (r"^vehicle type$", "vehicle_type"),
    (r"^model year$", "model_year"),
    (r"^(refrigerant type|refrigerant)$", "refrigerant_type"),
    (r"^technician$", "technician"),
    (r"^(equipment id|equipment)$", "equipment_id"),
    (r"^service address$", "service_address"),
)]

# Qualifiers on "activity quantity (...)" that say the value is a total over the document's records.
TOTAL_QUALIFIERS = re.compile(r"statement total|^total$|annual total|^q\d total|^diesel$|^gasoline$|^total fuel added$|all rows|sum")
# ... or a quantity that is in another unit than the printed one (not read by the extractor).
CONVERTED_QUALIFIERS = re.compile(r"convert")
# ... or a part-year slice of a long file (a reporting-year placement question, not a reading).
YEAR_SLICE_QUALIFIERS = re.compile(r"reporting year|recovered")


def family_of(base: str, qualifier: str = "") -> str:
    """The family id for a parsed key label (``META`` / ``UNMAPPED`` when it has none)."""

    text = re.sub(r"[^a-z0-9 ]", " ", base)
    text = re.sub(r"\s+", " ", text).strip()
    for pattern, family in RULES:
        if pattern.match(text):
            if family == "activity_quantity" and qualifier:
                if CONVERTED_QUALIFIERS.search(qualifier):
                    return "converted_quantity"
                if YEAR_SLICE_QUALIFIERS.search(qualifier):
                    return META
                if TOTAL_QUALIFIERS.search(qualifier):
                    return "activity_total"
            return family
    return UNMAPPED


def total_fuel_filter(base: str, qualifier: str) -> str | None:
    """"diesel" / "gasoline" when a total is restricted to one fuel."""

    for fuel in ("diesel", "gasoline"):
        if re.search(rf"\b{fuel}\b", f"{base} {qualifier}"):
            return fuel
    return None
