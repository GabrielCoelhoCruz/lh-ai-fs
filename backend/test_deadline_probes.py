"""DeadlineChecker and uncited-assertion merge probes (no LLM required)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from assembly import BRIEF_NAME, assemble, filter_ungrounded
from deadline_check import check_deadline
from schemas import (
    CitationExtraction,
    CrossDocCheck,
    EvidenceQuote,
    FactCheck,
    UncitedLegalAssertion,
)

DOCS_DIR = Path(__file__).parent / "documents"
REAL_BRIEF = (DOCS_DIR / "motion_for_summary_judgment.txt").read_text(
    encoding="utf-8"
)

# Minimal self-contained brief mirroring the planted F12 pattern.
_TIMELY_TIME_BARRED = """\
III. ARGUMENT

D. Rivera's Claims Are Time-Barred

The incident giving rise to this action occurred on March 14, 2021. Rivera did \
not file his complaint until March 10, 2023 — one year and 362 days after the \
incident. Under California Code of Civil Procedure Section 335.1, the statute \
of limitations for personal injury claims is two years. While Rivera's filing \
falls nominally within this window, Harmon reserves the right to challenge the \
accrual date.

IV. CONCLUSION
"""

_LATE_FILING = """\
III. ARGUMENT

D. Rivera's Claims Are Time-Barred

The incident giving rise to this action occurred on March 14, 2019. Rivera did \
not file his complaint until March 10, 2023. Under California Code of Civil \
Procedure Section 335.1, the statute of limitations for personal injury claims \
is two years. While Rivera's filing falls nominally within this window, Harmon \
reserves the right to challenge the accrual date.

IV. CONCLUSION
"""

_MISSING_DATES = """\
III. ARGUMENT

D. Rivera's Claims Are Time-Barred

Under California Code of Civil Procedure Section 335.1, the statute of \
limitations for personal injury claims is two years. While Rivera's filing \
falls nominally within this window, Harmon reserves the right to challenge \
the accrual date.

IV. CONCLUSION
"""


def test_timely_but_time_barred_emits_misleading_framing():
    finding = check_deadline(_TIMELY_TIME_BARRED)
    assert finding is not None
    assert finding.category == "misleading_framing"
    assert finding.source_agent == "DeadlineChecker"
    assert finding.severity == "high"
    assert "time-barred" in finding.description.lower()
    assert "statute of limitations" in finding.description.lower()
    assert "self-defeating" in finding.description.lower()
    assert "within this window" in finding.description.lower()
    for eq in finding.evidence:
        assert eq.quote in _TIMELY_TIME_BARRED
        assert eq.document == BRIEF_NAME


def test_genuinely_late_filing_returns_none():
    assert check_deadline(_LATE_FILING) is None


def test_missing_dates_returns_none():
    assert check_deadline(_MISSING_DATES) is None


def test_real_brief_finding_survives_filter_ungrounded():
    finding = check_deadline(REAL_BRIEF)
    assert finding is not None
    assert finding.category == "misleading_framing"
    for eq in finding.evidence:
        assert eq.quote in REAL_BRIEF
    kept, dropped = filter_ungrounded(
        [finding],
        {BRIEF_NAME: REAL_BRIEF},
    )
    assert dropped == 0
    assert len(kept) == 1
    assert kept[0].category == "misleading_framing"


def test_assemble_merges_multiple_uncited_assertions():
    texts = [
        "Assumption of risk bars recovery for known scaffolding hazards.",
        "A trained professional accepts inherent trade risks.",
        "Voluntary encounter of a known danger precludes recovery.",
    ]
    citations = CitationExtraction(
        citations=[],
        uncited_legal_assertions=[
            UncitedLegalAssertion(
                assertion_id=f"u{i}",
                text=t,
                brief_location=f"Section III.C, paragraph {i}",
            )
            for i, t in enumerate(texts, start=1)
        ],
    )
    findings, _cnv, _notes = assemble(citations, None, None, None)
    uncited_findings = [
        f for f in findings if f.source_agent == "CitationExtractor"
    ]
    assert len(uncited_findings) == 1
    merged = uncited_findings[0]
    assert merged.category == "unsupported_assertion"
    assert len(merged.evidence) == 3
    for t, eq in zip(texts, merged.evidence):
        assert eq.quote == t
        assert eq.document == BRIEF_NAME
    for t in texts:
        assert t in merged.description


def test_assemble_single_uncited_assertion_unchanged():
    text = "Assumption of risk bars recovery for known scaffolding hazards."
    citations = CitationExtraction(
        citations=[],
        uncited_legal_assertions=[
            UncitedLegalAssertion(
                assertion_id="u1",
                text=text,
                brief_location="Section III.C",
            )
        ],
    )
    findings, _cnv, _notes = assemble(citations, None, None, None)
    uncited_findings = [
        f for f in findings if f.source_agent == "CitationExtractor"
    ]
    assert len(uncited_findings) == 1
    f = uncited_findings[0]
    assert f.brief_location == "Section III.C"
    assert len(f.evidence) == 1
    assert f.evidence[0].quote == text
    assert "Uncited assertions:" not in f.description


def test_deadline_id_stays_unique_against_cnv_sequence():
    """Regression: do not stamp deadline as finding-{len(findings)+1}.

    assemble() shares one sequence across findings and CNV. Renumbering
    deadline from findings alone can collide with an existing id and
    double-count TPs in the eval scorer. Keep the stable finding-deadline id.
    """
    # 18 CNV rows consume finding-1..finding-18; one real finding is finding-19.
    facts = CrossDocCheck(
        facts=[
            FactCheck(
                fact_id=f"cnv-{i}",
                claim_text=f"Uncheckable claim number {i} about OSHA records.",
                brief_location=f"Section II, para {i}",
                status="could_not_verify",
                evidence=[],
                reasoning="Outside case file",
                confidence="low",
            )
            for i in range(1, 19)
        ]
        + [
            FactCheck(
                fact_id="real-1",
                claim_text="Rivera wore no PPE at the time of the incident.",
                brief_location="Section II",
                status="contradicted",
                evidence=[
                    EvidenceQuote(
                        document="police_report",
                        quote="Rivera was wearing a hard hat and safety harness",
                    )
                ],
                reasoning="Police report contradicts",
                confidence="high",
            )
        ]
    )
    findings, cnv, _notes = assemble(None, None, None, facts)
    assert any(f.finding_id == "finding-19" for f in findings)
    assert len(cnv) == 18

    # Old footgun: len(findings)+1 ignores CNV sequence → collides with an
    # already-issued id (here finding-2 in CNV; with a longer findings list
    # the same formula produced the committed finding-19 doubles).
    existing = {f.finding_id for f in findings} | {f.finding_id for f in cnv}
    old_id = f"finding-{len(findings) + 1}"
    assert old_id in existing

    deadline = check_deadline(_TIMELY_TIME_BARRED)
    assert deadline is not None
    # Mirror the fixed orchestrator path: append as-is (no renumber).
    findings.append(deadline)

    all_ids = [f.finding_id for f in findings] + [f.finding_id for f in cnv]
    assert len(all_ids) == len(set(all_ids)), (
        f"duplicate finding_ids: "
        f"{[i for i in all_ids if all_ids.count(i) > 1]}"
    )
    deadline_rows = [f for f in findings if f.source_agent == "DeadlineChecker"]
    assert len(deadline_rows) == 1
    assert deadline_rows[0].finding_id == "finding-deadline"


def test_contradicted_without_source_evidence_becomes_cnv():
    facts = CrossDocCheck(
        facts=[
            FactCheck(
                fact_id="bare",
                claim_text="The scaffold was inspected the morning of the incident.",
                brief_location="Section II",
                status="contradicted",
                evidence=[],
                reasoning="Model asserted contradiction without quotes",
                confidence="high",
            )
        ]
    )
    findings, cnv, _notes = assemble(None, None, None, facts)
    assert findings == []
    assert len(cnv) == 1
    assert cnv[0].category == "could_not_verify"
    assert "without source evidence" in cnv[0].title.lower()


def main() -> int:
    test_timely_but_time_barred_emits_misleading_framing()
    test_genuinely_late_filing_returns_none()
    test_missing_dates_returns_none()
    test_real_brief_finding_survives_filter_ungrounded()
    test_assemble_merges_multiple_uncited_assertions()
    test_assemble_single_uncited_assertion_unchanged()
    test_deadline_id_stays_unique_against_cnv_sequence()
    test_contradicted_without_source_evidence_becomes_cnv()
    print("All deadline/merge probe tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
