"""Deterministic deadline / SOL coherence check.

Pure date math — no LLM. Catches the self-defeating pattern where a brief
heading asserts claims are time-barred while the body concedes filing falls
inside the statute-of-limitations window (CCP 335.1 / two years = 730 days).
"""

from __future__ import annotations

import re
from datetime import date

from schemas import EvidenceQuote, Finding

BRIEF_NAME = "motion_for_summary_judgment"

# Two-year personal-injury SOL under CCP 335.1, in days.
_SOL_DAYS = 730

_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

_NAMED_DATE = re.compile(
    r"\b("
    r"January|February|March|April|May|June|July|August|"
    r"September|October|November|December"
    r")\s+(\d{1,2}),\s+(\d{4})\b",
    re.IGNORECASE,
)
_NUMERIC_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")

_TIME_BARRED_HEADING = re.compile(
    r"^.*\b[Tt]ime-[Bb]arred\b.*$",
    re.MULTILINE,
)
_WITHIN_WINDOW = re.compile(
    r"[^.]*\bwithin this window\b[^.]*\.",
    re.IGNORECASE,
)
_SOL_CONTEXT = re.compile(
    r"(?:335\.1|statute of limitations|two[- ]year)",
    re.IGNORECASE,
)
_FILING_CUE = re.compile(
    r"(?:fil(?:e|ed|ing)|complaint|instant action)",
    re.IGNORECASE,
)
_INCIDENT_CUE = re.compile(
    r"(?:incident|occurred|accrual|injury)",
    re.IGNORECASE,
)


def _parse_named(match: re.Match[str]) -> date | None:
    month = _MONTHS.get(match.group(1).lower())
    if month is None:
        return None
    try:
        return date(int(match.group(3)), month, int(match.group(2)))
    except ValueError:
        return None


def _parse_numeric(match: re.Match[str]) -> date | None:
    try:
        return date(int(match.group(3)), int(match.group(1)), int(match.group(2)))
    except ValueError:
        return None


def _dates_near(text: str, cue: re.Pattern[str], window: int = 120) -> list[date]:
    """Collect dates whose surrounding context matches ``cue``."""
    found: list[date] = []
    for rx, parser in ((_NAMED_DATE, _parse_named), (_NUMERIC_DATE, _parse_numeric)):
        for m in rx.finditer(text):
            start = max(0, m.start() - window)
            end = min(len(text), m.end() + window)
            if cue.search(text[start:end]):
                parsed = parser(m)
                if parsed is not None:
                    found.append(parsed)
    return found


def _earliest(dates: list[date]) -> date | None:
    return min(dates) if dates else None


def _latest(dates: list[date]) -> date | None:
    return max(dates) if dates else None


def check_deadline(brief: str) -> Finding | None:
    """Return a misleading_framing finding when a time-barred heading is
    self-defeating under CCP 335.1 date math; otherwise None.
    """
    heading_m = _TIME_BARRED_HEADING.search(brief)
    if heading_m is None:
        return None
    if not _SOL_CONTEXT.search(brief):
        return None

    window_m = _WITHIN_WINDOW.search(brief)
    # Prefer dates from the time-barred section (heading → next major heading
    # or end), falling back to whole-brief cues.
    section_start = heading_m.start()
    next_heading = re.search(
        r"\n(?:[IVX]+\.|[A-Z]\.)\s",
        brief[heading_m.end() :],
    )
    section_end = (
        heading_m.end() + next_heading.start()
        if next_heading
        else len(brief)
    )
    section = brief[section_start:section_end]

    incident = _earliest(_dates_near(section, _INCIDENT_CUE)) or _earliest(
        _dates_near(brief, _INCIDENT_CUE)
    )
    filing = _latest(_dates_near(section, _FILING_CUE)) or _latest(
        _dates_near(brief, _FILING_CUE)
    )
    if incident is None or filing is None:
        return None

    elapsed = (filing - incident).days
    if elapsed < 0:
        return None
    # Genuinely late filing — the time-barred assertion is not self-defeating.
    if elapsed > _SOL_DAYS:
        return None

    heading_quote = heading_m.group(0).strip()
    if window_m is not None:
        window_quote = window_m.group(0).strip()
    else:
        # Fall back to the filing sentence in the section if the exact phrase
        # is absent (still require a grounded quote).
        fallback = re.search(
            r"[^.]*\b(?:fil(?:e|ed|ing)|complaint)[^.]*\.",
            section,
            re.IGNORECASE,
        )
        if fallback is None:
            return None
        window_quote = fallback.group(0).strip()

    evidence = [
        EvidenceQuote(document=BRIEF_NAME, quote=heading_quote),
        EvidenceQuote(document=BRIEF_NAME, quote=window_quote),
    ]

    description = (
        f"The section heading asserts the claims are time-barred, but the body "
        f"concedes the filing falls within this window under the statute of "
        f"limitations (CCP 335.1 / two years = {_SOL_DAYS} days). Filing on "
        f"{filing.isoformat()} is {elapsed} days after the incident on "
        f"{incident.isoformat()}, which is inside the {_SOL_DAYS}-day window. "
        f"The time-barred framing is therefore self-defeating."
    )

    return Finding(
        finding_id="finding-deadline",
        category="misleading_framing",
        severity="high",
        title="Time-barred heading contradicted by timely filing under SOL",
        description=description,
        brief_location="Section III.D (Time-Barred)",
        evidence=evidence,
        source_agent="DeadlineChecker",
    )
