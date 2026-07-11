"""Shared evidence-grounding helpers for pipeline and eval harness."""

from __future__ import annotations

import re
from collections.abc import Sequence

from schemas import EvidenceQuote


def norm(s: str) -> str:
    s = s.lower()
    for a, b in [
        ("‘", "'"), ("’", "'"), ("“", '"'), ("”", '"'),
        ("—", "-"), ("–", "-"), ("…", "..."),
    ]:
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip()


def quote_grounded(quote: str, document_text: str) -> bool:
    """True if the quote appears in the document (ellipsis-elided quotes are
    checked segment by segment). Empty / whitespace-only quotes are never
    grounded — the empty string appears in every document."""
    cleaned = norm(quote)
    if not cleaned:
        return False
    doc = norm(document_text)
    segments = [seg.strip(" .\"'") for seg in cleaned.split("...")]
    segments = [seg for seg in segments if len(seg) >= 12] or [
        cleaned.strip(" .\"'")
    ]
    segments = [seg for seg in segments if seg]
    if not segments:
        return False
    return all(seg in doc for seg in segments)


def evidence_grounded(
    evidence: Sequence[EvidenceQuote],
    documents: dict[str, str],
) -> tuple[bool, list[str]]:
    """Return (all_grounded, list of ungrounded quotes).

    An empty evidence list is never grounded (vacuous truth would let
    findings with no quotes survive the production filter).
    """
    if not evidence:
        return False, ["<empty evidence>"]
    bad: list[str] = []
    for e in evidence:
        if e.document not in documents or not quote_grounded(
            e.quote, documents[e.document]
        ):
            bad.append(e.quote if e.quote else "<empty quote>")
    return len(bad) == 0, bad
