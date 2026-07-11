"""Orchestrator integrity probes (no LLM required)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from grounding import evidence_grounded, quote_grounded
from orchestrator import (
    _annotate_stage_notes,
    _assemble,
    _filter_ungrounded,
    _pipeline_status,
    _run_stage,
    _sanitize_adjudication,
)
from schemas import (
    AdjudicatedFinding,
    Adjudication,
    CitationExtraction,
    EvidenceQuote,
    ExtractedCitation,
    Finding,
    QuoteCheck,
    QuoteChecking,
    StageStatus,
)


def _finding(
    fid: str,
    *,
    evidence: list | None = None,
    category: str = "unsupported_assertion",
    severity: str = "medium",
) -> Finding:
    return Finding(
        finding_id=fid,
        category=category,
        severity=severity,
        title=f"Title {fid}",
        description=f"Desc {fid}",
        brief_location="Sec I",
        evidence=evidence
        if evidence is not None
        else [EvidenceQuote(document="motion_for_summary_judgment", quote="test quote here")],
        source_agent="CrossDocChecker",
    )


def _adj(
    fid: str,
    *,
    duplicate_of: str | None = None,
    confidence: float = 0.8,
) -> AdjudicatedFinding:
    src = _finding(fid)
    return AdjudicatedFinding(
        **src.model_dump(),
        confidence=confidence,
        confidence_reasoning="test",
        duplicate_of=duplicate_of,
    )


def _citation(
    cid: str,
    *,
    quoted_text: str | None = None,
    full_citation: str = "Smith v. Jones, 1 Cal.4th 1 (2000)",
) -> ExtractedCitation:
    return ExtractedCitation(
        citation_id=cid,
        kind="case",
        case_name="Smith v. Jones",
        full_citation=full_citation,
        reporter="Cal.4th",
        volume=1,
        first_page=1,
        pinpoint=None,
        year=2000,
        quoted_text=quoted_text,
        asserted_proposition="Some proposition",
        brief_location="Section III.A",
    )


def test_sanitize_restores_missing_and_clamps():
    inputs = [_finding("finding-1")]
    adjudication = Adjudication(
        findings=[
            AdjudicatedFinding(
                finding_id="finding-1",
                category="fabricated_citation",
                severity="high",
                title="Hijacked",
                description="Changed",
                brief_location="wrong",
                evidence=[EvidenceQuote(document="fake", quote="nope")],
                source_agent="evil",
                confidence=2.5,
                confidence_reasoning="bad",
                duplicate_of="missing-id",
            )
        ]
    )
    result = _sanitize_adjudication(inputs, adjudication)
    assert len(result) == 1
    r = result[0]
    assert r.category == "unsupported_assertion"
    assert r.evidence == inputs[0].evidence
    assert r.source_agent == "CrossDocChecker"
    assert r.confidence == 1.0
    assert r.duplicate_of is None


def test_sanitize_restores_omitted():
    inputs = [_finding("finding-1", evidence=[])]
    result = _sanitize_adjudication(inputs, Adjudication(findings=[]))
    assert len(result) == 1
    assert result[0].finding_id == "finding-1"


def test_sanitize_rejects_self_duplicate():
    inputs = [_finding("finding-1")]
    adjudication = Adjudication(
        findings=[_adj("finding-1", duplicate_of="finding-1")]
    )
    result = _sanitize_adjudication(inputs, adjudication)
    assert result[0].duplicate_of is None
    live = [f for f in result if f.duplicate_of is None]
    assert len(live) == 1


def test_sanitize_rejects_cycle():
    inputs = [_finding("finding-1"), _finding("finding-2")]
    adjudication = Adjudication(
        findings=[
            _adj("finding-1", duplicate_of="finding-2"),
            _adj("finding-2", duplicate_of="finding-1"),
        ]
    )
    result = _sanitize_adjudication(inputs, adjudication)
    by_id = {f.finding_id: f for f in result}
    assert by_id["finding-1"].duplicate_of is None
    assert by_id["finding-2"].duplicate_of is None
    live = [f for f in result if f.duplicate_of is None]
    assert len(live) == 2


def test_sanitize_rewrites_chain_to_earlier_canonical():
    inputs = [
        _finding("finding-1"),
        _finding("finding-2"),
        _finding("finding-3"),
    ]
    adjudication = Adjudication(
        findings=[
            _adj("finding-1", duplicate_of=None),
            _adj("finding-2", duplicate_of="finding-1"),
            _adj("finding-3", duplicate_of="finding-2"),
        ]
    )
    result = _sanitize_adjudication(inputs, adjudication)
    by_id = {f.finding_id: f for f in result}
    assert by_id["finding-1"].duplicate_of is None
    assert by_id["finding-2"].duplicate_of == "finding-1"
    assert by_id["finding-3"].duplicate_of == "finding-1"
    live = [f for f in result if f.duplicate_of is None]
    assert [f.finding_id for f in live] == ["finding-1"]


def test_sanitize_rejects_forward_duplicate():
    inputs = [_finding("finding-1"), _finding("finding-2")]
    adjudication = Adjudication(
        findings=[
            _adj("finding-1", duplicate_of="finding-2"),
            _adj("finding-2", duplicate_of=None),
        ]
    )
    result = _sanitize_adjudication(inputs, adjudication)
    by_id = {f.finding_id: f for f in result}
    assert by_id["finding-1"].duplicate_of is None
    assert by_id["finding-2"].duplicate_of is None


def test_assemble_verifier_none_covers_all_citations():
    citations = CitationExtraction(
        citations=[
            _citation("c1", full_citation="Alpha v. Beta, 1 Cal.4th 1"),
            _citation("c2", full_citation="Gamma v. Delta, 2 Cal.4th 2"),
        ],
        uncited_legal_assertions=[],
    )
    findings, cnv, _notes = _assemble(citations, None, None, None)
    assert findings == []
    assert len(cnv) == 2
    assert all(f.source_agent == "CitationVerifier" for f in cnv)
    assert all(f.category == "could_not_verify" for f in cnv)


def test_assemble_quotes_none_covers_quoted_citations():
    citations = CitationExtraction(
        citations=[
            _citation("c1", quoted_text="the holding of the court"),
            _citation("c2", quoted_text=None),
            _citation("c3", quoted_text="another quoted passage"),
        ],
        uncited_legal_assertions=[],
    )
    _findings, cnv, _notes = _assemble(citations, None, None, None)
    quote_cnv = [f for f in cnv if f.source_agent == "QuoteChecker"]
    verifier_cnv = [f for f in cnv if f.source_agent == "CitationVerifier"]
    assert len(verifier_cnv) == 3
    assert len(quote_cnv) == 2


def test_assemble_quotes_omission_covers_missing_check():
    citations = CitationExtraction(
        citations=[
            _citation("c1", quoted_text="the holding of the court"),
            _citation("c2", quoted_text="another quoted passage"),
        ],
        uncited_legal_assertions=[],
    )
    quotes = QuoteChecking(
        checks=[
            QuoteCheck(
                citation_id="c1",
                quoted_text="the holding of the court",
                verdict="accurate",
                known_actual_language=None,
                reasoning="Matches.",
                confidence="high",
            )
        ]
    )
    _findings, cnv, _notes = _assemble(citations, None, quotes, None)
    quote_cnv = [f for f in cnv if f.source_agent == "QuoteChecker"]
    assert len(quote_cnv) == 1
    assert "c2" in quote_cnv[0].title or "Smith" in quote_cnv[0].title


def test_quote_grounded_rejects_empty():
    doc = "some document text that is long enough"
    assert quote_grounded("", doc) is False
    assert quote_grounded("   ", doc) is False
    assert quote_grounded("\t\n", doc) is False


def test_evidence_grounded_rejects_empty_list():
    ok, bad = evidence_grounded([], {"doc": "text"})
    assert ok is False
    assert bad == ["<empty evidence>"]


def test_filter_ungrounded_drops_empty_evidence():
    docs = {"motion_for_summary_judgment": "real text in document"}
    findings = [
        Finding(
            finding_id="f1",
            category="unsupported_assertion",
            severity="medium",
            title="Empty",
            description="D",
            brief_location="S",
            evidence=[],
            source_agent="X",
        ),
        Finding(
            finding_id="f2",
            category="unsupported_assertion",
            severity="medium",
            title="Empty quote",
            description="D",
            brief_location="S",
            evidence=[EvidenceQuote(document="motion_for_summary_judgment", quote="")],
            source_agent="X",
        ),
    ]
    kept, dropped = _filter_ungrounded(findings, docs)
    assert dropped == 2
    assert len(kept) == 0


def test_filter_ungrounded_drops_bad_evidence():
    docs = {"motion_for_summary_judgment": "real text in document"}
    findings = [
        Finding(
            finding_id="f1",
            category="unsupported_assertion",
            severity="medium",
            title="Bad",
            description="D",
            brief_location="S",
            evidence=[EvidenceQuote(document="unknown_doc", quote="fake")],
            source_agent="X",
        )
    ]
    kept, dropped = _filter_ungrounded(findings, docs)
    assert dropped == 1
    assert len(kept) == 0


def test_annotate_stage_notes_split_by_stage():
    stages = [
        StageStatus(name="CitationVerifier", state="ok", error=None, duration_ms=1),
        StageStatus(name="QuoteChecker", state="ok", error=None, duration_ms=1),
    ]
    _annotate_stage_notes(
        stages,
        {"unknown_verdict_ids": 2, "unknown_quote_ids": 3},
    )
    assert "verdict" in (stages[0].note or "")
    assert "quote" not in (stages[0].note or "")
    assert "quote" in (stages[1].note or "")
    assert "verdict" not in (stages[1].note or "")
    assert stages[0].error is None
    assert stages[1].error is None


def test_assemble_backfill_marks_backfilled():
    citations = CitationExtraction(
        citations=[
            _citation("c1", full_citation="Alpha v. Beta, 1 Cal.4th 1"),
        ],
        uncited_legal_assertions=[],
    )
    _findings, cnv, _notes = _assemble(citations, None, None, None)
    assert len(cnv) == 1
    assert cnv[0].backfilled is True


def test_truncated_stage_fails_without_retry():
    from llm import LLMCallError

    def truncated():
        raise LLMCallError("truncated", "incomplete response: max_output_tokens")

    stages = []
    assert _run_stage("Probe", truncated, stages, retries=0) is None
    assert len(stages) == 1
    assert stages[0].state == "failed"
    assert "truncated" in (stages[0].error or "")


def test_pipeline_status_failed():
    stages = [
        StageStatus(name="CitationExtractor", state="failed", error="x", duration_ms=1),
        StageStatus(name="CrossDocChecker", state="failed", error="x", duration_ms=1),
    ]
    assert _pipeline_status(stages, [], []) == "failed"


def main() -> int:
    test_sanitize_restores_missing_and_clamps()
    test_sanitize_restores_omitted()
    test_sanitize_rejects_self_duplicate()
    test_sanitize_rejects_cycle()
    test_sanitize_rewrites_chain_to_earlier_canonical()
    test_sanitize_rejects_forward_duplicate()
    test_assemble_verifier_none_covers_all_citations()
    test_assemble_quotes_none_covers_quoted_citations()
    test_assemble_quotes_omission_covers_missing_check()
    test_quote_grounded_rejects_empty()
    test_evidence_grounded_rejects_empty_list()
    test_filter_ungrounded_drops_empty_evidence()
    test_filter_ungrounded_drops_bad_evidence()
    test_annotate_stage_notes_split_by_stage()
    test_assemble_backfill_marks_backfilled()
    test_truncated_stage_fails_without_retry()
    test_pipeline_status_failed()
    print("All orchestrator probe tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
