"""DeadlineChecker and uncited-assertion merge probes (no LLM required)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from assembly import BRIEF_NAME, filter_ungrounded
from deadline_check import check_deadline

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


def main() -> int:
    test_timely_but_time_barred_emits_misleading_framing()
    test_genuinely_late_filing_returns_none()
    test_missing_dates_returns_none()
    test_real_brief_finding_survives_filter_ungrounded()
    print("All deadline probe tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
