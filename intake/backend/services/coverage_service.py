"""Coverage maths for the interview meter (intake Stage 2, Phase C2).

Counts only the questions that currently apply to this client, so the total
moves as answers come in: saying "no" to fuel-burning equipment removes the
follow-up about blends, and the denominator drops with it. That is deliberate -
it is honest about how much is actually left - so the meter is presented as
"14 of 22", never as a percentage that appears to go backwards.

What counts as done is judged from the client's side, not ours. If they have
given an answer, that question is done for them - even when it has also gone to
our team for confirmation, which every boundary answer does. A question that
escalated with no answer (they said "not sure") is genuinely still open.

Without that distinction the meter would stall for clients who had in fact
answered everything, because roughly a quarter of the questions are
human-confirmed by design. The count of questions sitting with the team is
reported separately, so nothing is hidden.
"""

from __future__ import annotations

from typing import Any

from intake.backend.config import load_profile_schema
from intake.backend.services.interview_engine import ANSWERED_STATUSES, InterviewEngine


def is_complete_for_client(state: dict[str, Any]) -> bool:
    """True when the client has nothing left to do on this question."""
    if state["status"] in ANSWERED_STATUSES:
        return True
    # Answered, then escalated for team confirmation: done from their side.
    return state["status"] == "escalated" and state.get("value") is not None


class CoverageService:
    def __init__(self, engine: InterviewEngine) -> None:
        self._engine = engine
        schema = load_profile_schema()
        self._sections = {
            section["section_id"]: section for section in schema["sections"]
        }
        self._datapoints = {
            datapoint["datapoint_id"]: datapoint for datapoint in schema["datapoints"]
        }

    def coverage(self, org_id: str) -> dict[str, Any]:
        states = self._engine.applicable_states(org_id)
        total = len(states)
        complete = sum(1 for state in states if is_complete_for_client(state))
        escalated = sum(1 for state in states if state["status"] == "escalated")

        by_section: dict[str, dict[str, Any]] = {}
        for state in states:
            section_id = self._datapoints[state["datapoint_id"]]["section"]
            bucket = by_section.setdefault(
                section_id,
                {
                    "section_id": section_id,
                    "label": self._sections[section_id]["label"],
                    "order": self._sections[section_id]["order"],
                    "total": 0,
                    "complete": 0,
                },
            )
            bucket["total"] += 1
            if is_complete_for_client(state):
                bucket["complete"] += 1

        return {
            "complete": complete,
            "total": total,
            "escalated": escalated,
            "remaining": total - complete,
            "is_complete": total > 0 and complete == total,
            "label": f"{complete} of {total} complete",
            "note": "The total can change as you answer - some questions only apply to some businesses.",
            "sections": sorted(by_section.values(), key=lambda item: item["order"]),
        }
