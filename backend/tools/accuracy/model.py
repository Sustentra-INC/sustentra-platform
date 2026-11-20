"""Plain data the harness passes around: what the extractor gave, and how each key cell scored."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Outcome statuses for one key cell.
MATCH = "match"  # the extractor gave the expected value
WRONG = "wrong"  # the extractor gave a different value
MISSED = "missed"  # the extractor has the field but gave no value, or no such record
NOT_TARGETED = "not_targeted"  # the extractor has no field for this yet: not scored
UNSCORED = "unscored"  # the key cell is not a value to read (note, reporting set, non-evidence file...)
STATUSES = (MATCH, WRONG, MISSED, NOT_TARGETED, UNSCORED)

# Flags that describe what the reader did, not a doubt about the value. A wrong value carrying only
# these is a silent error.
INFORMATIONAL_FLAGS = frozenset({"unit_converted", "grid_region_from_zip", "biofuel_blend",
                                 "no_certificates_market_equals_location"})
# Below this confidence the review screen shows a value as low confidence.
LOW_CONFIDENCE = 0.50


@dataclass(frozen=True)
class Item:
    """One extraction candidate."""

    field: str
    raw: Any
    value: Any  # the normalised value
    unit: str | None
    confidence: float | None
    flags: tuple[str, ...] = ()
    record: int | None = None  # record_index; None = a document-level value
    record_key: str | None = None

    @property
    def has_value(self) -> bool:
        return self.value is not None or self.raw is not None

    @property
    def warning_flags(self) -> tuple[str, ...]:
        return tuple(f for f in self.flags if f not in INFORMATIONAL_FLAGS and f != "field_not_found")

    @property
    def flagged(self) -> bool:
        """The reviewer is told to look: a warning flag, or a low confidence."""

        low = self.confidence is not None and self.confidence < LOW_CONFIDENCE
        return bool(self.warning_flags) or low


@dataclass
class ExtractedDoc:
    """What the pipeline made of one document."""

    filename: str
    status: str | None = None
    canonical_type_id: str | None = None
    halt_code: str | None = None
    targets: frozenset[str] = frozenset()
    items: list[Item] = field(default_factory=list)
    error: str | None = None

    @property
    def read(self) -> bool:
        """The document was typed and read (not halted as unreadable or unsupported)."""

        return bool(self.canonical_type_id) and not self.halt_code and not self.error


@dataclass(frozen=True)
class Outcome:
    set_name: str
    filename: str
    family: str
    status: str
    reason: str = ""
    label: str = ""
    expected: str = ""
    actual: str = ""
    exact: bool = False  # a match with no tolerance needed
    silent: bool = False  # a wrong value that carried no flag
    flags: tuple[str, ...] = ()
    confidence: float | None = None
