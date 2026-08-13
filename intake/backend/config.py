"""Configuration loading for the intake workstream.

Config over code (CLAUDE.md): escalation contacts, SLAs, token lifetimes,
storage paths and vocabulary choices live in ``intake/config/*.json``, never as
literals in code. Every setting can be overridden by the environment variable
named in the settings file's ``env_overrides`` block, so nothing needs editing
to run against a different environment.

Loaders are cached; call ``reset_caches()`` in tests after pointing the loaders
at a temporary file.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parents[2]

SETTINGS_PATH = REPO_ROOT / "intake/config/intake_settings.json"
SEED_FORM_PATH = REPO_ROOT / "intake/config/seed_form.json"
PROFILE_SCHEMA_PATH = REPO_ROOT / "intake/config/profile_schema.json"
VOCABULARIES_PATH = REPO_ROOT / "intake/config/controlled_vocabularies.json"
LLM_CONFIG_PATH = REPO_ROOT / "intake/config/llm.json"
CONTRADICTIONS_PATH = REPO_ROOT / "intake/config/contradictions.json"
EVIDENCE_CADENCE_PATH = REPO_ROOT / "intake/config/evidence_cadence.json"
EMISSION_FACTOR_LIBRARY_PATH = (
    REPO_ROOT / "reference-data/config/libraries/emission_factor_library.json"
)
EVIDENCE_TYPE_LIBRARY_PATH = (
    REPO_ROOT / "reference-data/config/libraries/evidence_type_library.json"
)

DATA_DIR_ENV = "INTAKE_DATA_DIR"


class AuthSettings(BaseModel):
    magic_link_ttl_minutes: int
    session_ttl_hours: int
    token_bytes: int
    verify_url_template: str


class EscalationSettings(BaseModel):
    primary_email: str
    secondary_email: str
    sla_hours: int
    reminder_hours: int
    source: str | None = None
    human_class_policy: str = "always"
    human_class_policy_note: str | None = None
    digest_interval_minutes: int = 60
    digest_note: str | None = None
    review_url_template: str = "http://localhost:3000/intake/review/{escalation_id}"
    urgent_triggers: list[str] = Field(default_factory=list)
    urgent_triggers_note: str | None = None


class EmailSettings(BaseModel):
    adapter: str
    from_address: str
    outbox_path: str
    note: str | None = None
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_use_tls: bool = True


class ApiSettings(BaseModel):
    cors_allowed_origins: list[str]
    note: str | None = None


class IntakeSettings(BaseModel):
    """Typed view over intake/config/intake_settings.json."""

    settings_name: str
    settings_version: str
    auth: AuthSettings
    escalation: EscalationSettings
    email: EmailSettings
    api: ApiSettings
    roles: dict[str, Any]
    storage: dict[str, str]
    industries: list[dict[str, Any]]
    site_types: dict[str, Any]
    provisional_vocabularies: dict[str, Any]

    def storage_path(self, key: str) -> Path:
        """Absolute path for a storage key, honouring INTAKE_DATA_DIR."""
        try:
            relative = self.storage[key]
        except KeyError:
            raise KeyError(f"unknown storage key {key!r}") from None
        return _resolve_data_path(relative)

    def role_names(self) -> list[str]:
        return list(self.roles)

    def industry(self, value: str) -> dict[str, Any] | None:
        return next((item for item in self.industries if item["value"] == value), None)


def _resolve_data_path(relative: str) -> Path:
    """Resolve a storage path, redirecting to INTAKE_DATA_DIR when set."""
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        return Path(override) / Path(relative).name
    path = Path(relative)
    return path if path.is_absolute() else REPO_ROOT / path


def _coerce(current: Any, raw: str) -> Any:
    """Coerce an environment string to the type of the value it replaces."""
    if isinstance(current, bool):
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(current, int):
        return int(raw)
    if isinstance(current, float):
        return float(raw)
    if isinstance(current, list):
        # List settings are supplied as a comma-separated environment string.
        return [item.strip() for item in raw.split(",") if item.strip()]
    return raw


def _apply_env_overrides(payload: dict[str, Any]) -> dict[str, Any]:
    """Apply the env_overrides declared in the settings file."""
    overrides = payload.get("env_overrides", {})
    for env_name, dotted_path in overrides.items():
        if dotted_path.endswith(".*"):
            # Handled separately (INTAKE_DATA_DIR redirects every storage path).
            continue
        raw = os.environ.get(env_name)
        if raw is None:
            continue
        parts = dotted_path.split(".")
        node: Any = payload
        for part in parts[:-1]:
            node = node.get(part)
            if not isinstance(node, dict):
                node = None
                break
        if not isinstance(node, dict):
            continue
        leaf = parts[-1]
        if leaf in node:
            node[leaf] = _coerce(node[leaf], raw)
    return payload


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise RuntimeError(f"missing intake config file: {path}") from None
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{path}: invalid JSON - {exc}") from exc


@lru_cache(maxsize=1)
def load_settings() -> IntakeSettings:
    payload = _apply_env_overrides(_read_json(SETTINGS_PATH))
    return IntakeSettings.model_validate(payload)


@lru_cache(maxsize=1)
def load_seed_form() -> dict[str, Any]:
    return _read_json(SEED_FORM_PATH)


@lru_cache(maxsize=1)
def load_profile_schema() -> dict[str, Any]:
    return _read_json(PROFILE_SCHEMA_PATH)


@lru_cache(maxsize=1)
def load_controlled_vocabularies() -> dict[str, Any]:
    return _read_json(VOCABULARIES_PATH)


@lru_cache(maxsize=1)
def load_llm_config() -> dict[str, Any]:
    """LLM settings for Stage 2. Defaults to the disabled adapter."""
    return _apply_env_overrides(_read_json(LLM_CONFIG_PATH))


@lru_cache(maxsize=1)
def load_contradiction_rules() -> dict[str, Any]:
    """Deterministic checks for answers that conflict with what we already know."""
    return _read_json(CONTRADICTIONS_PATH)


@lru_cache(maxsize=1)
def load_emission_factor_library() -> dict[str, Any]:
    """Read-only access to the S2 emission factor library.

    Used for values the platform assigns rather than asks for - notably the GWP
    set behind BND-2.6, which comes from the library instead of being invented.
    """
    return _read_json(EMISSION_FACTOR_LIBRARY_PATH)


@lru_cache(maxsize=1)
def load_evidence_cadence() -> dict[str, Any]:
    """How often each J2 evidence type is expected (Phase E).

    Cadence is the one thing neither the evidence-type library nor the mapping
    states, except for electricity. Everything else here is flagged provisional.
    """
    return _read_json(EVIDENCE_CADENCE_PATH)


@lru_cache(maxsize=1)
def load_evidence_type_library() -> dict[str, Any]:
    """Read-only access to the J2 evidence types (J2-001 ... J2-020).

    Names and acceptance criteria are read from here rather than restated in
    intake config, so there is one definition of what a document type is.
    """
    return _read_json(EVIDENCE_TYPE_LIBRARY_PATH)


@lru_cache(maxsize=1)
def evidence_type_names() -> dict[str, str]:
    """``{"J2-002": "Electricity bill", ...}`` straight from the library."""
    return {
        entry["evidence_type_id"]: entry["evidence_type_name"]
        for entry in load_evidence_type_library().get("evidence_types", [])
    }


def default_gwp_set() -> dict[str, Any]:
    """The library's default GWP set, or the only one if none is marked default."""
    sets = load_emission_factor_library().get("gwp_sets") or []
    if not sets:
        raise RuntimeError(f"{EMISSION_FACTOR_LIBRARY_PATH}: no gwp_sets found")
    return next((item for item in sets if item.get("default_for_this_library")), sets[0])


def vocabulary_values(name: str) -> list[str]:
    """Permitted values for a controlled vocabulary extracted from the workbooks."""
    vocabularies = load_controlled_vocabularies()["vocabularies"]
    try:
        return list(vocabularies[name]["values"])
    except KeyError:
        raise KeyError(f"unknown controlled vocabulary {name!r}") from None


def vocabulary_is_open(name: str) -> bool:
    """True when the workbook marks the vocabulary OPEN (values are indicative)."""
    vocabularies = load_controlled_vocabularies()["vocabularies"]
    try:
        return bool(vocabularies[name]["open"])
    except KeyError:
        raise KeyError(f"unknown controlled vocabulary {name!r}") from None


def reset_caches() -> None:
    """Clear cached config (tests that patch paths or environment call this)."""
    load_settings.cache_clear()
    load_seed_form.cache_clear()
    load_profile_schema.cache_clear()
    load_controlled_vocabularies.cache_clear()
    load_emission_factor_library.cache_clear()
    load_llm_config.cache_clear()
    load_contradiction_rules.cache_clear()
    load_evidence_cadence.cache_clear()
    load_evidence_type_library.cache_clear()
    evidence_type_names.cache_clear()
