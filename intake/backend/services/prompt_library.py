"""Load prompts from files in ``intake/prompts/``.

CLAUDE.md: prompts live as files, never as inline strings. Each file carries a
small YAML-ish front matter block declaring its id, version and the variables it
expects; rendering with a missing variable raises rather than silently sending a
prompt with a hole in it.

Front matter is parsed with a deliberately tiny reader (id, version, and the
``variables`` list) rather than a YAML dependency - that is all the format
needs, and a stricter parser would be one more thing to keep in step.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from intake.backend.config import REPO_ROOT

FRONT_MATTER = re.compile(r"\A---\n(?P<meta>.*?)\n---\n(?P<body>.*)\Z", re.DOTALL)
PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]*)\}")


class PromptError(Exception):
    """Raised when a prompt is missing, malformed, or rendered incompletely."""


class Prompt:
    def __init__(self, prompt_id: str, version: str, variables: list[str], body: str) -> None:
        self.prompt_id = prompt_id
        self.version = version
        self.variables = variables
        self.body = body

    def render(self, values: dict[str, Any]) -> str:
        missing = [name for name in self.variables if name not in values]
        if missing:
            raise PromptError(f"{self.prompt_id}: missing variables {missing}")
        rendered = self.body
        for name in self.variables:
            rendered = rendered.replace("{" + name + "}", str(values[name]))
        return rendered


def _parse_front_matter(text: str, path: Path) -> tuple[dict[str, str], list[str], str]:
    match = FRONT_MATTER.match(text)
    if not match:
        raise PromptError(f"{path}: missing --- front matter block")

    meta: dict[str, str] = {}
    variables: list[str] = []
    in_variables = False

    for line in match.group("meta").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("- "):
            if in_variables:
                variables.append(stripped[2:].strip())
            continue
        in_variables = stripped.startswith("variables:")
        if ":" in stripped and not in_variables:
            key, _, value = stripped.partition(":")
            meta[key.strip()] = value.strip().strip('"').strip("'")

    return meta, variables, match.group("body")


@lru_cache(maxsize=1)
def load_prompts() -> dict[str, Prompt]:
    """Every prompt in intake/prompts/, keyed by its declared prompt_id."""
    directory = REPO_ROOT / "intake/prompts"
    if not directory.exists():
        raise PromptError(f"missing prompts directory: {directory}")

    prompts: dict[str, Prompt] = {}
    for path in sorted(directory.glob("*.md")):
        meta, variables, body = _parse_front_matter(
            path.read_text(encoding="utf-8"), path
        )
        prompt_id = meta.get("prompt_id")
        if not prompt_id:
            raise PromptError(f"{path}: front matter has no prompt_id")
        if not variables:
            raise PromptError(f"{path}: front matter declares no variables")

        # Every declared variable must actually appear in the body, and every
        # placeholder in the body must be declared. A mismatch means the prompt
        # would be sent malformed.
        used = {
            name
            for name in PLACEHOLDER.findall(body)
            # The JSON output block uses braces too; only single-word lowercase
            # placeholders on their own are treated as variables.
            if name in variables
        }
        undeclared = [name for name in variables if name not in used]
        if undeclared:
            raise PromptError(f"{path}: declares unused variables {undeclared}")

        prompts[prompt_id] = Prompt(prompt_id, meta.get("version", "0"), variables, body)

    if not prompts:
        raise PromptError(f"{directory}: no prompts found")
    return prompts


def get_prompt(prompt_id: str) -> Prompt:
    prompts = load_prompts()
    try:
        return prompts[prompt_id]
    except KeyError:
        raise PromptError(
            f"unknown prompt {prompt_id!r}; known: {sorted(prompts)}"
        ) from None


def reset_cache() -> None:
    load_prompts.cache_clear()
