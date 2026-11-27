"""One engagement's documents with their extraction results and review decisions, read in bulk.

The Evidence tree, the schedule and the recalculation all walk every document of an engagement and
need its extraction results and its review decisions. Asking the stores one document at a time is
two queries per document (an N+1: 500 documents, 1,000+ round trips). ``DocumentReads`` asks once
for the whole engagement (one query for the documents, one for all their results, one for all their
decisions) and hands each document its own slice, so the number of queries does not depend on the
number of documents.

The seams are the services the callers already inject. A seam without the bulk method (a test
double) is read one document at a time, as before. Nothing is cached beyond this object's life, so
build one per request (or per calculation), never keep one.
"""

from __future__ import annotations

import gc
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

_gc_lock = threading.Lock()
_gc_paused = 0
_gc_was_on = False


@contextmanager
def gc_paused() -> Iterator[None]:
    """Python's cyclic garbage collector off while an engagement's records are built.

    Reading and placing tens of thousands of records allocates hundreds of thousands of long-lived objects, and the
    collector re-scans them again and again as they pile up: about a third of the time of a 500-document load. None
    of them are cyclic garbage, so nothing is lost by waiting; the collector is back on (and runs as usual) when
    the last such block ends. Several requests may overlap: it is turned back on only when none is left."""

    global _gc_paused, _gc_was_on
    with _gc_lock:
        if _gc_paused == 0:
            _gc_was_on = gc.isenabled()
            gc.disable()
        _gc_paused += 1
    try:
        yield
    finally:
        with _gc_lock:
            _gc_paused -= 1
            if _gc_paused == 0 and _gc_was_on:
                gc.enable()


@dataclass(frozen=True)
class DocumentRead:
    document: dict[str, Any]
    results: list[dict[str, Any]]  # the extraction results this reader may see, oldest first
    reviews: list[dict[str, Any]]  # the review decisions this reader may see, oldest first


class DocumentReads:
    def __init__(self, upload_service: Any, pipeline_service: Any, review_service: Any, engagement_id: str,
                 can_see: Callable[[dict], bool]) -> None:
        self._upload = upload_service
        self._pipeline = pipeline_service
        self._reviews = review_service
        self._engagement_id = engagement_id
        self._can_see = can_see
        self._documents: list[dict[str, Any]] | None = None
        self._results: dict[str, list[dict[str, Any]]] | None = None
        self._decisions: dict[str, list[dict[str, Any]]] | None = None

    def documents(self) -> list[dict[str, Any]]:
        """The engagement's documents this reader may see, in upload order (one query)."""

        if self._documents is None:
            self._documents = [d for d in self._upload.list_documents(self._engagement_id) if self._can_see(d)]
        return self._documents

    def _ids(self) -> list[str]:
        return [str(d.get("document_id")) for d in self.documents()]

    def _load_results(self) -> dict[str, list[dict[str, Any]]]:
        if self._results is None:
            bulk = getattr(self._pipeline, "list_extraction_results_by_documents", None)
            if bulk is not None:
                self._results = dict(bulk(self._ids()))
            else:  # a seam that cannot read in bulk: one document at a time
                self._results = {i: list(self._pipeline.list_extraction_results_by_document(i)) for i in self._ids()}
        return self._results

    def _load_decisions(self) -> dict[str, list[dict[str, Any]]]:
        if self._decisions is None:
            bulk = getattr(self._reviews, "list_by_documents", None)
            if bulk is not None:
                self._decisions = dict(bulk(self._ids()))
            else:
                self._decisions = {i: list(self._reviews.list_by_document(i)) for i in self._ids()}
        return self._decisions

    def results(self, document: dict[str, Any]) -> list[dict[str, Any]]:
        found = self._load_results().get(str(document.get("document_id")), [])
        return [r for r in found if self._can_see(r)]

    def reviews(self, document: dict[str, Any]) -> list[dict[str, Any]]:
        found = self._load_decisions().get(str(document.get("document_id")), [])
        return [d for d in found if self._can_see(d)]

    def read(self, document: dict[str, Any]) -> DocumentRead:
        return DocumentRead(document, self.results(document), self.reviews(document))

    def __iter__(self) -> Iterator[DocumentRead]:
        """Every visible document with its results and decisions."""

        for document in self.documents():
            yield self.read(document)
