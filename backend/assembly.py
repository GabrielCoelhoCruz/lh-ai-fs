"""Deterministic assembly: stage outputs -> Finding objects."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TypeVar

from grounding import evidence_grounded
from schemas import (
    CitationExtraction,
    CitationVerification,
    CrossDocCheck,
    EvidenceQuote,
    ExtractedCitation,
    Finding,
    QuoteChecking,
    StageStatus,
)

BRIEF_NAME = "motion_for_summary_judgment"

T = TypeVar("T")


def _backfill_missing(
    items: Iterable[T],
    checked_ids: set[str],
    item_id: Callable[[T], str],
    make_cnv: Callable[[T], Finding],
    cnv: list[Finding],
) -> None:
    """Emit could-not-verify findings for extracted items with no stage output."""
    for item in items:
        if item_id(item) not in checked_ids:
            cnv.append(make_cnv(item))


def assemble(
    citations: CitationExtraction | None,
    verification: CitationVerification | None,
    quotes: QuoteChecking | None,
    facts: CrossDocCheck | None,
) -> tuple[list[Finding], list[Finding], dict[str, int]]:
    """Map typed stage outputs to findings.

    Returns (findings, could_not_verify, assembly_notes).
    """
    findings: list[Finding] = []
    cnv: list[Finding] = []
    notes: dict[str, int] = {
        "unknown_verdict_ids": 0,
        "unknown_quote_ids": 0,
    }
    seq = 0

    def make(
        category,
        severity,
        title,
        description,
        location,
        evidence,
        agent,
        *,
        backfilled: bool = False,
    ):
        nonlocal seq
        seq += 1
        return Finding(
            finding_id=f"finding-{seq}",
            category=category,
            severity=severity,
            title=title,
            description=description,
            brief_location=location,
            evidence=evidence,
            source_agent=agent,
            backfilled=backfilled,
        )

    by_id = {c.citation_id: c for c in citations.citations} if citations else {}

    if citations:
        uncited = citations.uncited_legal_assertions
        if len(uncited) == 1:
            a = uncited[0]
            findings.append(
                make(
                    "unsupported_assertion",
                    "medium",
                    "Legal argument advanced without any supporting authority",
                    "The brief states and applies a rule of law without citing "
                    "any case, statute, or regulation in support.",
                    a.brief_location,
                    [EvidenceQuote(document=BRIEF_NAME, quote=a.text)],
                    "CitationExtractor",
                )
            )
        elif len(uncited) > 1:
            locations = "; ".join(a.brief_location for a in uncited)
            enumerated = " ".join(
                f"({i}) at {a.brief_location}: {a.text}"
                for i, a in enumerate(uncited, start=1)
            )
            findings.append(
                make(
                    "unsupported_assertion",
                    "medium",
                    "Legal argument advanced without any supporting authority",
                    "The brief states and applies rules of law without citing "
                    "any case, statute, or regulation in support. Uncited "
                    f"assertions: {enumerated}",
                    locations,
                    [
                        EvidenceQuote(document=BRIEF_NAME, quote=a.text)
                        for a in uncited
                    ],
                    "CitationExtractor",
                )
            )

    if citations and citations.citations:
        verdict_ids: set[str] = set()
        if verification:
            verdict_ids = {v.citation_id for v in verification.verdicts}
            for v in verification.verdicts:
                c = by_id.get(v.citation_id)
                if c is None:
                    notes["unknown_verdict_ids"] += 1
                    continue
                cite_evidence = [
                    EvidenceQuote(document=BRIEF_NAME, quote=c.full_citation)
                ]
                label = c.case_name or c.full_citation
                jurisdiction = (
                    f" Jurisdiction concern: {v.jurisdiction_concern}"
                    if v.jurisdiction_concern
                    else ""
                )
                if v.existence == "likely_fabricated":
                    findings.append(
                        make(
                            "fabricated_citation",
                            "high" if v.confidence != "low" else "medium",
                            f"Cited authority could not be located: {label}",
                            f"{v.existence_reasoning}{jurisdiction}",
                            c.brief_location,
                            cite_evidence,
                            "CitationVerifier",
                        )
                    )
                elif v.existence == "real":
                    if v.support_verdict in ("mischaracterized", "unsupported"):
                        findings.append(
                            make(
                                "mischaracterized_holding",
                                "high",
                                f"Authority does not support the stated "
                                f"proposition: {label}",
                                f"{v.support_reasoning}{jurisdiction}",
                                c.brief_location,
                                cite_evidence,
                                "CitationVerifier",
                            )
                        )
                    elif v.support_verdict == "partially_supported":
                        findings.append(
                            make(
                                "mischaracterized_holding",
                                "medium",
                                f"Brief overstates the authority: {label}",
                                f"{v.support_reasoning}{jurisdiction}",
                                c.brief_location,
                                cite_evidence,
                                "CitationVerifier",
                            )
                        )
                else:
                    cnv.append(
                        make(
                            "could_not_verify",
                            "low",
                            f"Could not verify authority: {label}",
                            v.existence_reasoning,
                            c.brief_location,
                            cite_evidence,
                            "CitationVerifier",
                        )
                    )

        def _missing_verdict(c: ExtractedCitation) -> Finding:
            label = c.case_name or c.full_citation
            return make(
                "could_not_verify",
                "low",
                f"No verification produced for authority: {label}",
                "CitationVerifier did not return a verdict for this "
                "extracted citation.",
                c.brief_location,
                [EvidenceQuote(document=BRIEF_NAME, quote=c.full_citation)],
                "CitationVerifier",
                backfilled=True,
            )

        _backfill_missing(
            citations.citations,
            verdict_ids,
            lambda c: c.citation_id,
            _missing_verdict,
            cnv,
        )

    quoted_citations = [
        c for c in (citations.citations if citations else []) if c.quoted_text
    ]
    if quoted_citations:
        checked_ids: set[str] = set()
        if quotes:
            for q in quotes.checks:
                c = by_id.get(q.citation_id)
                if c is None:
                    notes["unknown_quote_ids"] += 1
                    continue
                checked_ids.add(q.citation_id)
                location = c.brief_location
                label = c.case_name or c.full_citation
                evidence = [EvidenceQuote(document=BRIEF_NAME, quote=q.quoted_text)]
                actual = (
                    f" Known actual language/rule: {q.known_actual_language}"
                    if q.known_actual_language
                    else ""
                )
                if q.verdict in ("doctored", "fabricated"):
                    findings.append(
                        make(
                            "doctored_quote",
                            "high",
                            f"Quotation attributed to {label} appears {q.verdict}",
                            f"{q.reasoning}{actual}",
                            location,
                            evidence,
                            "QuoteChecker",
                        )
                    )
                elif q.verdict == "could_not_verify":
                    cnv.append(
                        make(
                            "could_not_verify",
                            "low",
                            f"Could not verify quotation attributed to {label}",
                            q.reasoning,
                            location,
                            evidence,
                            "QuoteChecker",
                        )
                    )

        def _missing_quote(c: ExtractedCitation) -> Finding:
            label = c.case_name or c.full_citation
            return make(
                "could_not_verify",
                "low",
                f"No quote check produced for quotation attributed to {label}",
                "QuoteChecker did not return a check for this "
                "extracted quotation.",
                c.brief_location,
                [EvidenceQuote(document=BRIEF_NAME, quote=c.quoted_text)],
                "QuoteChecker",
                backfilled=True,
            )

        _backfill_missing(
            quoted_citations,
            checked_ids,
            lambda c: c.citation_id,
            _missing_quote,
            cnv,
        )

    if facts:
        for f in facts.facts:
            if f.status == "contradicted":
                findings.append(
                    make(
                        "cross_document_contradiction",
                        "high" if f.confidence == "high" else "medium",
                        f"Brief claim contradicted by case file: {f.claim_text[:80]}",
                        f.reasoning,
                        f.brief_location,
                        [EvidenceQuote(document=BRIEF_NAME, quote=f.claim_text)]
                        + f.evidence,
                        "CrossDocChecker",
                    )
                )
            elif f.status == "unsupported":
                findings.append(
                    make(
                        "unsupported_assertion",
                        "medium",
                        f"Claim asserted without record support: {f.claim_text[:80]}",
                        f.reasoning,
                        f.brief_location,
                        [EvidenceQuote(document=BRIEF_NAME, quote=f.claim_text)],
                        "CrossDocChecker",
                    )
                )
            elif f.status == "could_not_verify":
                cnv.append(
                    make(
                        "could_not_verify",
                        "low",
                        f"Outside the case file's coverage: {f.claim_text[:80]}",
                        f.reasoning,
                        f.brief_location,
                        [EvidenceQuote(document=BRIEF_NAME, quote=f.claim_text)],
                        "CrossDocChecker",
                    )
                )

    return findings, cnv, notes


def filter_ungrounded(
    findings: list[Finding],
    documents: dict[str, str],
) -> tuple[list[Finding], int]:
    """Drop findings whose evidence quotes are not grounded in source documents."""
    kept: list[Finding] = []
    dropped = 0
    for f in findings:
        grounded, _ = evidence_grounded(f.evidence, documents)
        if grounded:
            kept.append(f)
        else:
            dropped += 1
    return kept, dropped


def annotate_stage_notes(stages: list[StageStatus], notes: dict[str, int]) -> None:
    """Attach non-fatal assembly warnings to ok stages via ``note``."""
    by_name = {s.name: s for s in stages}
    if notes.get("unknown_verdict_ids"):
        stage = by_name.get("CitationVerifier")
        if stage is not None and stage.state == "ok":
            stage.note = (
                f"{notes['unknown_verdict_ids']} verdict(s) referenced unknown "
                "citation_ids (discarded)"
            )
    if notes.get("unknown_quote_ids"):
        stage = by_name.get("QuoteChecker")
        if stage is not None and stage.state == "ok":
            stage.note = (
                f"{notes['unknown_quote_ids']} quote check(s) referenced unknown "
                "citation_ids (discarded)"
            )
