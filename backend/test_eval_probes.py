"""Offline scoring probes for eval harness fixes (no LLM required)."""

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from run_evals import EVALS_DIR, score_offline, score_report
from schemas import (
    AdjudicatedFinding,
    EvidenceQuote,
    Finding,
    StageStatus,
    VerificationReport,
)

GOLD = json.loads((Path(__file__).parent / "evals" / "gold.json").read_text())
DOCUMENTS = {
    "motion_for_summary_judgment": "Rivera worked for eight years as a scaffolder.",
    "police_report": "The incident occurred on March 12, 2021.",
}


def _report(findings=None, cnv=None) -> VerificationReport:
    return VerificationReport(
        case_caption="Test",
        document_analyzed="motion_for_summary_judgment",
        pipeline_status="complete",
        findings=findings or [],
        could_not_verify=cnv or [],
        judicial_memo=None,
        stages=[StageStatus(name="Test", state="ok", error=None, duration_ms=0)],
        citations=None,
        citation_verdicts=None,
        dropped_ungrounded=0,
        model_fast="test",
        model_reasoning="test",
    )


def test_f10_cnv_credit():
    cnv = [
        Finding(
            finding_id="f1",
            category="could_not_verify",
            severity="low",
            title="Could not verify tenure",
            description="No record support for experience claim.",
            brief_location="Section II",
            evidence=[
                EvidenceQuote(
                    document="motion_for_summary_judgment",
                    quote="eight years of experience",
                )
            ],
            source_agent="CrossDocChecker",
        )
    ]
    result = score_report(_report(cnv=cnv), GOLD, DOCUMENTS, use_judge=False)
    assert result["per_gold_credit"]["F10"] == 1.0, result["per_gold_credit"]


def test_f9_fractional_requires_category():
    findings = [
        AdjudicatedFinding(
            finding_id="f1",
            category="cross_document_contradiction",
            severity="high",
            title="Mentions Torres",
            description="Wrong category for F9.",
            brief_location="fn1",
            evidence=[
                EvidenceQuote(document="motion_for_summary_judgment", quote="Torres v. X")
            ],
            source_agent="CrossDocChecker",
            confidence=0.9,
            confidence_reasoning="test",
            duplicate_of=None,
        )
    ]
    result = score_report(_report(findings=findings), GOLD, DOCUMENTS, use_judge=False)
    assert result["per_gold_credit"]["F9"] == 0.0, result["per_gold_credit"]


def test_unknown_doc_counts_as_hallucination():
    findings = [
        AdjudicatedFinding(
            finding_id="f1",
            category="unsupported_assertion",
            severity="medium",
            title="Bad evidence doc",
            description="Cites unknown document.",
            brief_location="Section II",
            evidence=[
                EvidenceQuote(document="nonexistent_doc", quote="fabricated quote here")
            ],
            source_agent="CrossDocChecker",
            confidence=0.8,
            confidence_reasoning="test",
            duplicate_of=None,
        )
    ]
    result = score_report(_report(findings=findings), GOLD, DOCUMENTS, use_judge=False)
    assert result["hallucination_rate"] == 1.0, result
    assert len(result["ungrounded_evidence"]) == 1


def test_backfilled_cnv_does_not_earn_credit():
    """Stage-failure backfill must not score as honest could-not-verify."""
    cnv = [
        Finding(
            finding_id="f1",
            category="could_not_verify",
            severity="low",
            title="No verification produced for authority: Kellerman v. X",
            description="CitationVerifier did not return a verdict for this extracted citation.",
            brief_location="Section III",
            evidence=[
                EvidenceQuote(
                    document="motion_for_summary_judgment",
                    quote="Kellerman v. Harmon Industries",
                )
            ],
            source_agent="CitationVerifier",
            backfilled=True,
        )
    ]
    result = score_report(_report(cnv=cnv), GOLD, DOCUMENTS, use_judge=False)
    assert result["per_gold_credit"]["F7"] == 0.0, result["per_gold_credit"]
    assert result["backfill_excluded"] == 1


def test_offline_skips_judge():
    findings = [
        AdjudicatedFinding(
            finding_id="f1",
            category="cross_document_contradiction",
            severity="high",
            title="March 14 date wrong",
            description="Incident date contradicts records.",
            brief_location="Section II",
            evidence=[
                EvidenceQuote(
                    document="motion_for_summary_judgment",
                    quote="March 14, 2021",
                )
            ],
            source_agent="CrossDocChecker",
            confidence=0.95,
            confidence_reasoning="test",
            duplicate_of=None,
        )
    ]
    result = score_report(_report(findings=findings), GOLD, DOCUMENTS, use_judge=False)
    assert result["per_finding"][0]["matched_gold"] is None
    assert result["per_finding"][0]["counts_as"] == "FP"


def test_offline_report_does_not_overwrite_results_json():
    """--report must write results-offline-*.json, never clobber results.json."""
    live = EVALS_DIR / "results.json"
    before = live.read_bytes() if live.exists() else None
    before_hash = hashlib.sha256(before).hexdigest() if before else None

    report = EVALS_DIR / "report-run1.json"
    assert report.exists(), "committed report-run1.json required for this probe"

    offline_out = EVALS_DIR / "results-offline-report-run1.json"
    if offline_out.exists():
        offline_out.unlink()

    score_offline(str(report), GOLD, DOCUMENTS)

    assert offline_out.exists()
    after = live.read_bytes() if live.exists() else None
    after_hash = hashlib.sha256(after).hexdigest() if after else None
    assert after_hash == before_hash, "live results.json must be untouched by --report"

    offline_out.unlink(missing_ok=True)


def main() -> int:
    test_f10_cnv_credit()
    test_f9_fractional_requires_category()
    test_unknown_doc_counts_as_hallucination()
    test_backfilled_cnv_does_not_earn_credit()
    test_offline_skips_judge()
    test_offline_report_does_not_overwrite_results_json()
    print("All eval probe tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
