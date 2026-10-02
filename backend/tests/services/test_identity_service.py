from datetime import datetime, timezone
from pathlib import Path

from backend.app.repositories.identity_repository import IdentityRepository
from backend.app.services.identity_service import IdentityService


def test_jsonl_identity_works_without_database(tmp_path: Path):
    repo = IdentityRepository.jsonl(tmp_path / "identity")
    service = IdentityService(
        repository=repo,
        clock=lambda: datetime(2026, 9, 17, tzinfo=timezone.utc),
        return_dev_tokens=True,
    )
    created = service.create_sustentra_user(
        username="admin",
        email="admin@sustentra.local",
        password="password123",
    )
    assert created["user_id"].startswith("usr_")
    assert (tmp_path / "identity" / "users.jsonl").exists()

    restarted = IdentityService(
        repository=IdentityRepository.jsonl(tmp_path / "identity"),
        clock=lambda: datetime(2026, 9, 17, 1, tzinfo=timezone.utc),
        return_dev_tokens=True,
    )
    session = restarted.login("admin", "password123")
    assert session["token"]
    assert restarted.status()["persistence"] == "jsonl"
    assert restarted.status()["bootstrap_required"] is False
