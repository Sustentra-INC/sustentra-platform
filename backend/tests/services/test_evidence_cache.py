"""The Evidence cache (MVP-160): bounded, stamped, scoped by organization."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

from backend.app.services import evidence_cache
from backend.app.services.evidence_cache import EvidenceCache


def test_an_entry_is_served_only_for_the_stamp_it_was_built_from() -> None:
    cache = EvidenceCache(max_entries=4)
    cache.put(("org:a", "eng"), "s1", {"total": 1})
    assert cache.get(("org:a", "eng"), "s1") == {"total": 1}
    assert cache.get(("org:a", "eng"), "s2") is None  # something changed: a miss
    assert (cache.hits, cache.misses) == (1, 1)
    cache.put(("org:a", "eng"), "s2", {"total": 2})  # the fresh answer replaces the old one
    assert cache.get(("org:a", "eng"), "s2") == {"total": 2} and cache.get(("org:a", "eng"), "s1") is None
    assert len(cache) == 1


def test_no_stamp_means_nothing_is_kept_or_served() -> None:
    cache = EvidenceCache(max_entries=4)
    cache.put("k", None, "value")
    assert len(cache) == 0
    cache.put("k", "s", "value")
    assert cache.get("k", None) is None  # a store that cannot stamp is never served from the cache


def test_the_cache_is_bounded_and_drops_the_least_recently_used() -> None:
    cache = EvidenceCache(max_entries=3)
    for name in "abc":
        cache.put(name, "s", name)
    assert cache.get("a", "s") == "a"  # a is now the most recent
    cache.put("d", "s", "d")
    assert len(cache) == 3
    assert cache.get("b", "s") is None  # b was the least recently used
    assert [cache.get(k, "s") for k in "acd"] == ["a", "c", "d"]
    for index in range(1000):
        cache.put(f"many-{index}", "s", index)
    assert len(cache) == 3


def test_an_entry_is_never_served_to_another_organization() -> None:
    org_a, org_b = uuid.uuid4(), uuid.uuid4()
    a = SimpleNamespace(is_provider=False, org_id=org_a)
    b = SimpleNamespace(is_provider=False, org_id=org_b)
    provider = SimpleNamespace(is_provider=True, org_id=None)
    scopes = {evidence_cache.scope_of(u) for u in (a, b, provider)}
    assert len(scopes) == 3 and evidence_cache.scope_of(provider) == "provider"
    cache = EvidenceCache(max_entries=8)
    cache.put((evidence_cache.scope_of(a), "eng-1"), "s", "A's answer")
    assert cache.get((evidence_cache.scope_of(b), "eng-1"), "s") is None
    assert cache.get((evidence_cache.scope_of(provider), "eng-1"), "s") is None  # the provider also sees legacy rows
    assert cache.get((evidence_cache.scope_of(a), "eng-1"), "s") == "A's answer"


def test_the_digest_follows_the_content_not_the_key_order() -> None:
    assert evidence_cache.digest({"a": 1, "b": [1, 2]}) == evidence_cache.digest({"b": [1, 2], "a": 1})
    assert evidence_cache.digest({"a": 1}) != evidence_cache.digest({"a": 2})
    assert evidence_cache.digest({"name": "Müller 電気 CO₂", "when": uuid.UUID(int=1)})  # odd values still hash


def test_a_store_that_cannot_stamp_is_never_cached() -> None:
    class Bare:  # the three seams without stamps, as a test double has them
        pass

    assert asyncio.run(evidence_cache.stamp(None, {"id": uuid.uuid4()}, Bare(), Bare(), Bare())) is None  # type: ignore[arg-type]


def test_the_cache_is_bounded_by_bytes_too() -> None:
    cache = EvidenceCache(max_entries=100, max_bytes=1000)
    for name in "abcd":
        cache.put(name, "s", name, size=300)
    assert cache.size_bytes <= 1000 and len(cache) == 3  # a was the least recently used
    assert cache.get("a", "s") is None and cache.get("d", "s") == "d"
    cache.put("huge", "s", "x", size=5000)  # larger than the whole cache: never kept
    assert cache.get("huge", "s") is None
    cache.put("d", "s2", "d2", size=100)  # a replaced entry gives its bytes back
    assert cache.size_bytes == 300 + 300 + 100
    cache.clear()
    assert cache.size_bytes == 0


def test_the_stamp_changes_with_a_fuel_rename_and_with_a_fuel_delete() -> None:
    """MVP-145: a Level 2 change lives in the engagement's settings, which the stamp digests, so no stale tree or
    recalculation is served after a rename or a delete."""

    row = SimpleNamespace(n=0, top="", digest="d")

    class Db:
        async def execute(self, *_: object, **__: object) -> SimpleNamespace:
            return SimpleNamespace(one=lambda: row)

    source = SimpleNamespace(documents_stamp=lambda _key: "docs", extraction_stamp=lambda _key: "ext",
                             engagement_stamp=lambda _key: "rev")
    line = {"category": "stationary", "level2_label": "Propane", "anchor_kind": "facility", "anchor_id": "F1",
            "label": "Propane at Kent"}
    base = {"id": "E1", "settings": {"evidenceLines": [line]}}
    renamed = {**base, "settings": {**base["settings"], "evidenceLevel2Names": {"stationary:propane": {"label": "LPG"}}}}
    again = {**base, "settings": {**base["settings"], "evidenceLevel2Names": {"stationary:propane": {"label": "LPG 2"}}}}
    deleted = {**base, "settings": {"evidenceLines": []}}

    def stamp(engagement: dict) -> str | None:
        return asyncio.run(evidence_cache.stamp(Db(), engagement, source, source, source))  # type: ignore[arg-type]

    stamps = [stamp(e) for e in (base, renamed, again, deleted)]
    assert all(stamps) and len(set(stamps)) == 4
    assert stamp(base) == stamps[0]  # and the same settings give the same stamp
