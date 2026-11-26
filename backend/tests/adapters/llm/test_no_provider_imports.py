"""Only the provider modules in backend/app/adapters/llm/ may import a provider's library."""

from __future__ import annotations

import re
from pathlib import Path

APP = Path(__file__).resolve().parents[3] / "app"
LLM_DIR = APP / "adapters" / "llm"
PROVIDER_IMPORT = re.compile(r"^\s*(?:import|from)\s+anthropic\b", re.MULTILINE)


def test_nothing_outside_the_llm_adapters_imports_anthropic() -> None:
    offenders = [
        str(path.relative_to(APP))
        for path in APP.rglob("*.py")
        if LLM_DIR not in path.parents and PROVIDER_IMPORT.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_the_scan_sees_the_provider_modules() -> None:
    # Guards the scan itself: it must find the imports it is meant to confine.
    inside = [p.name for p in LLM_DIR.glob("*.py") if PROVIDER_IMPORT.search(p.read_text(encoding="utf-8"))]
    assert {"anthropic_api.py", "bedrock.py", "_claude_sdk.py"} <= set(inside)
