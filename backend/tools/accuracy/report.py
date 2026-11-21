"""Aggregate outcomes into per-family scores; render the JSON summary and the Markdown report."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from backend.tools.accuracy.model import MATCH, MISSED, NOT_TARGETED, UNSCORED, WRONG, Outcome

READING = "reading"
PLACEMENT = "placement"
RECOGNITION = "recognition"
GROUPS = {"facility": PLACEMENT, "document_recognition": RECOGNITION, "non_evidence_rejected": RECOGNITION}
COUNT_KEYS = ("scored", "match", "exact", "wrong", "missed", "silent", "not_targeted", "unscored")


def group_of(family: str) -> str:
    return GROUPS.get(family, READING)


def _blank() -> dict[str, int]:
    return dict.fromkeys(COUNT_KEYS, 0)


def tally(outcomes: list[Outcome]) -> dict[str, dict[str, int]]:
    """Counts per family. ``scored`` = match + wrong + missed."""

    families: dict[str, dict[str, int]] = defaultdict(_blank)
    for o in outcomes:
        c = families[o.family]
        if o.status == MATCH:
            c["match"] += 1
            c["scored"] += 1
            c["exact"] += int(o.exact)
        elif o.status == WRONG:
            c["wrong"] += 1
            c["scored"] += 1
            c["silent"] += int(o.silent)
        elif o.status == MISSED:
            c["missed"] += 1
            c["scored"] += 1
        elif o.status == NOT_TARGETED:
            c["not_targeted"] += 1
        elif o.status == UNSCORED:
            c["unscored"] += 1
    return dict(sorted(families.items()))


def totals(families: dict[str, dict[str, int]], group: str | None = None) -> dict[str, int]:
    out = _blank()
    for name, c in families.items():
        if group is not None and group_of(name) != group:
            continue
        for k in COUNT_KEYS:
            out[k] += c[k]
    return out


def rates(c: dict[str, int]) -> dict[str, float | None]:
    given = c["match"] + c["wrong"]
    return {
        # Of the values given, the share right. A value the key does not cover is not in either count.
        "precision": round(c["match"] / given, 4) if given else None,
        # Of the values the key says exist, the share found and right.
        "recall": round(c["match"] / c["scored"], 4) if c["scored"] else None,
        "exact_rate": round(c["exact"] / c["scored"], 4) if c["scored"] else None,
        # Of the wrong values, the share that carried no flag.
        "silent_rate": round(c["silent"] / c["wrong"], 4) if c["wrong"] else None,
    }


def summarize_set(name: str, outcomes: list[Outcome], *, documents_in_folder: int, documents_keyed: int,
                  documents_not_found: int, extracted_unscored: dict[str, int], unmapped_labels: dict[str, int],
                  detail_limit: int = 400) -> dict[str, Any]:
    families = tally(outcomes)
    reasons = Counter(o.reason for o in outcomes if o.status in (UNSCORED, NOT_TARGETED) and o.reason)
    not_targeted = Counter(o.family for o in outcomes if o.status == NOT_TARGETED)
    unscored_families = Counter(o.family for o in outcomes if o.status == UNSCORED)
    problems = [o for o in outcomes if o.status in (WRONG, MISSED)]
    return {
        "set": name,
        "documents_in_folder": documents_in_folder,
        "documents_keyed": documents_keyed,
        "documents_keyed_but_not_in_folder": documents_not_found,
        "families": {f: {**c, **rates(c)} for f, c in families.items()},
        "groups": {g: {**totals(families, g), **rates(totals(families, g))} for g in (READING, PLACEMENT, RECOGNITION)},
        "totals": {**totals(families), **rates(totals(families))},
        "not_targeted_by_family": dict(sorted(not_targeted.items())),
        "unscored_by_family": dict(sorted(unscored_families.items())),
        "unscored_or_untargeted_reasons": dict(sorted(reasons.items())),
        "extracted_values_with_no_key_cell": dict(sorted(extracted_unscored.items())),
        "unmapped_key_labels": dict(sorted(unmapped_labels.items())),
        "problems": [  # local report only: carries key values, never written into the repo
            {"file": o.filename, "family": o.family, "field": o.label, "status": o.status, "expected": o.expected,
             "actual": o.actual, "silent": o.silent, "flags": list(o.flags), "reason": o.reason}
            for o in problems[:detail_limit]
        ],
    }


def baseline_payload(summaries: dict[str, dict[str, Any]], mode: str) -> dict[str, Any]:
    """Aggregate counts only: family names and numbers. No values, no file names, no company names."""

    return {
        "schema": 1,
        "mode": mode,
        "note": "Aggregate counts only. Regenerate with: python -m backend.tools.accuracy --write-baseline <path>",
        "sets": {
            name: {
                "families": {f: {k: c[k] for k in COUNT_KEYS} for f, c in s["families"].items()},
                "totals": {k: s["totals"][k] for k in COUNT_KEYS},
            }
            for name, s in sorted(summaries.items())
        },
    }


def _pct(x: float | None) -> str:
    return "-" if x is None else f"{x * 100:.1f}%"


def render_markdown(summaries: dict[str, dict[str, Any]], mode: str) -> str:
    lines = [
        "# Accuracy report", "", f"Mode: `{mode}`. Scores are per field family.", "",
        "- **precision** = match / (match + wrong): of the values given, the share right. A value the key does not cover is "
        "*unscored*, never wrong.",
        "- **recall** = match / (match + wrong + missed). **exact** = matched with no tolerance (numbers as printed).",
        "- **silent** = wrong values that carried no warning flag and were not low confidence.", "",
    ]
    for name, s in summaries.items():
        t = s["totals"]
        lines += [f"## {name}", "",
                  f"Documents in folder: {s['documents_in_folder']}; with key rows: {s['documents_keyed']}"
                  f" (not in folder: {s['documents_keyed_but_not_in_folder']}).", "",
                  "| family | scored | match | exact | wrong | missed | silent | precision | recall | not targeted | unscored |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for fam, c in s["families"].items():
            lines.append(f"| {fam} | {c['scored']} | {c['match']} | {c['exact']} | {c['wrong']} | {c['missed']} | {c['silent']} |"
                         f" {_pct(c['precision'])} | {_pct(c['recall'])} | {c['not_targeted']} | {c['unscored']} |")
        lines.append(f"| **all** | {t['scored']} | {t['match']} | {t['exact']} | {t['wrong']} | {t['missed']} | {t['silent']} |"
                     f" {_pct(t['precision'])} | {_pct(t['recall'])} | {t['not_targeted']} | {t['unscored']} |")
        lines += ["", "By group: " + "; ".join(
            f"{g} {v['match']}/{v['wrong']}/{v['missed']} (match/wrong/missed), silent {v['silent']}"
            for g, v in s["groups"].items()), ""]
        if s["unscored_or_untargeted_reasons"]:
            lines += ["Unscored or not-targeted reasons: " + ", ".join(
                f"{k} {v}" for k, v in s["unscored_or_untargeted_reasons"].items()), ""]
        if s["unmapped_key_labels"]:
            lines += ["Key labels with no mapping rule (unscored): " + ", ".join(
                f"`{k}` x{v}" for k, v in s["unmapped_key_labels"].items()), ""]
        if s["extracted_values_with_no_key_cell"]:
            lines += ["Extracted values with no key cell (unscored, by extractor field): " + ", ".join(
                f"{k} {v}" for k, v in s["extracted_values_with_no_key_cell"].items()), ""]
        if s["problems"]:
            lines += ["<details><summary>Wrong and missed values</summary>", "",
                      "| file | field | status | expected | actual | silent | flags |", "|---|---|---|---|---|---|---|"]
            for p in s["problems"]:
                lines.append(f"| {p['file']} | {p['field']} | {p['status']} | {p['expected']} | {p['actual']} |"
                             f" {'yes' if p['silent'] else ''} | {', '.join(p['flags'])} |")
            lines += ["", "</details>", ""]
    return "\n".join(lines) + "\n"


def render_table(summaries: dict[str, dict[str, Any]]) -> str:
    out: list[str] = []
    for name, s in summaries.items():
        out.append(f"== {name} ==")
        out.append(f"{'family':24} {'scored':>6} {'match':>6} {'exact':>6} {'wrong':>6} {'missed':>6} {'silent':>6} {'prec':>7} {'recall':>7}")
        for fam, c in [*s["families"].items(), ("ALL", s["totals"])]:
            if c["scored"] == 0 and fam != "ALL":
                continue
            out.append(f"{fam:24} {c['scored']:>6} {c['match']:>6} {c['exact']:>6} {c['wrong']:>6} {c['missed']:>6} "
                       f"{c['silent']:>6} {_pct(c['precision']):>7} {_pct(c['recall']):>7}")
        out.append("")
    return "\n".join(out)
