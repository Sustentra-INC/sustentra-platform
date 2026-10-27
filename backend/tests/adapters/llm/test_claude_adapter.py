"""The Claude adapter, with the HTTP layer faked: no test reaches the network."""

from __future__ import annotations

import json
import logging
from typing import Any

import anthropic
import httpx2
import pytest
from pydantic import BaseModel, ConfigDict, Field

from backend.app.adapters.llm import claude
from backend.app.adapters.llm.claude import (
    AiNotConfiguredError,
    SdkClaude,
    TokenUsage,
    UnknownModelError,
    cost_microusd,
    get_claude,
)
from backend.app.core.config import Settings

TEST_KEY = "sk-ant-test-0123456789-never-real"


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str = Field(max_length=10)


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {"ai_provider": "anthropic", "anthropic_api_key": None, "ai_model": "claude-sonnet-5-5"}
    values.update(overrides)
    return Settings(**values)


def _message(
    *,
    text: str = '{"value": "42"}',
    stop_reason: str = "end_turn",
    model: str = "claude-sonnet-5-5",
    usage: dict[str, Any] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": text}] if text else [],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": usage or {"input_tokens": 1_000, "output_tokens": 200},
        **extra,
    }


class FakeApi:
    """Records each request and answers with a canned Messages API body."""

    def __init__(self, body: dict[str, Any]) -> None:
        self.body = body
        self.requests: list[httpx2.Request] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return httpx2.Response(200, headers={"request-id": "req_test"}, json=self.body)

    def http_client(self) -> httpx2.Client:
        return httpx2.Client(transport=httpx2.MockTransport(self.handler))

    @property
    def sent(self) -> dict[str, Any]:
        return json.loads(self.requests[-1].content)


def _anthropic_claude(api: FakeApi, model: str = "claude-sonnet-5-5") -> SdkClaude:
    sdk = anthropic.Anthropic(api_key=TEST_KEY, http_client=api.http_client(), max_retries=0)
    return SdkClaude(sdk, provider="anthropic", model=model, effort="low")


def _ask(client: SdkClaude) -> claude.StructuredReply[Answer]:
    return client.structured(system="Rules.", content="Document lines.", output_type=Answer, max_tokens=8_000)


# --- factory ---------------------------------------------------------------------------------


def test_no_key_means_no_client() -> None:
    assert get_claude(_settings()) is None


def test_key_gives_an_anthropic_client() -> None:
    client = get_claude(_settings(anthropic_api_key=TEST_KEY))
    assert client is not None
    assert (client.provider, client.model) == ("anthropic", "claude-sonnet-5-5")
    sdk = claude.build_sdk_client(_settings(anthropic_api_key=TEST_KEY))
    assert isinstance(sdk, anthropic.Anthropic)
    assert (sdk.timeout, sdk.max_retries) == (claude.REQUEST_TIMEOUT_S, claude.MAX_RETRIES)


def test_unknown_model_is_refused() -> None:
    with pytest.raises(UnknownModelError):
        get_claude(_settings(anthropic_api_key=TEST_KEY, ai_model="claude-made-up-9"))
    # Even before a key exists, so a typo shows up on staging before the key does.
    with pytest.raises(UnknownModelError):
        get_claude(_settings(ai_model="claude-made-up-9"))


@pytest.fixture
def fake_aws(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> pytest.MonkeyPatch:
    """Static fake credentials, no region, and none of this machine's AWS config."""
    for name in ("AWS_REGION", "AWS_DEFAULT_REGION", "AWS_PROFILE", "AWS_SESSION_TOKEN",
                 "AWS_BEARER_TOKEN_BEDROCK", "ANTHROPIC_AWS_API_KEY", "ANTHROPIC_BEDROCK_MANTLE_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "none"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "none"))
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIDEXAMPLE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "not-a-real-secret")
    return monkeypatch


def test_bedrock_needs_no_key(fake_aws: pytest.MonkeyPatch) -> None:
    fake_aws.setenv("AWS_REGION", "us-east-1")
    client = get_claude(_settings(ai_provider="bedrock"))
    assert client is not None
    assert (client.provider, client.model) == ("bedrock", "claude-sonnet-5-5")
    sdk = claude.build_sdk_client(_settings(ai_provider="bedrock"))
    assert isinstance(sdk, anthropic.AnthropicBedrockMantle)
    assert (sdk.timeout, sdk.max_retries) == (claude.REQUEST_TIMEOUT_S, claude.MAX_RETRIES)


def test_bedrock_without_a_region_is_a_config_error(fake_aws: pytest.MonkeyPatch) -> None:
    with pytest.raises(AiNotConfiguredError, match="Bedrock"):
        get_claude(_settings(ai_provider="bedrock"))


# --- cost ------------------------------------------------------------------------------------

ONE_MILLION_EACH = TokenUsage(
    input_tokens=1_000_000,
    output_tokens=1_000_000,
    cache_read_tokens=1_000_000,
    cache_write_5m_tokens=1_000_000,
    cache_write_1h_tokens=1_000_000,
)


@pytest.mark.parametrize(
    ("model", "usd"),
    [
        # input + output + cache read + 5m write + 1h write, USD per million tokens.
        ("claude-opus-5-5", 4 + 20 + 0.20 + 5 + 8),
        ("claude-sonnet-5-5", 2 + 10 + 0.10 + 2.50 + 4),
        ("anthropic.claude-sonnet-5-5", 2 + 10 + 0.10 + 2.50 + 4),
        ("claude-sonnet-5", 2 + 10 + 0.20 + 2.50 + 4),
        ("claude-opus-5", 5 + 25 + 0.50 + 6.25 + 10),
        ("claude-opus-4-8", 5 + 25 + 0.50 + 6.25 + 10),
        # 5M prompt tokens: Claude Haiku 5.5's long-prompt rate card.
        ("claude-haiku-5-5", 0.50 + 2.50 + 0.05 + 0.625 + 1),
    ],
)
def test_cost_per_model(model: str, usd: float) -> None:
    assert cost_microusd(model, ONE_MILLION_EACH) == round(usd * 1_000_000)


def test_cost_of_one_bill() -> None:
    # 3,000 input, 2,500 written to the 5-minute cache, 1,200 output on Claude Sonnet 5.5:
    # 3,000 x $2 + 2,500 x $2.50 + 1,200 x $10 per million = $0.02425.
    usage = TokenUsage(input_tokens=3_000, output_tokens=1_200, cache_write_5m_tokens=2_500)
    assert cost_microusd("claude-sonnet-5-5", usage) == 24_250
    # A cache hit on the same prompt: 3,000 x $2 + 2,500 x $0.10 + 1,200 x $10 = $0.01825.
    usage = TokenUsage(input_tokens=3_000, output_tokens=1_200, cache_read_tokens=2_500)
    assert cost_microusd("claude-sonnet-5-5", usage) == 18_250


def test_haiku_switches_rate_card_above_100k_prompt_tokens() -> None:
    at_limit = TokenUsage(input_tokens=90_000, cache_read_tokens=10_000, output_tokens=1_000)
    over = TokenUsage(input_tokens=90_001, cache_read_tokens=10_000, output_tokens=1_000)
    # 90,000 x 0.10 + 10,000 x 0.01 + 1,000 x 0.50 = 9,600 micro-USD.
    assert cost_microusd("claude-haiku-5-5", at_limit) == 9_600
    # 90,001 x 0.50 + 10,000 x 0.05 + 1,000 x 2.50 = 48,000.5 -> 48,001.
    assert cost_microusd("claude-haiku-5-5", over) == 48_001


def test_cost_of_an_unknown_model_raises() -> None:
    with pytest.raises(UnknownModelError):
        cost_microusd("gpt-4o", TokenUsage(input_tokens=1))


# --- structured() ----------------------------------------------------------------------------


def test_structured_request_and_reply() -> None:
    api = FakeApi(_message(usage={
        "input_tokens": 3_000, "output_tokens": 1_200, "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 2_500,
        "cache_creation": {"ephemeral_5m_input_tokens": 2_500, "ephemeral_1h_input_tokens": 0},
    }))
    reply = _ask(_anthropic_claude(api))

    assert reply.outcome == "ok"
    assert reply.output == Answer(value="42")
    assert (reply.model, reply.request_id, reply.stop_reason) == ("claude-sonnet-5-5", "req_test", "end_turn")
    assert reply.usage == TokenUsage(input_tokens=3_000, output_tokens=1_200, cache_write_5m_tokens=2_500)
    assert reply.cost_microusd == 24_250

    request = api.requests[-1]
    assert request.url.path == "/v1/messages"
    assert request.headers["anthropic-version"] == "2026-10-21"
    assert claude.FALLBACK_BETA in request.headers["anthropic-beta"]
    body = api.sent
    assert body["model"] == "claude-sonnet-5-5"
    assert body["max_tokens"] == 8_000
    assert body["fallbacks"] == "default"
    assert body["output_config"]["effort"] == "low"
    schema = body["output_config"]["format"]["schema"]
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {"value"}
    assert body["system"] == [{"type": "text", "text": "Rules.", "cache_control": {"type": "ephemeral"}}]
    assert body["messages"] == [{"role": "user", "content": "Document lines."}]
    # Sampling parameters are gone on API version 2026-10-21; thinking stays adaptive.
    assert not {"temperature", "top_p", "top_k", "thinking", "tools", "tool_choice"} & set(body)


def test_haiku_gets_no_fallback() -> None:
    api = FakeApi(_message(model="claude-haiku-5-5"))
    _ask(_anthropic_claude(api, model="claude-haiku-5-5"))
    assert "fallbacks" not in api.sent
    assert "anthropic-beta" not in api.requests[-1].headers


def test_bedrock_request_uses_the_prefixed_model_and_no_fallback() -> None:
    api = FakeApi(_message())
    sdk = anthropic.AnthropicBedrockMantle(
        aws_region="us-east-1", aws_access_key="AKIDEXAMPLE", aws_secret_key="not-a-real-secret",
        http_client=api.http_client(), max_retries=0,
    )
    reply = SdkClaude(sdk, provider="bedrock", model="claude-sonnet-5-5", effort="low").structured(
        system="Rules.", content="Document lines.", output_type=Answer, max_tokens=8_000
    )
    assert reply.outcome == "ok"
    request = api.requests[-1]
    assert request.url.host == "bedrock-mantle.us-east-1.api.aws"
    assert request.headers["authorization"].startswith("AWS4-HMAC-SHA256 ")  # SigV4, no API key
    assert api.sent["model"] == "anthropic.claude-sonnet-5-5"
    assert "fallbacks" not in api.sent
    assert "anthropic-beta" not in request.headers


def test_refusal_gives_no_output() -> None:
    api = FakeApi(_message(text="", stop_reason="refusal",
                           stop_details={"type": "refusal", "category": "cyber", "explanation": None}))
    reply = _ask(_anthropic_claude(api))
    assert (reply.outcome, reply.output, reply.refusal_category) == ("refused", None, "cyber")
    assert reply.cost_microusd == 1_000 * 2 + 200 * 10


def test_cut_off_reply_gives_no_output() -> None:
    reply = _ask(_anthropic_claude(FakeApi(_message(text='{"value": "4', stop_reason="max_tokens"))))
    assert (reply.outcome, reply.output) == ("incomplete", None)


@pytest.mark.parametrize("text", ["not json", '{"value": "far too long for ten"}', '{"value": "1", "bounding_box": [0, 0]}'])
def test_reply_that_breaks_the_model_is_invalid(text: str) -> None:
    reply = _ask(_anthropic_claude(FakeApi(_message(text=text))))
    assert (reply.outcome, reply.output) == ("invalid", None)
    assert reply.cost_microusd is not None  # a bad reply is still billed and still counted


def test_fallback_is_priced_per_model() -> None:
    # Claude Sonnet 5.5 declined; the server-side fallback served the reply on Claude Sonnet 5.
    api = FakeApi(_message(model="claude-sonnet-5", usage={
        "input_tokens": 2_000, "output_tokens": 300,
        "iterations": [
            {"type": "message", "model": "claude-sonnet-5-5", "input_tokens": 1_000, "output_tokens": 100,
             "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
            {"type": "fallback_message", "model": "claude-sonnet-5", "input_tokens": 1_000, "output_tokens": 200,
             "cache_read_input_tokens": 1_000, "cache_creation_input_tokens": 0},
        ],
    }))
    reply = _ask(_anthropic_claude(api))
    assert reply.outcome == "ok"
    assert reply.model == "claude-sonnet-5"
    assert reply.usage == TokenUsage(input_tokens=2_000, output_tokens=300, cache_read_tokens=1_000)
    # Sonnet 5.5: 1,000 x 2 + 100 x 10 = 3,000. Sonnet 5: 1,000 x 2 + 200 x 10 + 1,000 x 0.20 = 4,200.
    assert reply.cost_microusd == 7_200


def test_unpriced_served_model_keeps_the_reply(caplog: pytest.LogCaptureFixture) -> None:
    reply = _ask(_anthropic_claude(FakeApi(_message(model="claude-future-1"))))
    assert reply.outcome == "ok"
    assert reply.cost_microusd is None
    assert "claude-future-1" in caplog.text


# --- secrets ---------------------------------------------------------------------------------


def test_key_and_prompt_never_reach_the_logs(caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", TEST_KEY)
    caplog.set_level(logging.DEBUG)  # root at DEBUG; the adapter keeps the SDK's logger at INFO
    settings = Settings()
    assert get_claude(settings) is not None
    for body in (_message(), _message(text="not json"), _message(model="claude-future-1")):
        _ask(_anthropic_claude(FakeApi(body)))
    logging.getLogger(claude.__name__).info("settings %s %r", settings, settings)
    assert "api.anthropic.com" in caplog.text  # the HTTP layer's request line was captured
    assert TEST_KEY not in caplog.text
    assert "Document lines." not in caplog.text and "Rules." not in caplog.text
    # The SDK logs whole request bodies at DEBUG; that logger stays at INFO.
    assert logging.getLogger("anthropic").getEffectiveLevel() == logging.INFO
