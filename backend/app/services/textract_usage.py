"""The ledger of Textract calls (table ``textract_usage``, migration 0029) and the scan side of the monthly limit.

One limit covers Sustentra's AI and scans together: ``ai_usage.month_spend_microusd`` adds both tables, and the
same ``settings.ai_monthly_cap_usd`` is checked against it. Before a call this module estimates its cost (pages
times the mode's price); a call that would take the month over the limit is not made, the caller marks the page
"not read", and the document can be read later. Every call that is made is recorded, ok or not (a failed call
costs 0: AWS does not bill an error). Only ids, counts and cost are stored.

The ledger works wherever there is a database (``DATABASE_URL`` set), whatever ``S1_STORE`` is, as the AI
ledger does (``ai_routing.DbLedger``); with no database URL at all (local development) nothing is recorded or checked. It is wired to ``textract_calls`` (the one place every
call goes through) once, the first time a Textract reader is built.
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from typing import Any, Protocol

from sqlalchemy import Engine, text

from backend.app.core.config import get_settings
from backend.app.core.db import tenant_transaction
from backend.app.core.s1_scope import S1Scope
from backend.app.services import ai_usage
from backend.app.services.pdf_scan_pages import SCAN_CAP_REACHED as SCAN_CAP_CODE
from backend.app.services.pdf_scan_pages import SCAN_LIMIT_SENTENCE, SCAN_UNCHECKED_SENTENCE
from backend.app.services.textract_calls import register_textract_gate, register_textract_hook

logger = logging.getLogger("sustentra.textract_usage")

SCAN_CAP_REACHED = SCAN_CAP_CODE
MESSAGE_CAP_REACHED = SCAN_LIMIT_SENTENCE
MESSAGE_UNCHECKED = SCAN_UNCHECKED_SENTENCE

FORMS_TABLES = "forms_tables"
TABLES = "tables"
FORMS = "forms"
DETECT_TEXT = "detect_text"

# What AWS charges per page, in micro-USD (1 USD = 1,000,000), first pricing tier, US regions.
# Source: https://aws.amazon.com/textract/pricing/ (checked 2026-11-26). AnalyzeDocument bills each feature
# type separately: Tables $0.015, Forms $0.05, both $0.065. DetectDocumentText (plain text) $0.0015.
PRICE_MICROUSD_PER_PAGE: dict[str, int] = {
    FORMS_TABLES: 65_000,
    TABLES: 15_000,
    FORMS: 50_000,
    DETECT_TEXT: 1_500,
}


def price_mode(feature_types: list[str] | None) -> str:
    """The price a call is billed at. No feature types is plain text detection; FORMS and TABLES alone are their
    own prices; anything else (QUERIES, SIGNATURES, LAYOUT, an unknown name) is priced as both, the highest."""

    features = {str(f).strip().upper() for f in feature_types or [] if str(f).strip()}
    if not features:
        return DETECT_TEXT
    if features == {"TABLES"}:
        return TABLES
    if features == {"FORMS"}:
        return FORMS
    return FORMS_TABLES


def page_count(pages: Any) -> int:
    """A page count as a non-negative int: a missing, negative or non-numeric count is 0 pages (nothing billed)."""

    if isinstance(pages, bool):
        return 0
    try:
        return max(0, int(pages))
    except (TypeError, ValueError):
        return 0


def estimate_microusd(pages: Any, mode: str) -> int:
    return page_count(pages) * PRICE_MICROUSD_PER_PAGE.get(mode, PRICE_MICROUSD_PER_PAGE[FORMS_TABLES])


def would_exceed(spent_microusd: int, estimate: int, cap_usd: float) -> bool:
    """True when ``estimate`` taken on top of ``spent_microusd`` goes over the cap. A call that costs nothing
    never exceeds it."""

    return estimate > 0 and spent_microusd + estimate > round(cap_usd * ai_usage.MICRO)


_INSERT = text(
    """
    INSERT INTO textract_usage (org_id, document_id, sha256, pages, mode, ok, cost_microusd)
    VALUES (:org_id, :document_id, :sha256, :pages, :mode, :ok, :cost_microusd)
    """
)


class ScanLedger(Protocol):
    def month_spend_microusd(self, org_id: uuid.UUID) -> int: ...

    def record(self, *, org_id: uuid.UUID, document_id: str | None, sha256: str | None, pages: int, mode: str,
               ok: bool, cost_microusd: int) -> None: ...


class DbScanLedger:
    """``textract_usage`` through the S1 stores' sync engine: one short ``tenant_transaction`` per call, in the
    organization's RLS scope, so no connection is held while Textract answers."""

    def __init__(self, engine: Engine | None = None) -> None:
        self._engine = engine  # None: the app's own sync engine

    def month_spend_microusd(self, org_id: uuid.UUID) -> int:
        with tenant_transaction(S1Scope.tenant(org_id), self._engine) as conn:
            return ai_usage.month_spend_microusd_sync(conn, org_id)

    def record(self, *, org_id: uuid.UUID, document_id: str | None, sha256: str | None, pages: int, mode: str,
               ok: bool, cost_microusd: int) -> None:
        with tenant_transaction(S1Scope.tenant(org_id), self._engine) as conn:
            conn.execute(_INSERT, {"org_id": org_id, "document_id": document_id, "sha256": sha256, "pages": pages,
                                   "mode": mode, "ok": ok, "cost_microusd": cost_microusd})


def _org(value: Any) -> uuid.UUID | None:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


_override: ScanLedger | None = None
_default = DbScanLedger()


def _active() -> ScanLedger | None:
    if _override is not None:
        return _override
    return None if get_settings().database_url is None else _default


def use_ledger(ledger: ScanLedger | None) -> Callable[[], None]:
    """Use ``ledger`` instead of the database (tests). Returns a function that puts the previous one back."""

    global _override
    previous = _override
    _override = ledger

    def restore() -> None:
        global _override
        _override = previous

    return restore


def _gate(request: dict[str, Any]) -> str | None:
    ledger = _active()
    org_id = _org(request.get("org_id"))
    if ledger is None or org_id is None:
        return None
    estimate = estimate_microusd(request.get("pages"), price_mode(request.get("feature_types")))
    if estimate == 0:
        return None
    if would_exceed(ledger.month_spend_microusd(org_id), estimate, get_settings().ai_monthly_cap_usd):
        return SCAN_CAP_REACHED
    return None


def _hook(record: dict[str, Any]) -> None:
    ledger = _active()
    org_id = _org(record.get("org_id"))
    pages = page_count(record.get("pages"))
    if ledger is None or org_id is None or pages == 0:
        return
    mode = price_mode(record.get("feature_types"))
    ok = bool(record.get("ok"))
    document_id = record.get("document_id")
    ledger.record(org_id=org_id, document_id=None if document_id is None else str(document_id),
                  sha256=record.get("sha256"), pages=pages, mode=mode, ok=ok,
                  cost_microusd=estimate_microusd(pages, mode) if ok else 0)


_installed = False
_install_lock = threading.Lock()


def ensure_installed() -> None:
    """Wire the ledger and the gate to ``textract_calls``, once."""

    global _installed
    with _install_lock:
        if _installed:
            return
        register_textract_gate(_gate)
        register_textract_hook(_hook)
        _installed = True
