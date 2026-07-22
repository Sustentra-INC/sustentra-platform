from pathlib import Path

import pytest

from backend.scripts.generate_synthetic_evidence import (
    DEFAULT_LINES,
    generate_synthetic_evidence,
)


def test_creates_synthetic_file(tmp_path: Path) -> None:
    path = generate_synthetic_evidence(
        output_dir=tmp_path,
        file_name="synthetic.txt",
    )

    assert path.exists()
    assert path.is_file()


def test_does_not_overwrite_by_default(tmp_path: Path) -> None:
    path = generate_synthetic_evidence(
        output_dir=tmp_path,
        file_name="synthetic.txt",
    )
    original = path.read_text(encoding="utf-8")

    with pytest.raises(FileExistsError):
        generate_synthetic_evidence(
            output_dir=tmp_path,
            file_name="synthetic.txt",
            overwrite=False,
        )

    assert path.read_text(encoding="utf-8") == original


def test_overwrites_when_overwrite_passed(tmp_path: Path) -> None:
    path = generate_synthetic_evidence(
        output_dir=tmp_path,
        file_name="synthetic.txt",
        lines=["Old line"],
    )
    assert "Old line" in path.read_text(encoding="utf-8")

    generate_synthetic_evidence(
        output_dir=tmp_path,
        file_name="synthetic.txt",
        overwrite=True,
        lines=["New line"],
    )

    assert path.read_text(encoding="utf-8") == "New line\n"


def test_uses_fake_expected_content(tmp_path: Path) -> None:
    path = generate_synthetic_evidence(
        output_dir=tmp_path,
        file_name="synthetic.txt",
    )
    text = path.read_text(encoding="utf-8")

    for line in DEFAULT_LINES:
        assert line in text


def test_creates_parent_directory(tmp_path: Path) -> None:
    output_dir = tmp_path / "nested" / "generated"
    path = generate_synthetic_evidence(
        output_dir=output_dir,
        file_name="synthetic.txt",
    )

    assert output_dir.exists()
    assert path.exists()
