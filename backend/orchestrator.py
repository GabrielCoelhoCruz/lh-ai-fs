"""Deterministic pipeline orchestrator.

Plain Python controls the pipeline — which agents run, in what order, and
what happens when one fails. LLMs make judgments inside stages; they never
decide control flow. Every stage is recorded in the report with its state
and duration, and a stage failure degrades the report instead of aborting it
(a partial verification is still useful; a 500 is not).

Stage graph:

    extract_citations ──> verify_citations ──┐
                     └──> check_quotes ──────┤
    check_facts (independent) ───────────────┼──> assemble findings
                                             └──> adjudicate ──> memo
"""

import re
import time
from collections.abc import Callable
from typing import TypeVar

from agents import (
    adjudicate,
    check_facts,
    check_quotes,
    extract_citations,
    verify_citations,
    write_memo,
)
from llm import MODEL_FAST, MODEL_REASONING, LLMCallError
from schemas import (
    AdjudicatedFinding,
    CitationExtraction,
    EvidenceQuote,
    Finding,
    StageStatus,
    VerificationReport,
)

BRIEF_NAME = "motion_for_summary_judgment"

T = TypeVar("T")

# Heuristic confidence used only when the adjudication stage itself fails.
_FALLBACK_CONFIDENCE = {"high": 0.8, "medium": 0.6, "low": 0.4}


def _run_stage(
    name: str,
    fn: Callable[[], T],
    stages: list[StageStatus],
    retries: int = 1,
) -> T | None:
    """Run one stage; record status; retry once on retryable LLM errors."""
    start = time.monotonic()
    attempt = 0
    while True:
        try:
            result = fn()
            stages.append(
                StageStatus(
                    name=name,
                    state="ok",
                    error=None,
                    duration_ms=int((time.monotonic() - start) * 1000),
                )
            )
            return result
        except LLMCallError as e:
            # bad_schema and refusal will not improve on retry with same input
            if attempt < retries and e.kind in ("api", "truncated"):
                attempt += 1
                continue
            stages.append(
                StageStatus(
                    name=name,
                    state="failed",
                    error=str(e),
                    duration_ms=int((time.monotonic() - start) * 1000),
                )
            )
            return None
        except Exception as e:  # defensive: a stage bug must not kill the report
            stages.append(
                StageStatus(
                    name=name,
                    state="failed",
                    error=f"unexpected: {e}",
                    duration_ms=int((time.monotonic() - start) * 1000),
                )
            )
            return None


def _skip_stage(name: str, reason: str, stages: list[StageStatus]) -> None:
    stages.append(StageStatus(name=name, state="skipped", error=reason, duration_ms=0))


# ---------------------------------------------------------------------------
# Deterministic assembly: stage outputs -> Finding objects
# ---------------------------------------------------------------------------


def _assemble(
    citations: CitationExtraction | None,
    verification,
    quotes,
    facts,
) -> tuple[list[Finding], list[Finding]]:
    """Map typed stage outputs to findings. Returns (findings, could_not_verify)."""
    findings: list[Finding] = []
    cnv: list[Finding] = []
    seq = 0

    def make(category, severity, title, description, location, evidence, agent):
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
        )

    by_id = {c.citation_id: c for c in citations.citations} if citations else {}

    # Legal doctrine advanced with no supporting authority is itself a defect —
    # flagged deterministically, no LLM judgment required.
    if citations:
        for a in citations.uncited_legal_assertions:
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

    if verification:
        for v in verification.verdicts:
            c = by_id.get(v.citation_id)
            if c is None:
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
                            f"Authority does not support the stated proposition: {label}",
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
            else:  # could_not_verify
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

    if quotes:
        for q in quotes.checks:
            c = by_id.get(q.citation_id)
            location = c.brief_location if c else "unknown"
            label = (c.case_name or c.full_citation) if c else q.citation_id
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
            # consistent claims produce no finding

    return findings, cnv


def _passthrough_adjudication(findings: list[Finding]) -> list[AdjudicatedFinding]:
    """Degraded mode when the adjudicator stage fails: heuristic confidence."""
    return [
        AdjudicatedFinding(
            **f.model_dump(),
            confidence=_FALLBACK_CONFIDENCE[f.severity],
            confidence_reasoning=(
                "Adjudication stage unavailable; heuristic confidence assigned "
                "from severity."
            ),
            duplicate_of=None,
        )
        for f in findings
    ]


def _case_caption(brief_text: str) -> str:
    m = re.search(r"Case No\.?\s*([A-Za-z0-9-]+)", brief_text)
    return f"Case No. {m.group(1)}" if m else BRIEF_NAME


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_pipeline(documents: dict[str, str]) -> VerificationReport:
    brief = documents[BRIEF_NAME]
    sources = {k: v for k, v in documents.items() if k != BRIEF_NAME}
    stages: list[StageStatus] = []

    citations = _run_stage(
        "CitationExtractor", lambda: extract_citations(brief), stages
    )

    if citations and citations.citations:
        verification = _run_stage(
            "CitationVerifier", lambda: verify_citations(citations, brief), stages
        )
        if any(c.quoted_text for c in citations.citations):
            quotes = _run_stage(
                "QuoteChecker", lambda: check_quotes(citations), stages
            )
        else:
            quotes = None
            _skip_stage("QuoteChecker", "no direct quotes in brief", stages)
    else:
        verification = None
        quotes = None
        reason = (
            "citation extraction failed"
            if citations is None
            else "no citations found"
        )
        _skip_stage("CitationVerifier", reason, stages)
        _skip_stage("QuoteChecker", reason, stages)

    facts = _run_stage(
        "CrossDocChecker", lambda: check_facts(brief, sources), stages
    )

    findings, cnv = _assemble(citations, verification, quotes, facts)

    if findings:
        adjudication = _run_stage(
            "ConfidenceAdjudicator", lambda: adjudicate(findings), stages
        )
        adjudicated = (
            adjudication.findings
            if adjudication
            else _passthrough_adjudication(findings)
        )
    else:
        adjudicated = []
        _skip_stage("ConfidenceAdjudicator", "no findings to adjudicate", stages)

    live = [f for f in adjudicated if f.duplicate_of is None]
    if live:
        memo_result = _run_stage(
            "JudicialMemoWriter", lambda: write_memo(adjudicated), stages
        )
        memo = memo_result.memo if memo_result else None
    else:
        memo = None
        _skip_stage("JudicialMemoWriter", "no findings to summarize", stages)

    # Highest severity and confidence first, duplicates last.
    order = {"high": 0, "medium": 1, "low": 2}
    adjudicated.sort(
        key=lambda f: (
            f.duplicate_of is not None,
            order[f.severity],
            -f.confidence,
        )
    )

    return VerificationReport(
        case_caption=_case_caption(brief),
        document_analyzed=BRIEF_NAME,
        findings=adjudicated,
        could_not_verify=cnv,
        judicial_memo=memo,
        stages=stages,
        model_fast=MODEL_FAST,
        model_reasoning=MODEL_REASONING,
    )
