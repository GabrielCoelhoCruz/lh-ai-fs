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
    check_deadline (deterministic) ──────────┤
                                             └──> adjudicate ──> memo

Budget/model limits live exclusively on ``llm.llm_run``. This module only
accepts ``stage_retries``. Nested ``llm_run`` scopes reuse the outer budget.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from typing import TypeVar

from adjudication import sanitize_adjudication
from agents import (
    adjudicate,
    check_facts,
    check_quotes,
    extract_citations,
    verify_citations,
    write_memo,
)
from assembly import (
    BRIEF_NAME,
    annotate_stage_notes,
    assemble,
    filter_ungrounded,
)
from deadline_check import check_deadline
from llm import (
    MODEL_FAST,
    MODEL_REASONING,
    LLMCallError,
    effective_model,
    env_int,
    llm_run,
)
from schemas import (
    AdjudicatedFinding,
    Finding,
    PipelineStatus,
    StageStatus,
    VerificationReport,
)

log = logging.getLogger(__name__)

T = TypeVar("T")

_DEFAULT_STAGE_RETRIES = env_int("BSD_STAGE_RETRIES", 0)


def _run_stage(
    name: str,
    fn: Callable[[], T],
    stages: list[StageStatus],
    retries: int | None = None,
) -> T | None:
    """Run one stage; record status; retry on retryable LLM errors up to ``retries``."""
    if retries is None:
        retries = _DEFAULT_STAGE_RETRIES
    start = time.monotonic()
    attempt = 0
    log.info("[stage] %s starting...", name)
    while True:
        try:
            result = fn()
            duration_ms = int((time.monotonic() - start) * 1000)
            stages.append(
                StageStatus(
                    name=name,
                    state="ok",
                    error=None,
                    duration_ms=duration_ms,
                )
            )
            log.info("[stage] %s ok (%sms)", name, duration_ms)
            return result
        except LLMCallError as e:
            if attempt < retries and e.kind in ("api", "truncated"):
                attempt += 1
                log.info(
                    "[stage] %s retry %s/%s after %s",
                    name,
                    attempt,
                    retries,
                    e.kind,
                )
                continue
            duration_ms = int((time.monotonic() - start) * 1000)
            stages.append(
                StageStatus(
                    name=name,
                    state="failed",
                    error=str(e),
                    duration_ms=duration_ms,
                )
            )
            log.info("[stage] %s failed (%sms): %s", name, duration_ms, e)
            return None
        except Exception as e:  # defensive: a stage bug must not kill the report
            duration_ms = int((time.monotonic() - start) * 1000)
            stages.append(
                StageStatus(
                    name=name,
                    state="failed",
                    error=f"unexpected: {e}",
                    duration_ms=duration_ms,
                )
            )
            log.info(
                "[stage] %s failed (%sms): unexpected: %s",
                name,
                duration_ms,
                e,
            )
            return None


def _skip_stage(name: str, reason: str, stages: list[StageStatus]) -> None:
    log.info("[stage] %s skipped: %s", name, reason)
    stages.append(StageStatus(name=name, state="skipped", error=reason, duration_ms=0))


def _assert_unique_finding_ids(
    findings: list[AdjudicatedFinding] | list[Finding],
    cnv: list[Finding],
) -> None:
    """Raise if any finding_id appears more than once across findings + CNV."""
    ids = [f.finding_id for f in findings] + [f.finding_id for f in cnv]
    seen: set[str] = set()
    dupes: set[str] = set()
    for fid in ids:
        if fid in seen:
            dupes.add(fid)
        seen.add(fid)
    if dupes:
        raise RuntimeError(
            "duplicate finding_id(s) in report: " + ", ".join(sorted(dupes))
        )


def _pipeline_status(
    stages: list[StageStatus],
    findings: list[AdjudicatedFinding],
    cnv: list[Finding],
) -> PipelineStatus:
    """Classify overall pipeline outcome.

    Ungrounded drops happen before adjudication; status uses post-adjudication
    findings plus CNV. Core failure = both CitationExtractor and CrossDocChecker
    failed, or no output with any stage failure. Empty citation extraction
    (verifier/quote stages skipped with "no citations found") is partial.
    """
    by_name = {s.name: s for s in stages}
    extract = by_name.get("CitationExtractor")
    facts = by_name.get("CrossDocChecker")
    core_both_failed = (
        extract is not None
        and extract.state == "failed"
        and facts is not None
        and facts.state == "failed"
    )
    has_output = bool(findings) or bool(cnv)
    any_failed = any(s.state == "failed" for s in stages)
    empty_extraction = any(
        s.state == "skipped" and s.error == "no citations found" for s in stages
    )

    if core_both_failed or (not has_output and any_failed):
        return "failed"
    if any_failed or empty_extraction:
        return "partial"
    return "complete"


def _case_caption(brief_text: str) -> str:
    m = re.search(r"Case No\.?\s*([A-Za-z0-9-]+)", brief_text)
    return f"Case No. {m.group(1)}" if m else BRIEF_NAME


def run_pipeline(
    documents: dict[str, str],
    *,
    stage_retries: int | None = None,
) -> VerificationReport:
    """Run the pipeline inside one bounded LLM usage scope.

    Callers that need a shared budget (e.g. eval + judge) wrap this in
    ``llm_run(budget)`` themselves. Nested ``llm_run`` reuses that outer scope.
    """
    retries = _DEFAULT_STAGE_RETRIES if stage_retries is None else stage_retries
    if retries < 0:
        raise ValueError("stage_retries must be zero or greater")

    with llm_run():
        return _execute_pipeline(documents, retries)


def _execute_pipeline(
    documents: dict[str, str],
    stage_retries: int,
) -> VerificationReport:
    brief = documents[BRIEF_NAME]
    sources = {k: v for k, v in documents.items() if k != BRIEF_NAME}
    stages: list[StageStatus] = []

    citations = _run_stage(
        "CitationExtractor",
        lambda: extract_citations(brief),
        stages,
        retries=stage_retries,
    )

    if citations and citations.citations:
        verification = _run_stage(
            "CitationVerifier",
            lambda: verify_citations(citations, brief),
            stages,
            retries=stage_retries,
        )
        if any(c.quoted_text for c in citations.citations):
            quotes = _run_stage(
                "QuoteChecker",
                lambda: check_quotes(citations),
                stages,
                retries=stage_retries,
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
        "CrossDocChecker",
        lambda: check_facts(brief, sources),
        stages,
        retries=stage_retries,
    )

    deadline = _run_stage(
        "DeadlineChecker",
        lambda: check_deadline(brief),
        stages,
        retries=stage_retries,
    )

    findings, cnv, assembly_notes = assemble(citations, verification, quotes, facts)
    annotate_stage_notes(stages, assembly_notes)
    # Keep DeadlineChecker's stable id (finding-deadline). Do NOT renumber with
    # len(findings)+1 — assemble's sequence also covers CNV entries, so that
    # stamp can collide and double-count TPs in the eval scorer.
    if isinstance(deadline, Finding):
        findings.append(deadline)
    findings, dropped_ungrounded = filter_ungrounded(findings, documents)

    if findings:
        adjudication = _run_stage(
            "ConfidenceAdjudicator",
            lambda: adjudicate(findings),
            stages,
            retries=stage_retries,
        )
        adjudicated = sanitize_adjudication(findings, adjudication)
    else:
        adjudicated = []
        _skip_stage("ConfidenceAdjudicator", "no findings to adjudicate", stages)

    _assert_unique_finding_ids(adjudicated, cnv)

    live = [f for f in adjudicated if f.duplicate_of is None]
    if live:
        memo_result = _run_stage(
            "JudicialMemoWriter",
            lambda: write_memo(adjudicated),
            stages,
            retries=stage_retries,
        )
        memo = memo_result.memo if memo_result else None
    else:
        memo = None
        _skip_stage("JudicialMemoWriter", "no findings to summarize", stages)

    order = {"high": 0, "medium": 1, "low": 2}
    adjudicated.sort(
        key=lambda f: (
            f.duplicate_of is not None,
            order[f.severity],
            -f.confidence,
        )
    )

    status = _pipeline_status(stages, adjudicated, cnv)

    return VerificationReport(
        case_caption=_case_caption(brief),
        document_analyzed=BRIEF_NAME,
        pipeline_status=status,
        findings=adjudicated,
        could_not_verify=cnv,
        judicial_memo=memo,
        stages=stages,
        citations=citations.citations if citations else None,
        citation_verdicts=verification.verdicts if verification else None,
        dropped_ungrounded=dropped_ungrounded,
        model_fast=effective_model(MODEL_FAST),
        model_reasoning=effective_model(MODEL_REASONING),
    )


# Compat aliases for existing probes that imported private names.
_assemble = assemble
_filter_ungrounded = filter_ungrounded
_annotate_stage_notes = annotate_stage_notes
_sanitize_adjudication = sanitize_adjudication
