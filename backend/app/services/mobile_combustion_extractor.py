"""EXT-002 - deterministic extraction for CT-S1-MOBFUEL (mobile fuel transactions).

Handles fleet fuel-card statements, pump receipts and fleet fuel invoices (gasoline,
diesel, biodiesel blends, ethanol blends, CNG/LNG, propane/autogas).

Grain follows the Scope 1 schema's ``fuel_transaction`` (S1-MOB-110 / S1-MOB-410): a
statement yields one record per fuel transaction line; non-fuel lines (car wash, DEF /
AdBlue, motor oil, merchandise) are skipped. Fields:

    core         fuel_type, activity_quantity, activity_unit, transaction_date
    conditional  merchant_or_supplier, fueling_location, vehicle_or_equipment_id
    optional     transaction_id, account_number (card numbers are masked), biofuel_blend_pct

The layout engine (visual rows, label/value lookup, tables, bounding boxes) is the
EXT-001 one; this module supplies the mobile vocabulary and record assembly.

Distance / odometer readings are not extracted here: the schema keeps them in
CT-S1-TRANSACT (S1-MOB-050/120).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from backend.app.domain import fuel_units
from backend.app.services.stationary_combustion_extractor import (
    _ALL_LABELS as _BASE_LABELS,
)
from backend.app.services.stationary_combustion_extractor import (
    CONF_DOCUMENT_SCAN,
    CONF_TABLE,
    ELECTRIC_UNITS,
    HALT_UNREADABLE,
    HALT_UNSUPPORTED,
    ExtractionOutcome,
    Located,
    Row,
    StationaryCombustionExtractor,
    UsageRecord,
    _norm,
    parse_date,
)

CANONICAL_TYPE_ID = "CT-S1-MOBFUEL"

RECORD_FIELDS = ("fuel_type", "activity_quantity", "activity_unit", "transaction_date", "merchant_or_supplier",
                 "fueling_location", "vehicle_or_equipment_id", "transaction_id", "biofuel_blend_pct")
DOCUMENT_FIELDS = ("account_number",)

# --- fuel vocabulary ------------------------------------------------------------------
# Non-fuel lines, even when they name a fuel ("Federal excise tax - diesel", "DEF"):
# a line matching these is never a fuel line.
NON_FUEL_PATTERNS = re.compile(
    r"diesel exhaust fluid|\bdef\b|adblue|car ?wash|\bwash\b|oil change|motor oil|engine oil|"
    r"lubricant|washer fluid|windshield|merchandise|snacks?|convenience|tank rental|cylinder deposit|"
    r"\bfees?\b|\btax(?:es)?\b|\bexcise\b|surcharge|\bdeposit\b|\bdiscount\b|\brebate\b",
    re.IGNORECASE,
)
# (pattern, fuel_type) - most specific first; patterns are matched on normalized lower text.
MOBILE_FUELS: tuple[tuple[str, str], ...] = (
    (r"renewable diesel|\bhvo\b|\br99\b|\br100\b", "renewable_diesel"),
    (r"\bb100\b|biodiesel", "biodiesel"),
    (r"^b\d{1,2}$", "diesel"),  # a bare "B20" product code; "B20 diesel" is handled above
    (r"ultra low sulfur diesel|\bulsd\b|dyed diesel|\bdiesel\b|\bdsl\b|\bdiesel #?2\b", "diesel"),
    (r"flex ?fuel", "e85"),
    (r"compressed natural gas|\bcng\b", "cng"),
    (r"liquefied natural gas|\blng\b", "lng"),
    (r"\bpropane\b|\blpg\b|autogas|liquefied petroleum gas", "propane"),
    (r"\bjet[ -]?a\b|jet fuel|\bavtur\b", "jet_fuel"),
    (r"\bavgas\b|aviation gasoline|100ll", "aviation_gasoline"),
    (r"unleaded|\bunld?\b|gasoline|\bpetrol\b|midgrade|mid-grade|"
     r"regular unleaded|premium unleaded|super unleaded|\breg unl\b", "gasoline"),
    # Pump grade names alone ("Regular", "Plus 89", "Premium 93", "UNLD"): only when the
    # text is the grade itself (optionally with octane / ethanol code), not a sentence.
    (r"^(?:regular|reg|premium|prem|super|plus|mid|mid ?grade|unld|unl)(?: (?:8[5-9]|9[0-4]))?(?: e\d{1,2})?$|"
     r"^(?:8[5-9]|9[0-4]) octane$|\b(?:regular|premium|super|plus|mid) (?:8[5-9]|9[0-4])\b", "gasoline"),
)
_GRADE_CONTEXT = r"gas|unleaded|unld|fuel|ethanol|flex|petrol|regular|premium|super|plus|\bmid\b"
_MOBILE_FUEL_RE: tuple[tuple[re.Pattern[str], str], ...] = tuple((re.compile(p), f) for p, f in MOBILE_FUELS)
_BLEND_RE = re.compile(r"\b([be])(\d{1,3})\b")

# Signals that a fuel document is about vehicles/equipment rather than a building.
MOBILE_CUES = re.compile(
    r"\bvehicle\b|\bfleet\b|fuel card|\bcard\b|\bdriver\b|odometer|\bpump\b|\bunit #|\bunit no\b|"
    r"license plate|\bplate\b|\bmerchant\b|\bstation\b|price/gal|\bppg\b|/gal\b|\bforklift\b|\bvin\b",
    re.IGNORECASE,
)

# Explicit context that decides stationary vs mobile when the classifier cannot.
# Decisive cues count on their own; supporting cues only in pairs (an address's
# "Unit #4" or a company called "Fleet Street Gas" must not flip a gas bill).
DECISIVE_MOBILE_CUES = re.compile(r"fuel ?card|fleet card|odometer|\bforklifts?\b|license plate|\bmpg\b", re.I)
SUPPORTING_MOBILE_CUES = re.compile(
    r"\bfleet\b|\bvehicles?\b|\bpump\b|\btruck stop\b|"
    r"\bunit #(?=[ \t]*(?:$|[a-z]{1,4}-?\d))|\bunit no\.?(?=[ \t]*(?:$|[a-z]{1,4}-?\d))",
    re.I | re.M,
)
DECISIVE_STATIONARY_CUES = re.compile(
    r"\bboilers?\b|\bfurnaces?\b|\bgenerators?\b|heating oil|day tank|\btherms?\b|\bstandby\b", re.I
)
SUPPORTING_STATIONARY_CUES = re.compile(
    r"space heat|\bkiln|\bbuilding\b|service address|\bpremises\b|\bmeter (?:number|#|id|reading)", re.I
)


def fuel_use_cues(parser_output: dict) -> tuple[list[str], list[str]]:
    """(mobile cues, stationary cues) that are strong enough to act on.

    A side counts only with a decisive cue or at least two distinct supporting cues;
    otherwise its list is empty.
    """

    texts: list[str] = [str(p.get("text") or "") for p in parser_output.get("pages") or [] if isinstance(p, dict)]
    if not any(texts):
        texts = [str(b.get("text") or "") for b in parser_output.get("text_blocks") or [] if isinstance(b, dict)]
    corpus = "\n".join(texts)

    def side(decisive: re.Pattern[str], supporting: re.Pattern[str]) -> list[str]:
        strong = {" ".join(m.group(0).lower().split()) for m in decisive.finditer(corpus)}
        weak = {" ".join(m.group(0).lower().split()) for m in supporting.finditer(corpus)}
        return sorted(strong | weak) if strong or len(weak) >= 2 else []

    return (side(DECISIVE_MOBILE_CUES, SUPPORTING_MOBILE_CUES),
            side(DECISIVE_STATIONARY_CUES, SUPPORTING_STATIONARY_CUES))


def names_combusted_fuel(parser_output: dict) -> bool:
    """True when any line names a stationary or mobile fuel."""

    from backend.app.services.stationary_combustion_extractor import detect_fuel

    texts = [str(p.get("text") or "") for p in parser_output.get("pages") or [] if isinstance(p, dict)]
    texts += [str(b.get("text") or "") for b in parser_output.get("text_blocks") or [] if isinstance(b, dict)]
    lines = [line for text in texts for line in text.splitlines()]
    return any(normalize_mobile_fuel(line) or detect_fuel(line) for line in lines)


# --- labels ---------------------------------------------------------------------------
MERCHANT_LABELS: tuple[tuple[str, ...], ...] = (
    ("merchant name", "merchant", "station name", "station", "sold by", "vendor", "supplier", "site name"),
)
LOCATION_LABELS: tuple[tuple[str, ...], ...] = (
    ("station address", "merchant address", "site address", "fueling location", "location", "address",
     "city/state", "city"),
)
VEHICLE_LABELS: tuple[tuple[str, ...], ...] = (
    ("vehicle id", "vehicle #", "vehicle no", "vehicle number", "vehicle", "unit #", "unit no", "unit number",
     "asset id", "asset #", "asset", "equipment id", "equipment", "truck #", "truck no", "fleet #"),
)
TRANSACTION_ID_LABELS: tuple[tuple[str, ...], ...] = (
    ("transaction #", "transaction no", "transaction id", "trans #", "trans no", "receipt #", "receipt no",
     "invoice #", "invoice no", "invoice number", "ticket #", "ticket no", "sale #", "reference #"),
)
DATE_LABELS: tuple[tuple[str, ...], ...] = (
    ("transaction date", "purchase date", "sale date", "fueling date", "fill date", "date/time", "date"),
)
CARD_LABELS: tuple[tuple[str, ...], ...] = (
    ("card number", "card no", "card #", "fleet card", "fuel card", "account number", "account no", "account #",
     "customer number", "customer no", "account", "card"),
)
QUANTITY_LABELS: tuple[tuple[str, ...], ...] = (
    # labels that carry the unit first; a bare "Qty" can belong to a coffee
    ("total gallons", "total litres", "total liters", "gallons", "litres", "liters", "volume", "fuel quantity",
     "total propane weight", "gge", "dge"),
    ("quantity", "qty"),
)
FUEL_LABELS: tuple[tuple[str, ...], ...] = (("product", "fuel type", "fuel grade", "grade", "fuel", "description"),)

# Statement columns kept on each record.
EXTRA_COLUMNS: dict[str, tuple[str, ...]] = {
    "vehicle": ("unit #", "unit no", "unit number", "unit", "vehicle", "vehicle #", "vehicle id", "veh #", "asset",
                "asset #", "asset id", "equipment", "truck #", "truck"),
    "card": ("card", "card #", "card no", "card number", "card last 4"),
    "merchant": ("merchant", "merchant name", "station", "station name", "vendor", "site", "site name"),
    "location": ("city", "city/state", "city, st", "location", "merchant city", "station city", "address", "state"),
    "transaction": ("transaction #", "trans #", "transaction id", "trans id", "receipt #", "invoice",
                    "invoice #", "ticket #", "ref #", "reference"),
}
DATE_HEADERS = ("date", "transaction date", "trans date", "purchase date", "date/time", "posted", "post date",
                "sale date", "fill date", "delivery date")
PRODUCT_HEADERS = ("product", "description", "fuel", "fuel type", "grade", "fuel grade", "item")

# Card-number shapes only: 15-19 contiguous digits, or 4-4-4-4(-3) groups with one
# separator. Column-joined text ("03/02/2026  1012  4471 2209") is not a card.
_PAN_RE = re.compile(r"(?<![\d/.-])(?:\d{15,19}|\d{4}([ -])\d{4}\1\d{4}\1\d{4}(?:\1\d{1,3})?)(?![\d/.-])")
_RECEIPT_QTY_RE = re.compile(
    r"(?<![\d.,])(?P<qty>\d{1,4}(?:[.,]\d{1,3}))\s*(?P<unit>gallons?|gals?|g|litres?|liters?|ltrs?|l|gge|dge)\b"
    r"\s*(?:@|x\b|at\b)",
    re.IGNORECASE,
)


def normalize_mobile_fuel(text: str) -> tuple[str, int | None, str] | None:
    """(fuel_type, biofuel_blend_pct, matched text) for a product description, or None.

    B100 / "biodiesel" -> biodiesel (100); Bxx -> diesel with a xx% biodiesel blend;
    E10/E15 -> gasoline with ethanol blend; E51-E85 / flex fuel -> e85. Lines naming a
    non-fuel item (DEF/AdBlue, car wash, motor oil, taxes, fees...) are never fuel.
    """

    if NON_FUEL_PATTERNS.search(str(text)):
        return None
    low = _norm(str(text))
    # A stated biodiesel blend below B100 is diesel with a blend share, even when the
    # product says "biodiesel" ("B20 Biodiesel").
    for letter, digits in _BLEND_RE.findall(low):
        if letter == "b" and 1 <= int(digits) < 100 and ("diesel" in low or re.fullmatch(r"b\d{1,2}", low)):
            return "diesel", int(digits), f"b{digits}"
        # Ethanol blends: E51-E85 is "e85" (mostly ethanol); E1-E50 is gasoline with a blend share.
        if letter == "e" and (re.search(_GRADE_CONTEXT, low) or re.fullmatch(r"e\d{1,2}", low)):
            pct = int(digits)
            if 51 <= pct <= 85:
                return "e85", pct, f"e{digits}"
            if 1 <= pct <= 50:
                return "gasoline", pct, f"e{digits}"
    for pattern, fuel in _MOBILE_FUEL_RE:
        match = pattern.search(low)
        if match is None:
            continue
        blend: int | None = None
        for letter, digits in _BLEND_RE.findall(low):
            pct = int(digits)
            if letter == "b" and fuel in ("diesel", "biodiesel") and 1 <= pct <= 100:
                blend = pct
            elif letter == "e" and fuel in ("gasoline", "e85") and 1 <= pct <= 100:
                blend = pct
        if fuel == "biodiesel" and blend is None:
            blend = 100
        return fuel, blend, match.group(0)
    return None


def mask_card_numbers(text: Any) -> Any:
    """Replace card-number shapes with ****last4."""

    if not isinstance(text, str):
        return text
    return _PAN_RE.sub(lambda m: "****" + re.sub(r"\D", "", m.group(0))[-4:], text)


class MobileCombustionExtractor(StationaryCombustionExtractor):
    """Builds CT-S1-MOBFUEL candidates: one record per fuel transaction."""

    CANONICAL_TYPE_ID = CANONICAL_TYPE_ID
    FUEL_LABEL_GROUPS = FUEL_LABELS
    QUANTITY_LABEL_GROUPS = QUANTITY_LABELS
    ID_HEADERS = ()
    PRODUCT_HEADERS = PRODUCT_HEADERS
    DATE_HEADERS = DATE_HEADERS
    # On fleet statements a bare "Unit" column is the vehicle and "Units" the quantity.
    UNIT_HEADERS = ("uom", "unit of measure", "u/m")
    EXTRA_COLUMNS = EXTRA_COLUMNS
    QTY_EXCLUDE = StationaryCombustionExtractor.QTY_EXCLUDE + ("odometer", "miles", "mpg", "km", "ppg", "/gal",
                                                               "price/", "per gal", "per litre", "per liter")
    ALL_LABELS = _BASE_LABELS + tuple(
        label
        for group in (MERCHANT_LABELS + LOCATION_LABELS + VEHICLE_LABELS + TRANSACTION_ID_LABELS + DATE_LABELS
                      + CARD_LABELS + QUANTITY_LABELS + FUEL_LABELS)
        for label in group
    )

    def _fuel(self, text: str) -> tuple[str, str] | None:
        hit = normalize_mobile_fuel(text)
        return (hit[0], hit[2]) if hit else None

    def _quantity_header_score(self, text: str) -> int:
        if text.strip(" :#") in ("units", "unit qty", "qty units", "gallons/units"):
            return 3
        return super()._quantity_header_score(text)

    def _document_fuel(self, rows: Sequence[Row]) -> Located | None:
        labeled = self._find_labeled(rows, self.FUEL_LABEL_GROUPS, accept=lambda v: self._fuel(v) is not None,
                                     accept_bare=lambda v: self._fuel(v) is not None)
        if labeled is not None:
            return labeled
        # Free-text scan: a bare code like "B12" (a bus or a bay) is not a fuel here.
        for row in rows:
            for cell in row.cells:
                if not re.fullmatch(r"[be]\d{1,2}", _norm(cell.text)) and self._fuel(cell.text) is not None:
                    return Located(cell.text, [cell], row, CONF_DOCUMENT_SCAN)
        return None

    def confirms(self, parser_output: dict) -> bool:
        """Content check: a mobile fuel, a quantity in a fuel unit, and a vehicle/fleet cue."""

        rows = self._rows(parser_output)
        if not any(MOBILE_CUES.search(cell.text) for row in rows for cell in row.cells):
            return False
        return super().confirms(parser_output)

    # ---------------------------------------------------------------------------------
    def _extract(self, rows: list[Row], parser_output: dict, targets: Sequence[dict], evidence_id: str,
                 document_id: str) -> ExtractionOutcome:
        if not any(cell.text.strip() for row in rows for cell in row.cells):
            return ExtractionOutcome(candidates=[], halt_reason={
                "code": HALT_UNREADABLE,
                "message": "No readable text was found in the document (for example a photographed receipt "
                "while OCR is off, or an empty file). Upload a text-based PDF or enable OCR.",
            })
        doc_fuel = self._document_fuel(rows)
        records = self._quantity_records(rows)
        unit_hint = self._document_unit(rows)
        units = {fuel_units.find_unit(r.unit_raw or (unit_hint.raw if unit_hint else "")) for r in records}
        if records and units <= ELECTRIC_UNITS:
            return ExtractionOutcome(candidates=[], halt_reason={
                "code": HALT_UNSUPPORTED,
                "message": "The quantities are electricity (kWh) - for example EV charging. Purchased "
                "electricity is Scope 2, not mobile combustion.",
            })
        if doc_fuel is None:
            return ExtractionOutcome(candidates=[], halt_reason={
                "code": HALT_UNSUPPORTED,
                "message": "No vehicle fuel (gasoline, diesel, biodiesel, ethanol blend, CNG, LNG, propane or "
                "jet fuel) is named in the document, so it is not mobile-combustion evidence.",
            })

        document = {
            "merchant_or_supplier": self._merchant(rows),
            "fueling_location": self._find_labeled(rows, LOCATION_LABELS, accept=lambda v: len(v) > 2),
            "vehicle_or_equipment_id": (
                self._find_labeled(rows, VEHICLE_LABELS, accept=lambda v: bool(re.search(r"\d", v)),
                                   accept_bare=self._looks_like_id)
                # receipts print "Unit: T-118" for the vehicle; a unit of measure has no digits
                or self._find_labeled(rows, (("unit",),), accept=self._looks_like_vehicle_id)
            ),
            "transaction_id": self._find_labeled(rows, TRANSACTION_ID_LABELS, accept=self._looks_like_id,
                                                 accept_bare=self._looks_like_id),
            "account_number": self._find_labeled(rows, CARD_LABELS, accept=self._looks_like_id,
                                                 accept_bare=self._looks_like_id),
        }
        doc_date = self._find_labeled(rows, DATE_LABELS, accept=lambda v: parse_date(v) is not None)
        if doc_date is None:
            doc_date = self._document_period(rows)[0]

        candidates: list[dict] = []
        record_list: list[UsageRecord | None] = list(records) if records else [None]
        multi = len(record_list) > 1
        for index, record in enumerate(record_list, start=1):
            values = self._record_values(record, (doc_date, doc_date), doc_fuel, unit_hint)
            fuel_loc = record.fuel if record and record.fuel else doc_fuel
            normalized_fuel = normalize_mobile_fuel(fuel_loc.raw)
            record_index = index if multi else None
            record_key = self._mobile_record_key(index, record, values) if multi else None
            record_candidates: list[dict] = []
            for target in targets:
                field_id = str(target.get("field_id") or "")
                record_candidates.append(self._mobile_candidate(
                    target, field_id, record, values, document, normalized_fuel, fuel_loc, document_id,
                    evidence_id, record_key, record_index, parser_output))
            if multi:
                label = self._mobile_record_display(index, record, values)
                for candidate in record_candidates:
                    candidate["display_label"] = f"{candidate['display_label']} ({label})"
                    candidate["source_reference"]["record_key"] = record_key
            candidates.extend(record_candidates)
        for candidate in candidates:  # never keep full card numbers anywhere
            candidate["raw_value"] = mask_card_numbers(candidate["raw_value"])
            candidate["normalized_value"] = mask_card_numbers(candidate["normalized_value"])
            ref = candidate["source_reference"]
            ref["text_snippet"] = mask_card_numbers(ref.get("text_snippet"))
        return ExtractionOutcome(candidates=candidates, records=len(record_list) if records else 0)

    # ---------------------------------------------------------------------------------
    def _mobile_candidate(self, target: dict, field_id: str, record: UsageRecord | None, values: dict[str, Any],
                          document: dict[str, Located | None], normalized_fuel: tuple[str, int | None, str] | None,
                          fuel_loc: Located, document_id: str, evidence_id: str, record_key: str | None,
                          record_index: int | None, parser_output: dict) -> dict:
        args = (document_id, evidence_id, record_key, record_index)
        if field_id in ("activity_quantity", "activity_unit"):
            return self._record_candidate(target, values, *args, parser_output)
        if field_id == "transaction_date":
            hit = values.get("service_period_start")
            if hit is None:
                return self._missing(target, *args)
            located, iso = hit
            return self._candidate(target, located, located.raw, iso, None, *args, parser_output, [])
        if field_id == "fuel_type":
            if normalized_fuel is None:
                return self._missing(target, *args)
            flags = []
            allowed = (target.get("normalization") or {}).get("allowed_values") or []
            if allowed and normalized_fuel[0] not in allowed:
                flags.append("value_not_in_allowed_values")
            if normalized_fuel[1] is not None and normalized_fuel[1] < 100:
                flags.append("biofuel_blend")
            return self._candidate(target, fuel_loc, fuel_loc.raw, normalized_fuel[0], None, *args, parser_output,
                                   flags)
        if field_id == "biofuel_blend_pct":
            if normalized_fuel is None or normalized_fuel[1] is None:
                return self._missing(target, *args)
            return self._candidate(target, fuel_loc, normalized_fuel[2], normalized_fuel[1], "%", *args,
                                   parser_output, [])
        column = {"merchant_or_supplier": "merchant", "fueling_location": "location",
                  "vehicle_or_equipment_id": "vehicle", "transaction_id": "transaction",
                  "account_number": "card"}.get(field_id)
        if column is None:
            return self._missing(target, *args, ["unsupported_extraction_method"])
        located = record.extra.get(column) if record is not None else None
        if located is None:
            located = document.get(field_id)
        masked: list[str] = []
        if located is not None and field_id == "account_number" and _PAN_RE.search(located.raw):
            masked.append("card_number_masked")
        candidate = self._candidate_for_text(target, located, *args, parser_output, field_id)
        candidate["validation_flags"].extend(masked)
        return candidate

    def _merchant(self, rows: Sequence[Row]) -> Located | None:
        labeled = self._find_labeled(rows, MERCHANT_LABELS, accept=self._looks_like_org_name, allow_next_row=False)
        if labeled is not None:
            return labeled
        letterhead = self._letterhead(rows)
        if letterhead is not None:
            return letterhead
        # Plain-text receipts: the first line is the station name ("ROUTE 9 FUEL STOP").
        for row in rows[:2]:
            text = row.cells[0].text
            if (len(row.cells) == 1 and self._looks_like_org_name(text) and parse_date(text) is None
                    and not re.search(r"\d{3,}", text)):
                name = re.split(r"\s+[-\u2013\u2014|]\s+", text)[0].strip()
                return Located(name, [row.cells[0]], row, CONF_DOCUMENT_SCAN, context=text)
        return None

    @staticmethod
    def _looks_like_vehicle_id(value: str) -> bool:
        token = value.split()[0] if value.split() else ""
        return bool(re.fullmatch(r"[A-Za-z]{0,4}[- ]?\d[\w-]*", token)) and fuel_units.canonical_unit(token) is None

    @staticmethod
    def _looks_like_id(value: str) -> bool:
        token = value.split()[0] if value.split() else ""
        return bool(re.search(r"\d", token)) and parse_date(value) is None and not value.startswith("$")

    def _quantity_records(self, rows: Sequence[Row]) -> list[UsageRecord]:
        records = super()._quantity_records(rows) or self._receipt_records(rows)
        for record in records:
            # A "Unit" column holding GAL / L is a unit of measure, not a vehicle.
            vehicle = record.extra.get("vehicle")
            if vehicle is not None and fuel_units.canonical_unit(vehicle.raw) is not None:
                del record.extra["vehicle"]
                if record.unit_raw is None:
                    record.unit_raw, record.unit_located = vehicle.raw, vehicle
        return records

    def _receipt_records(self, rows: Sequence[Row]) -> list[UsageRecord]:
        """Pump receipts: one record per "12.457 G @ $3.459/G" line.

        The product is on the same line or the line just above; lines for non-fuel
        products (DEF, washer fluid...) are skipped. Single-letter units are only
        accepted before a price.
        """

        records: list[UsageRecord] = []
        for position, row in enumerate(rows):
            for cell in row.cells:
                match = _RECEIPT_QTY_RE.search(cell.text)
                if match is None:
                    continue
                product_cells = [c for c in row.cells if c is not cell] + [cell]
                above = rows[position - 1] if position > 0 and rows[position - 1].page == row.page else None
                if above is not None and not any(_RECEIPT_QTY_RE.search(c.text) for c in above.cells):
                    product_cells += above.cells
                if any(NON_FUEL_PATTERNS.search(c.text) for c in product_cells):
                    continue
                fuel_cell = next((c for c in product_cells if self._fuel(c.text) is not None), None)
                fuel = None
                if fuel_cell is not None:
                    fuel_row = row if fuel_cell in row.cells else above
                    fuel = Located(fuel_cell.text, [fuel_cell], fuel_row, CONF_TABLE)
                unit = match.group("unit")
                records.append(UsageRecord(
                    quantity=Located(match.group("qty"), [cell], row, CONF_DOCUMENT_SCAN + 0.1, context=row.text),
                    unit_raw={"g": "gal", "l": "L"}.get(unit.lower(), unit),
                    unit_located=None,
                    hint=None,
                    fuel=fuel,
                ))
        return records

    @staticmethod
    def _mobile_record_display(index: int, record: UsageRecord | None, values: dict[str, Any]) -> str:
        parts = [f"record {index}"]
        date_hit = values.get("service_period_start")
        if date_hit:
            parts.append(date_hit[1])
        if record is not None:
            vehicle = record.extra.get("vehicle")
            if vehicle is not None:
                parts.append(vehicle.raw.strip())
        return " · ".join(parts)

    @staticmethod
    def _mobile_record_key(index: int, record: UsageRecord | None, values: dict[str, Any]) -> str:
        parts = [f"r{index}"]
        date_hit = values.get("service_period_start")
        if date_hit:
            parts.append(date_hit[1])
        if record is not None:
            for key in ("vehicle", "transaction"):
                located = record.extra.get(key)
                if located is not None:
                    parts.append(re.sub(r"\s+", "_", mask_card_numbers(located.raw.strip())))
        return ":".join(parts)

