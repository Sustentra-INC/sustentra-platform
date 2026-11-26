"""How a failed Claude call in Methodology review is classified."""

from __future__ import annotations

import logging

import anthropic
import httpx2
import pytest

from backend.app.adapters.llm._claude_sdk import _translate
from backend.app.api import methodology_review as api


def _status_error(status: int, message: str = "schema too complex") -> anthropic.APIStatusError:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx2.Response(status, request=request, json={"type": "error", "error": {
        "type": "invalid_request_error", "message": message}})
    return anthropic.APIStatusError(message, response=response, body=response.json())


@pytest.mark.parametrize("status,rejected", [(400, True), (422, True), (429, False), (500, False), (529, False)])
def test_only_400_and_422_are_configuration_failures(status: int, rejected: bool) -> None:
    assert api._is_request_rejected(_translate(_status_error(status))) is rejected


def test_network_and_timeout_errors_are_not_configuration_failures() -> None:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    assert not api._is_request_rejected(_translate(anthropic.APITimeoutError(request=request)))
    assert not api._is_request_rejected(_translate(anthropic.APIConnectionError(request=request)))


def test_the_log_has_status_provider_type_and_message(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=api.logger.name):
        api._log_call_failure(_translate(_status_error(400, "too many union types")))
    text = caplog.text
    assert "APIStatusError" in text and "status=400" in text
    assert "error_type=invalid_request_error" in text and "too many union types" in text


def test_the_response_reason_is_short_and_has_no_keys() -> None:
    text = api._reason(_translate(_status_error(401, "invalid x-api-key sk-ant-api03-abcdefghijklmnop " + "x" * 300)))
    assert text.startswith("invalid_request_error:") and "sk-ant" not in text and len(text) <= 150
    assert api._reason(_translate(_status_error(400, "Your credit balance is too low"))).startswith("billing:")
    assert api._reason(RuntimeError("boom")) == "RuntimeError"
