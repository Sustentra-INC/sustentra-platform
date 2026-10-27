"""AI settings: off by default, and the Anthropic key never shows."""

from __future__ import annotations

import argparse
import json

import pytest
from pydantic import SecretStr, ValidationError

from backend.app import cli
from backend.app.core.config import Settings

AI_ENV = ("AI_SUGGESTIONS_ENABLED", "AI_PROVIDER", "AI_MODEL", "AI_EFFORT", "AI_MONTHLY_CAP_USD", "ANTHROPIC_API_KEY")
TEST_KEY = "sk-ant-test-0123456789-never-real"


@pytest.fixture(autouse=True)
def _no_ai_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in AI_ENV:
        monkeypatch.delenv(name, raising=False)


def test_ai_is_off_by_default() -> None:
    settings = Settings()
    assert settings.ai_suggestions_enabled is False
    assert settings.ai_provider == "anthropic"
    assert settings.anthropic_api_key is None
    assert settings.ai_model == "claude-sonnet-5-5"
    assert settings.ai_effort == "low"
    assert settings.ai_monthly_cap_usd == 25.0


def test_ai_settings_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_SUGGESTIONS_ENABLED", "true")
    monkeypatch.setenv("AI_PROVIDER", "bedrock")
    monkeypatch.setenv("AI_MODEL", " claude-opus-5-5 ")
    monkeypatch.setenv("AI_EFFORT", "medium")
    monkeypatch.setenv("AI_MONTHLY_CAP_USD", "40")
    settings = Settings()
    assert settings.ai_suggestions_enabled is True
    assert settings.ai_provider == "bedrock"
    assert settings.ai_model == "claude-opus-5-5"
    assert settings.ai_effort == "medium"
    assert settings.ai_monthly_cap_usd == 40.0


@pytest.mark.parametrize(("name", "value"), [("AI_PROVIDER", "openai"), ("AI_EFFORT", "max"), ("AI_MONTHLY_CAP_USD", "-1")])
def test_bad_ai_values_are_refused(monkeypatch: pytest.MonkeyPatch, name: str, value: str) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        Settings()


def test_key_is_a_secret_and_masked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", TEST_KEY)
    settings = Settings()
    assert isinstance(settings.anthropic_api_key, SecretStr)
    assert settings.anthropic_api_key.get_secret_value() == TEST_KEY
    for shown in (repr(settings), str(settings), json.dumps(settings.model_dump(mode="json"))):
        assert TEST_KEY not in shown


def test_blank_key_counts_as_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # docker-compose.yml passes ${ANTHROPIC_API_KEY:-} through as "" when it is unset.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "  ")
    assert Settings().anthropic_api_key is None


def test_show_settings_masks_the_key(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", TEST_KEY)
    monkeypatch.setattr(cli, "get_settings", Settings)
    assert cli._show_settings(argparse.Namespace()) == 0
    printed = capsys.readouterr().out
    assert TEST_KEY not in printed
    assert json.loads(printed)["anthropic_api_key"] == "**********"
