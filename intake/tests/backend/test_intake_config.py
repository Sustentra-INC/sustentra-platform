"""Config loading, environment overrides and controlled vocabularies."""

from __future__ import annotations

import pytest

from intake.backend import config as config_module
from intake.backend.config import (
    load_seed_form,
    load_settings,
    reset_caches,
    vocabulary_is_open,
    vocabulary_values,
)


@pytest.fixture
def clean_config_cache():
    reset_caches()
    yield
    reset_caches()


def test_settings_load_with_spec_values() -> None:
    settings = load_settings()
    # SPEC section 11 requires these as config, not literals in code.
    assert settings.escalation.primary_email == "vivian@sustentra.com"
    assert settings.escalation.secondary_email == "claire@sustentra.com"
    assert settings.escalation.sla_hours == 24
    assert settings.escalation.reminder_hours == 12


def test_roles_match_the_spec() -> None:
    assert set(load_settings().role_names()) == {
        "client_owner",
        "client_member",
        "sustentra_reviewer",
    }


def test_reviewer_cannot_submit_the_seed_form() -> None:
    roles = load_settings().roles
    assert roles["sustentra_reviewer"]["can_submit_seed_form"] is False
    assert roles["client_owner"]["can_submit_seed_form"] is True


def test_env_override_applies_and_is_type_coerced(monkeypatch, clean_config_cache) -> None:
    monkeypatch.setenv("INTAKE_MAGIC_LINK_TTL_MINUTES", "45")
    reset_caches()
    assert load_settings().auth.magic_link_ttl_minutes == 45


def test_data_dir_override_redirects_storage(monkeypatch, tmp_path, clean_config_cache) -> None:
    monkeypatch.setenv(config_module.DATA_DIR_ENV, str(tmp_path))
    reset_caches()
    assert load_settings().storage_path("orgs") == tmp_path / "orgs.jsonl"


def test_default_email_adapter_sends_nothing_real() -> None:
    """v1 must not be able to email a real person by accident."""
    assert load_settings().email.adapter == "outbox"


def test_lease_type_vocabulary_comes_from_the_workbook() -> None:
    assert vocabulary_values("lease_type") == ["finance_capital", "operating"]
    assert vocabulary_is_open("lease_type") is False


def test_party_role_vocabulary_comes_from_the_workbook() -> None:
    assert vocabulary_values("party_role") == ["lessee", "lessor", "owner_occupier", "neither"]


def test_open_vocabulary_is_flagged_open() -> None:
    """consolidation_approach is annotated OPEN in the workbook."""
    assert vocabulary_is_open("consolidation_approach") is True


def test_unknown_vocabulary_raises() -> None:
    with pytest.raises(KeyError):
        vocabulary_values("not_a_real_vocabulary")


def test_seed_form_copy_is_marked_placeholder() -> None:
    """SPEC section 10: final wording follows the Vocabulary Library review."""
    assert load_seed_form()["copy_status"] == "placeholder"
