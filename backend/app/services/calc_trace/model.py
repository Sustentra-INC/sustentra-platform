"""The step-level calculation trace: one shape for every calculation panel.

Types follow ``docs`` / ``contracts/calculation_trace.schema.json`` and the TypeScript twin in
``frontend/features/s1/api/calcTrace.ts``. A trace only *describes* a calculation that the calculators
already ran; it never feeds a number back into any total. ``to_dict`` gives the JSON the API carries
(full precision; a field that is ``None`` is left out, except where null is the answer: a term's first
operator, the Results step's number, an operand's or side's value, and the line result).
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any, Literal

TRACE_VERSION = 1

Panel = Literal["stationary", "mobile", "fugitive", "purchased_gases", "electricity", "steam", "heat", "cooling"]
PANELS: tuple[str, ...] = ("stationary", "mobile", "fugitive", "purchased_gases", "electricity", "steam", "heat",
                           "cooling")
State = Literal["complete", "blocked", "partial"]
SideStatus = Literal["not_reported", "suggested", "accepted", "edited", "rejected", "reference", "derived",
                     "awaiting_review"]
InputKind = Literal["evidence_sum", "reference", "reviewer_entered", "company_input", "methodology", "constant"]
Tag = Literal["detected_from_evidence", "not_used_for_this_line"]
OpSymbol = Literal["×", "÷", "+", "−"]
SOURCE_KINDS = ("document", "workbook_cell", "reference", "methodology", "entered", "derived")


@dataclass
class SourceRef:
    """Where a value comes from. ``kind`` picks which of the other fields apply (see the schema)."""

    kind: str
    document_id: str | None = None
    candidate_id: str | None = None
    file_name: str | None = None
    page: int | None = None
    quote: str | None = None
    sheet: str | None = None
    cell: str | None = None
    dataset: str | None = None
    table: str | None = None
    row: int | None = None
    edition: str | None = None
    citation: str | None = None
    field: str | None = None
    label: str | None = None
    by: str | None = None
    at: str | None = None
    reason: str | None = None
    from_: list[str] | None = None  # serialised as "from"


@dataclass
class Suggestion:
    origin: str  # "ai"
    value: str | float
    reason: str
    quote: str
    source: SourceRef
    model: str
    request_id: str
    suggested_at: str
    unit: str | None = None


@dataclass
class Decision:
    status: str  # pending | accepted | edited | rejected
    by: str
    at: str
    value: str | float | None = None
    unit: str | None = None
    reason: str | None = None


@dataclass
class Side:
    value: float | str | None
    unit: str | None
    status: str  # SideStatus
    source: SourceRef | None = None
    suggestion: Suggestion | None = None
    decision: Decision | None = None


@dataclass
class InputRow:
    id: str
    label: str
    company: Side | None = None
    recomputed: Side | None = None
    difference: float | None = None


@dataclass
class TraceInput:
    id: str
    label: str
    kind: str  # InputKind
    symbol: str | None = None
    required_for: list[str] = field(default_factory=list)
    company: Side | None = None
    recomputed: Side | None = None
    differs: bool | None = None
    difference: float | None = None
    rows: list[InputRow] | None = None
    decidable: bool = True  # a reviewer can accept or edit the recomputed value for this line
    why_not: str | None = None  # why not, when it cannot
    # A default the line uses where nothing is stated yet, shown as such until a reviewer decides the input:
    # "Default: <value> (<source>) · not confirmed"
    assumption: str | None = None


@dataclass
class ChoiceOption:
    id: str
    label: str
    available: bool = True
    equation: str | None = None
    why_unavailable: str | None = None
    detection: str | None = None  # Tag
    required_inputs: list[str] = field(default_factory=list)
    citation: SourceRef | None = None


@dataclass
class Choice:
    id: str
    label: str
    options: list[ChoiceOption]
    chosen: str
    chosen_by: str = "default"  # default | reviewer; an AI suggestion never sets it
    company: str | None = None
    suggestion: Suggestion | None = None
    decision: Decision | None = None


@dataclass
class Operand:
    column: str
    value: float | str | None
    unit: str | None = None
    input_id: str | None = None
    step_ref: str | None = None
    difference: float | None = None  # only on the recomputed row
    differs: bool | None = None


@dataclass
class Term:
    op: str | None  # None for the first term, else OpSymbol
    operand: Operand


@dataclass
class Operation:
    """``terms`` evaluated left to right give ``result``; see ``ops.evaluate``."""

    terms: list[Term]
    result: Operand


@dataclass
class Column:
    key: str
    label: str
    unit: str | None = None
    is_result: bool = False
    display: dict[str, int] = field(default_factory=dict)  # {"dp": n} or {"sig": n}


@dataclass
class TraceBlock:
    id: str
    label: str
    columns: list[Column]
    company: Operation | None = None
    recomputed: Operation | None = None
    tag: str | None = None  # Tag
    choice_id: str | None = None
    # a default the working uses that no reviewer has confirmed: "Default: 10% (EPA Table 1, …) · not confirmed"
    assumption: str | None = None
    # something a reviewer should check about this block's input: "Capacities differ between records (…)"
    warning: str | None = None


@dataclass
class TraceStep:
    id: str
    n: int | None  # 1..4, None = Results
    title: str
    blocks: list[TraceBlock]
    note: str | None = None


@dataclass
class Blocking:
    input_id: str
    message: str


@dataclass
class TraceResult:
    unit: str
    company: float | None
    recomputed: float | None
    difference: float | None


@dataclass
class LineTrace:
    line_key: str
    panel: str  # Panel
    state: str  # State
    result: TraceResult
    trace_version: int = TRACE_VERSION
    blocking: list[Blocking] = field(default_factory=list)
    choices: list[Choice] = field(default_factory=list)
    inputs: dict[str, TraceInput] = field(default_factory=dict)
    steps: list[TraceStep] = field(default_factory=list)
    method_mismatch: bool = False
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out = to_plain(self)
        assert isinstance(out, dict)
        return out


# (class name, field) pairs whose null is meaningful and so is kept on the wire.
_KEEP_NULL = {("Term", "op"), ("TraceStep", "n"), ("Operand", "value"), ("Side", "value"), ("TraceResult", "company"),
              ("TraceResult", "recomputed"), ("TraceResult", "difference")}


def to_plain(value: Any) -> Any:
    """Dataclasses to JSON-ready dicts, leaving out unset (``None``) fields except ``_KEEP_NULL``.
    ``from_`` is written ``from``. Keeps a line's trace small: a 5-line response would otherwise carry
    mostly nulls."""

    if is_dataclass(value) and not isinstance(value, type):
        out: dict[str, Any] = {}
        for f in fields(value):
            item = getattr(value, f.name)
            if item is None and (type(value).__name__, f.name) not in _KEEP_NULL:
                continue
            out["from" if f.name == "from_" else f.name] = to_plain(item)
        return out
    if isinstance(value, dict):
        return {k: to_plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_plain(v) for v in value]
    return value
