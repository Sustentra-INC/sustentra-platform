"""The reader on the app host: its compose service, and the deploy script that releases it.

``deploy/docker-compose.prod.yml`` gets a ``reader`` service (the api image running the reader
process), and ``deploy/deploy.sh`` validates ``S1_PROCESSING``, writes it into ``app.env``, and
waits for the reader's container health check before it calls a release healthy.

The script tests run real ``bash`` on pieces of ``deploy.sh`` (functions cut out with ``sed``) or on
a copy of the whole script pointed at a temporary directory, with ``aws``, ``docker``, ``curl`` and
``install`` replaced by stubs on ``PATH``. Nothing talks to a real host.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from backend.app.core.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "deploy" / "docker-compose.prod.yml"
DEPLOY_SCRIPT = REPO_ROOT / "deploy" / "deploy.sh"


def _services() -> dict[str, dict[str, Any]]:
    return yaml.safe_load(COMPOSE_FILE.read_text())["services"]


def _grace_seconds(value: str) -> int:
    assert value.endswith("s"), value
    return int(value.removesuffix("s"))


def _extract(*patterns: str) -> str:
    """The lines of deploy.sh that ``sed -n`` selects with ``patterns`` (``p;``-joined)."""

    result = subprocess.run(
        ["sed", "-n", ";".join(patterns), str(DEPLOY_SCRIPT)], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip(), f"sed found nothing for {patterns}"
    return result.stdout


def _write_stub(directory: Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _plain_env(stubs: Path | None = None, **variables: str) -> dict[str, str]:
    """A bare environment: the system PATH (stubs first), and only the variables the case sets."""

    path = os.environ["PATH"] if stubs is None else f"{stubs}{os.pathsep}{os.environ['PATH']}"
    return {"PATH": path, **variables}


# --- the compose service ---------------------------------------------------------------------


def test_the_reader_runs_the_api_image_with_the_api_settings() -> None:
    services = _services()
    reader, api = services["reader"], services["api"]

    assert reader["image"] == "${API_IMAGE:?}:${API_TAG:-latest}"
    assert reader["image"] == api["image"]
    assert reader["command"] == ["python", "-m", "backend.app.workers.processing_reader"]
    assert reader["env_file"] == ["app.env"]
    assert reader["environment"] == {"AWS_REGION": "${AWS_REGION}"}
    assert reader["init"] is True
    # The hardening anchor reaches the reader through the merge key.
    assert reader["read_only"] is True
    assert reader["cap_drop"] == ["ALL"]
    assert reader["restart"] == "unless-stopped"
    assert reader["mem_limit"] == "768m"
    assert "/opt/sustentra/data:/app/data" in reader["volumes"]
    assert reader["tmpfs"] == ["/tmp"]  # the file cache and the alive file the health check reads
    assert _grace_seconds(reader["stop_grace_period"]) == 60
    health = reader["healthcheck"]
    assert health["test"] == ["CMD", "python", "-m", "backend.app.workers.reader_health"]
    assert (health["interval"], health["timeout"], health["start_period"], health["retries"]) == ("15s", "5s", "20s", 3)
    # Logs go to the api's existing group (the awslogs driver won't start into a missing group).
    group = reader["logging"]["options"]["awslogs-group"]
    assert group.endswith("/api")
    assert group == api["logging"]["options"]["awslogs-group"]
    assert reader["logging"]["options"]["tag"] == "{{.Name}}"


def test_the_reader_stops_after_its_grace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("S1_READER_SHUTDOWN_GRACE_SECONDS", raising=False)
    grace = Settings().s1_reader_shutdown_grace_seconds
    assert grace == 45
    assert _grace_seconds(_services()["reader"]["stop_grace_period"]) > grace


# --- deploy.sh: S1_PROCESSING ------------------------------------------------------------------


def test_deploy_writes_s1_processing_into_app_env() -> None:
    lines = DEPLOY_SCRIPT.read_text().splitlines()
    heredoc = lines[lines.index("TEXTRACT_ENABLED=${TEXTRACT_ENABLED:-false}") :]
    # Right after TEXTRACT_ENABLED, still inside write_app_env's heredoc (which ends at EOF).
    assert heredoc[1] == "S1_PROCESSING=${S1_PROCESSING:-inline}"
    assert heredoc[2] == "EOF"


@pytest.mark.parametrize(
    ("variables", "exit_code", "stderr_has"),
    [
        ({"S1_PROCESSING": "queued", "S1_STORE": "jsonl"}, 1, "needs S1_STORE"),
        ({"S1_PROCESSING": "queued"}, 1, "needs S1_STORE"),  # S1_STORE unset means jsonl
        ({"S1_PROCESSING": "queued", "S1_STORE": "postgres+jsonl"}, 0, ""),
        ({"S1_PROCESSING": "queued", "S1_STORE": "postgres"}, 0, ""),
        ({}, 0, ""),  # unset means inline
        ({"S1_STORE": "jsonl"}, 0, ""),
        ({"S1_PROCESSING": "inline", "S1_STORE": "jsonl"}, 0, ""),
        ({"S1_PROCESSING": "fast"}, 1, "must be inline or queued, not 'fast'"),
        ({"S1_PROCESSING": "Queued", "S1_STORE": "postgres"}, 1, "must be inline or queued"),
    ],
)
def test_deploy_refuses_queued_without_postgres_stores(
    variables: dict[str, str], exit_code: int, stderr_has: str
) -> None:
    extracted = _extract("/^log()/p", "/^check_processing_mode()/,/^}/p")
    # The extract ends in a newline: join with one, or `; check_processing_mode` is a syntax error.
    script = f"set -euo pipefail\n{extracted}\ncheck_processing_mode\n"
    result = subprocess.run(
        ["bash", "-c", script],
        env=_plain_env(APP_DIR="/opt/sustentra", **variables),
        capture_output=True,
        text=True,
    )
    assert result.returncode == exit_code, result.stderr
    assert stderr_has in result.stderr
    assert result.stdout == ""  # the refusal is on stderr, so a caller capturing stdout never sees it


def _env_text(env_lines: list[str]) -> str:
    """The host's /opt/sustentra/.env for a case: the required variables plus the case's own lines."""

    required = ["API_IMAGE=x", "WEB_IMAGE=x", "APP_DOMAIN=x", "AWS_REGION=us-east-1", "ECR_REGISTRY=x"]
    return "\n".join([*required, *env_lines]) + "\n"


def _run_whole_script(tmp_path: Path, env_lines: list[str]) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    """Run a copy of deploy.sh (APP_DIR pointed at tmp_path) to its first outside call.

    The stubs record every call and the ``aws ecr get-login-password`` stub stops the run with
    exit code 3, so a run that gets past the S1_PROCESSING check ends at the ECR login, before
    anything is pulled or written.
    """

    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / ".env").write_text(_env_text(env_lines))
    script = tmp_path / "deploy.sh"
    script.write_text(DEPLOY_SCRIPT.read_text().replace("APP_DIR=/opt/sustentra\n", f"APP_DIR={app_dir}\n", 1))
    assert str(app_dir) in script.read_text()

    stubs = tmp_path / "stubs"
    stubs.mkdir()
    calls = tmp_path / "calls.log"
    _write_stub(stubs, "aws", f'echo "aws $*" >> "{calls}"\n[ "$1 $2" = "ecr get-login-password" ] && exit 3\nexit 9\n')
    # `docker login` reads the token from the pipe and succeeds, so the pipeline's status is aws's 3.
    login_ok = '[ "$1" = login ] && { cat > /dev/null; exit 0; }'
    _write_stub(stubs, "docker", f'echo "docker $*" >> "{calls}"\n{login_ok}\nexit 9\n')
    for name in ("curl", "install"):
        _write_stub(stubs, name, f'echo "{name} $*" >> "{calls}"\nexit 9\n')
    result = subprocess.run(
        ["bash", str(script), "staging", "newtag"], env=_plain_env(stubs), capture_output=True, text=True
    )
    return result, app_dir, calls


@pytest.mark.parametrize(
    "env_lines",
    [
        ["S1_PROCESSING=queued", "S1_STORE=jsonl"],
        ["S1_PROCESSING=queued"],
        ["S1_PROCESSING=fast", "S1_STORE=postgres"],
    ],
)
def test_a_bad_processing_mode_stops_the_deploy_before_anything_is_touched(tmp_path: Path, env_lines: list[str]) -> None:
    result, app_dir, calls = _run_whole_script(tmp_path, env_lines)

    assert result.returncode == 1, result.stderr
    assert "S1_PROCESSING" in result.stderr
    assert not calls.exists()  # no aws, no docker, no install: nothing pulled, restarted or written
    assert not (app_dir / "app.env").exists()
    # The deploy would append LOG_GROUP_PREFIX (and rewrite the tags) in .env: it is as it was.
    assert (app_dir / ".env").read_text() == _env_text(env_lines)


@pytest.mark.parametrize(
    "env_lines",
    [[], ["S1_PROCESSING=inline", "S1_STORE=jsonl"], ["S1_PROCESSING=queued", "S1_STORE=postgres+jsonl"]],
)
def test_a_good_processing_mode_lets_the_deploy_start(tmp_path: Path, env_lines: list[str]) -> None:
    # The check runs after log() exists: called earlier, `set -e` would end every deploy here.
    result, app_dir, calls = _run_whole_script(tmp_path, env_lines)

    assert result.returncode == 3, result.stderr  # stopped by the ECR login stub, the first call out
    assert "command not found" not in result.stderr
    # Only the two ends of the login pipeline ran (in either order: they run side by side).
    assert set(calls.read_text().splitlines()) == {
        "aws ecr get-login-password --region us-east-1",
        "docker login --username AWS --password-stdin x",
    }
    assert not (app_dir / "app.env").exists()


# --- deploy.sh: the reader in the health check -------------------------------------------------


def test_deploy_waits_for_a_healthy_reader() -> None:
    text = DEPLOY_SCRIPT.read_text()
    assert "\nreader_healthy() {" in text
    healthy = text[text.index("\nhealthy() {") :].split("\n}\n", 1)[0]
    assert "reader_healthy" in healthy
    assert "api/health" in healthy
    # The failure report covers the reader's output too.
    assert "logs --tail 50 caddy api web reader" in text


# What `docker inspect` prints for the reader (None: the reader has no container), and whether
# the api answers: the release is healthy only when the api answers and the reader is healthy.
@pytest.mark.parametrize(
    ("reader_status", "api_answers", "healthy"),
    [
        ("healthy", True, True),
        ("starting", True, False),
        ("unhealthy", True, False),
        ("none", True, False),  # no health check defined on the container
        (None, True, False),  # no reader container
        ("healthy", False, False),
        (None, False, False),
    ],
)
def test_the_release_is_healthy_only_when_the_api_answers_and_the_reader_is_healthy(
    tmp_path: Path, reader_status: str | None, api_answers: bool, healthy: bool
) -> None:
    functions = _extract("/^log()/p", "/^reader_healthy()/,/^}/p", "/^healthy()/,/^}/p")
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    # `docker compose ... ps -q reader` prints the container id (nothing when there is none);
    # `docker inspect ...` prints the health status.
    ps_output = 'echo reader-id' if reader_status is not None else "true"
    _write_stub(
        stubs,
        "docker",
        f'if [ "$1" = compose ]; then {ps_output}; exit 0; fi\n'
        f'if [ "$1" = inspect ]; then echo "{reader_status}"; exit 0; fi\nexit 9\n',
    )
    _write_stub(stubs, "curl", f"exit {0 if api_answers else 22}\n")
    script = (
        "set -euo pipefail\n"
        "COMPOSE=(docker compose -f x.yml)\n"
        "APP_DOMAIN=app.example.com HEALTH_ATTEMPTS=2 HEALTH_DELAY=0\n"
        f"{functions}\n"
        "healthy\n"
    )
    result = subprocess.run(["bash", "-c", script], env=_plain_env(stubs), capture_output=True, text=True)

    assert (result.returncode == 0) == healthy, result.stdout + result.stderr
    assert ("health check passed" in result.stdout) == healthy
