"""Users see "Sustentra's AI", never the vendor's model name (stored notes are renamed when shown)."""

from backend.app.api import methodology_review
from backend.app.services import ai_facility, engagement_recalculation_service as recalc
from backend.app.services.halt_text import plain_note


def test_user_facing_constants_do_not_name_the_vendor() -> None:
    texts = [ai_facility.SOURCE_LABEL, methodology_review._NOT_SAVED, *recalc.NOT_ON_A_LINE_WHY.values(),
             *methodology_review._FAILED.values()]
    assert texts and all("claude" not in t.lower() for t in texts)


def test_notes_saved_with_the_old_name_show_the_new_one() -> None:
    for old in ("Claude suggested CT-S2-ELEC from the first pages; the rules could not place this document.",
                "ai_unavailable: Claude could not be reached.",
                "ai_routing_ignored: Claude's type suggestion was not used."):
        assert "claude" not in plain_note(old).lower()
    assert plain_note("ai_unavailable: Claude could not be reached.") == "ai_unavailable: Sustentra's AI could not be reached."
