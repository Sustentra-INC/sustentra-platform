"""CLI guards, the end-to-end rule-reader run on a synthetic log, and AI record/replay."""

import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from backend.app.adapters.llm.base import StructuredReply, TokenUsage
from backend.tools.accuracy import cli
from backend.tools.accuracy.ai_replay import RecordingClaude, ReplayClaude, request_key

LOG = (
    "Date,Hours Run,Fuel Added (gal),Fuel Type,Operator\n"
    "03/05/2031,1.5,10.0,Diesel,A. Operator\n"
    "03/12/2031,2.0,3.5,Diesel,A. Operator\n"
)
KEY = (
    "filename,facility,document_type,field,expected_value,unit,page\n"
    "synthetic_log.csv,Plant Z,Generator run log (CSV),[row 2 03/05/2031] fuel added,10.0,gal,line 2\n"
    "synthetic_log.csv,Plant Z,Generator run log (CSV),[row 3 03/12/2031] fuel added,99.0,gal,line 3\n"
)


def test_refuses_paths_inside_the_repo(tmp_path: Path) -> None:
    inside = cli.REPO_ROOT / "backend"
    assert cli.is_inside_repo(inside)
    with pytest.raises(SystemExit, match="inside the repository"):
        cli.refuse_inside_repo(inside, "the documents folder")
    cli.refuse_inside_repo(tmp_path, "the output folder")  # outside: fine


def test_main_refuses_a_documents_folder_in_the_repo(tmp_path: Path) -> None:
    key = tmp_path / "key.csv"
    key.write_text(KEY, encoding="utf-8")
    with pytest.raises(SystemExit):
        cli.main(["--set", "S", str(cli.REPO_ROOT / "backend"), str(key), "--out", str(tmp_path / "out")])


def test_end_to_end_rules_only_on_a_synthetic_log(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "synthetic_log.csv").write_text(LOG, encoding="utf-8")
    key = tmp_path / "key.csv"
    key.write_text(KEY, encoding="utf-8")
    out = tmp_path / "out"
    baseline = tmp_path / "baseline.json"
    assert cli.main(["--set", "S", str(docs), str(key), "--out", str(out), "--write-baseline", str(baseline)]) == 0
    scores = json.loads((out / "accuracy_scores.json").read_text(encoding="utf-8"))
    families = scores["sets"]["S"]["families"]
    assert scores["mode"] == "rules-only"
    # one row read right, one row the key says is 99 (a deliberate disagreement): wrong, and silent
    assert families["activity_quantity"]["match"] == 1 and families["activity_quantity"]["wrong"] == 1
    assert families["activity_quantity"]["silent"] == 1
    report = (out / "accuracy_report.md").read_text(encoding="utf-8")
    assert "activity_quantity" in report and "precision" in report
    counts = json.loads(baseline.read_text(encoding="utf-8"))
    assert "synthetic_log" not in json.dumps(counts) and counts["sets"]["S"]["totals"]["wrong"] == 1


def test_rules_only_is_deterministic(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "synthetic_log.csv").write_text(LOG, encoding="utf-8")
    key = tmp_path / "key.csv"
    key.write_text(KEY, encoding="utf-8")
    runs = []
    for n in (1, 2):
        out = tmp_path / f"out{n}"
        cli.main(["--set", "S", str(docs), str(key), "--out", str(out)])
        runs.append((out / "accuracy_scores.json").read_text(encoding="utf-8"))
    assert runs[0] == runs[1]


class Answer(BaseModel):
    value: str


class FakeClient:
    provider = "anthropic"
    model = "claude-sonnet-5-5"

    def __init__(self) -> None:
        self.calls = 0

    def structured(self, *, system: str, content: object, output_type: type[BaseModel], max_tokens: int) -> StructuredReply:  # type: ignore[type-arg]
        self.calls += 1
        return StructuredReply("ok", output_type(value="42"), self.model, TokenUsage(10, 5), 7, "req-1", "end_turn")


def test_ai_replies_are_recorded_once_then_replayed_without_the_client(tmp_path: Path) -> None:
    fake = FakeClient()
    recorder = RecordingClaude(fake, tmp_path / "replies")  # type: ignore[arg-type]
    live = recorder.structured(system="s", content="read this", output_type=Answer, max_tokens=100)
    assert fake.calls == 1 and recorder.recorded == 1 and live.output == Answer(value="42")

    replay = ReplayClaude(tmp_path / "replies", model="claude-sonnet-5-5")
    again = replay.structured(system="s", content="read this", output_type=Answer, max_tokens=100)
    assert again.output == Answer(value="42") and again.cost_microusd == 7 and replay.replayed == 1 and replay.misses == []
    assert fake.calls == 1  # replay never reaches the client


def test_replay_miss_is_collected_and_raised(tmp_path: Path) -> None:
    (tmp_path / "replies").mkdir()
    replay = ReplayClaude(tmp_path / "replies", model="claude-sonnet-5-5")
    with pytest.raises(LookupError, match="re-record"):
        replay.structured(system="s", content="never recorded", output_type=Answer, max_tokens=100)
    assert len(replay.misses) == 1


def test_request_key_depends_on_every_part() -> None:
    base = request_key("m", "sys", "text", Answer)
    assert base == request_key("m", "sys", "text", Answer)
    assert len({base, request_key("m2", "sys", "text", Answer), request_key("m", "sys2", "text", Answer),
                request_key("m", "sys", "text2", Answer)}) == 4
