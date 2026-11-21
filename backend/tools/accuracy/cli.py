"""Accuracy harness CLI.

    python -m backend.tools.accuracy                       # STG, NPL and LHF found in ~/Downloads, rules only
    python -m backend.tools.accuracy --downloads DIR --out DIR2
    python -m backend.tools.accuracy --set NAME DOCS_DIR KEY_CSV   # any other set (repeatable)
    python -m backend.tools.accuracy --ai-record DIR      # real Claude, replies saved (needs credentials)
    python -m backend.tools.accuracy --ai-replay DIR      # recorded replies, no network, deterministic
    python -m backend.tools.accuracy --write-baseline backend/tests/data/accuracy-baseline.json

Documents, keys, reports and recorded replies stay outside the repository: every such path is refused
if it is inside it. The only file this tool writes into the repo is the baseline, and that holds
aggregate counts only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from backend.app.services.pipeline_orchestration_service import PipelineOrchestrationService
from backend.tools.accuracy.ai_replay import RecordingClaude, ReplayClaude
from backend.tools.accuracy.keys import KeyCell, read_key
from backend.tools.accuracy.report import baseline_payload, render_markdown, render_table, summarize_set
from backend.tools.accuracy.runner import build_service, run_folder
from backend.tools.accuracy.scorer import SetScorer

REPO_ROOT = Path(__file__).resolve().parents[3]

# Where the three sets live in the downloads folder: (label, documents folder, answer key).
KNOWN_SETS = (
    ("STG", "STG_GHG_Test_Set", "STG_answer_key.csv"),
    ("NPL", "NPL_Test_Documents", "NPL_Answer_Key.csv"),
    ("LHF", "LHF_Demo_Set_v2", "LHF_Answer_Key.csv"),
)


def is_inside_repo(path: Path) -> bool:
    return path.resolve().is_relative_to(REPO_ROOT)


def refuse_inside_repo(path: Path, what: str) -> None:
    if is_inside_repo(path):
        raise SystemExit(f"refusing to use {what} inside the repository ({path}): test data never goes in the repo")


def discover_sets(downloads: Path) -> list[tuple[str, Path, Path]]:
    found: list[tuple[str, Path, Path]] = []
    for label, folder, key in KNOWN_SETS:
        docs, csv_path = downloads / folder, downloads / key
        if docs.is_dir() and csv_path.is_file():
            found.append((label, docs, csv_path))
        else:
            print(f"{label}: not found in {downloads} (looked for {folder} and {key}); skipped", file=sys.stderr)
    return found


def score_set(label: str, docs_dir: Path, key_path: Path, service: PipelineOrchestrationService, org_id: str | None) -> dict[str, Any]:
    cells: list[KeyCell] = read_key(key_path, label)
    keyed = {c.filename for c in cells}
    keyed_files = keyed & {p.name for p in docs_dir.iterdir() if p.is_file()}
    docs = run_folder(docs_dir, service, org_id, only=keyed_files)
    scorer = SetScorer(label, cells, docs)
    outcomes = scorer.score()
    return summarize_set(
        label, outcomes,
        documents_in_folder=sum(1 for p in docs_dir.iterdir() if p.is_file() and not p.name.startswith(".")),
        documents_keyed=len(keyed), documents_not_found=len(keyed - keyed_files),
        extracted_unscored=dict(scorer.extracted_unscored), unmapped_labels=dict(scorer.unmapped_labels),
    )


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m backend.tools.accuracy", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--downloads", type=Path, default=Path.home() / "Downloads",
                        help="folder holding the STG, NPL and LHF documents and keys (default ~/Downloads)")
    parser.add_argument("--set", dest="sets", nargs=3, action="append", metavar=("NAME", "DOCS_DIR", "KEY_CSV"),
                        help="score this set instead of the downloads folder's (repeatable)")
    parser.add_argument("--only", action="append", default=None, metavar="NAME", help="score only this set (repeatable)")
    parser.add_argument("--out", type=Path, default=Path.home() / ".cache" / "sustentra-accuracy",
                        help="where accuracy_scores.json and accuracy_report.md go (outside the repo)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--rules-only", action="store_true", help="rule readers only: free, offline, deterministic (default)")
    mode.add_argument("--ai-replay", type=Path, metavar="DIR", help="AI on, answered from replies recorded in DIR")
    mode.add_argument("--ai-record", type=Path, metavar="DIR", help="AI on, real Claude; replies saved to DIR")
    parser.add_argument("--write-baseline", type=Path, metavar="FILE", help="write aggregate counts only to FILE")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    sets = [(n, Path(d), Path(k)) for n, d, k in args.sets] if args.sets else discover_sets(args.downloads)
    if args.only:
        sets = [s for s in sets if s[0] in args.only]
    if not sets:
        print("no test sets found", file=sys.stderr)
        return 2
    for name, docs, key in sets:
        refuse_inside_repo(docs, f"the {name} documents folder")
        refuse_inside_repo(key, f"the {name} answer key")
    refuse_inside_repo(args.out, "the output folder")
    for directory in (args.ai_replay, args.ai_record):
        if directory is not None:
            refuse_inside_repo(directory, "the AI reply folder")

    client: ReplayClaude | RecordingClaude | None = None
    mode = "rules-only"
    if args.ai_replay is not None or args.ai_record is not None:
        from backend.app.core.config import get_settings
        settings = get_settings()
        if args.ai_replay is not None:
            if not args.ai_replay.is_dir():
                print(f"{args.ai_replay} is not a folder of recorded replies; record first with --ai-record", file=sys.stderr)
                return 2
            client = ReplayClaude(args.ai_replay, model=settings.ai_model, provider=settings.ai_provider)
            mode = "ai-replay"
        else:
            from backend.app.adapters.llm.claude import get_claude
            real = get_claude(settings.model_copy(update={"ai_suggestions_enabled": True}))
            if real is None:
                print("cannot record: no AI credentials configured (ANTHROPIC_API_KEY / Bedrock)", file=sys.stderr)
                return 2
            assert args.ai_record is not None
            client = RecordingClaude(real, args.ai_record)
            mode = "ai-record"

    service, org_id = build_service(client)
    summaries = {name: score_set(name, docs, key, service, org_id) for name, docs, key in sets}

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "accuracy_scores.json").write_text(json.dumps({"mode": mode, "sets": summaries}, indent=1, sort_keys=True),
                                                    encoding="utf-8")
    (args.out / "accuracy_report.md").write_text(render_markdown(summaries, mode), encoding="utf-8")
    if args.write_baseline:
        args.write_baseline.parent.mkdir(parents=True, exist_ok=True)
        args.write_baseline.write_text(json.dumps(baseline_payload(summaries, mode), indent=1, sort_keys=True) + "\n",
                                       encoding="utf-8")
    print(render_table(summaries))
    print(f"Reports written to {args.out}")

    misses = client.misses if isinstance(client, ReplayClaude) else None
    if misses:
        print(f"{len(misses)} AI request(s) had no recorded reply: re-record with --ai-record {args.ai_replay}", file=sys.stderr)
        return 2
    return 0
