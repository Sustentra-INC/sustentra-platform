"""Condition/applicability evaluator for Subsystem 2 PR6."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

ConditionStatus = Literal[
    "applicable",
    "not_applicable",
    "unknown",
    "unsupported_condition",
]

TOKEN_PATTERN = re.compile(
    r"\s*(?:(AND|OR|IN)\b|([A-Za-z][A-Za-z0-9_-]*)|('[^']*'|\"[^\"]*\"|[^(),=\s]+)|(=)|(\()|(\))|(,))",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ConditionEvaluationResult:
    status: ConditionStatus
    condition: str | None
    reason: str | None = None


class ConditionEvaluator:
    """Evaluates a safe subset of methodology row conditions.

    Supported grammar:

    - `FIELD_ID = value`
    - `FIELD_ID IN (a, b, c)`
    - `AND`
    - `OR`
    - simple parentheses
    """

    def evaluate(
        self,
        condition: str | None,
        values: dict[str, Any],
    ) -> ConditionEvaluationResult:
        if not condition or not str(condition).strip():
            return ConditionEvaluationResult(
                status="applicable",
                condition=condition,
                reason="blank condition",
            )
        try:
            tokens = _tokenize(str(condition))
            parser = _Parser(tokens, values)
            result = parser.parse_expression()
            parser.expect_end()
        except _UnsupportedCondition as exc:
            return ConditionEvaluationResult(
                status="unsupported_condition",
                condition=condition,
                reason=str(exc),
            )
        except _UnknownCondition as exc:
            return ConditionEvaluationResult(
                status="unknown",
                condition=condition,
                reason=str(exc),
            )

        return ConditionEvaluationResult(
            status="applicable" if result else "not_applicable",
            condition=condition,
            reason=None,
        )


class _UnsupportedCondition(ValueError):
    pass


class _UnknownCondition(ValueError):
    pass


@dataclass(frozen=True)
class _Token:
    kind: str
    value: str


def _tokenize(condition: str) -> tuple[_Token, ...]:
    tokens: list[_Token] = []
    position = 0
    while position < len(condition):
        match = TOKEN_PATTERN.match(condition, position)
        if match is None:
            raise _UnsupportedCondition(
                f"Unsupported condition syntax near: {condition[position:]}"
            )
        position = match.end()
        keyword, identifier, literal, equals, left, right, comma = match.groups()
        if keyword:
            tokens.append(_Token(keyword.upper(), keyword.upper()))
        elif identifier:
            tokens.append(_Token("IDENT", identifier))
        elif literal:
            tokens.append(_Token("VALUE", _strip_quotes(literal)))
        elif equals:
            tokens.append(_Token("=", equals))
        elif left:
            tokens.append(_Token("(", left))
        elif right:
            tokens.append(_Token(")", right))
        elif comma:
            tokens.append(_Token(",", comma))
    return tuple(tokens)


def _strip_quotes(value: str) -> str:
    if (value.startswith("'") and value.endswith("'")) or (
        value.startswith('"') and value.endswith('"')
    ):
        return value[1:-1]
    return value


class _Parser:
    def __init__(self, tokens: tuple[_Token, ...], values: dict[str, Any]) -> None:
        self._tokens = tokens
        self._values = values
        self._index = 0

    def parse_expression(self) -> bool:
        result = self.parse_term()
        while self._peek("OR"):
            self._consume("OR")
            result = result or self.parse_term()
        return result

    def parse_term(self) -> bool:
        result = self.parse_factor()
        while self._peek("AND"):
            self._consume("AND")
            result = result and self.parse_factor()
        return result

    def parse_factor(self) -> bool:
        if self._peek("("):
            self._consume("(")
            result = self.parse_expression()
            self._consume(")")
            return result
        return self.parse_comparison()

    def parse_comparison(self) -> bool:
        field = self._consume("IDENT").value
        if self._peek("="):
            self._consume("=")
            expected = self._consume_value().value
            return _normalize_value(self._lookup(field)) == _normalize_value(expected)
        if self._peek("IN"):
            self._consume("IN")
            self._consume("(")
            expected_values = [self._consume_value().value]
            while self._peek(","):
                self._consume(",")
                expected_values.append(self._consume_value().value)
            self._consume(")")
            actual = _normalize_value(self._lookup(field))
            return actual in {_normalize_value(value) for value in expected_values}
        raise _UnsupportedCondition(
            f"Expected '=' or 'IN' after condition field '{field}'."
        )

    def expect_end(self) -> None:
        if self._index != len(self._tokens):
            token = self._tokens[self._index]
            raise _UnsupportedCondition(
                f"Unexpected token '{token.value}' at end of condition."
            )

    def _lookup(self, field: str) -> Any:
        if field not in self._values or self._values[field] is None:
            raise _UnknownCondition(f"Missing runtime value for '{field}'.")
        return self._values[field]

    def _consume_value(self) -> _Token:
        if self._peek("IDENT"):
            return self._consume("IDENT")
        return self._consume("VALUE")

    def _peek(self, kind: str) -> bool:
        return self._index < len(self._tokens) and self._tokens[self._index].kind == kind

    def _consume(self, kind: str) -> _Token:
        if not self._peek(kind):
            actual = self._tokens[self._index].value if self._index < len(self._tokens) else "EOF"
            raise _UnsupportedCondition(f"Expected {kind}, found '{actual}'.")
        token = self._tokens[self._index]
        self._index += 1
        return token


def _normalize_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip().casefold()
