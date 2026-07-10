"""Typed data contracts passed between pipeline agents.

Every agent consumes and produces these models — no raw text blobs cross
agent boundaries. Models are OpenAI strict-structured-outputs compatible:
all fields required, optionality expressed as union-with-null, shallow
nesting, no unsupported JSON Schema keywords.
"""

from typing import Literal

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Stage 1 — CitationExtractor
# ---------------------------------------------------------------------------

CitationKind = Literal["case", "statute", "regulation", "other"]


class ExtractedCitation(BaseModel):
    citation_id: str
    kind: CitationKind
    case_name: str | None  # None for statutes
    full_citation: str  # verbatim as it appears in the brief
    reporter: str | None  # e.g. "Cal.4th", "F.2d", "S.W.3d"
    volume: int | None
    first_page: int | None
    pinpoint: str | None
    year: int | None
    quoted_text: str | None  # verbatim quote attributed to this authority, if any
    asserted_proposition: str  # what the brief claims this authority establishes
    brief_location: str  # e.g. "Section III.A, paragraph 1"


class UncitedLegalAssertion(BaseModel):
    assertion_id: str
    text: str  # verbatim legal proposition asserted without any authority
    brief_location: str


class CitationExtraction(BaseModel):
    citations: list[ExtractedCitation]
    uncited_legal_assertions: list[UncitedLegalAssertion]


# ---------------------------------------------------------------------------
# Stage 2 — CitationVerifier
# ---------------------------------------------------------------------------

ExistenceAssessment = Literal["real", "likely_fabricated", "could_not_verify"]
SupportVerdict = Literal[
    "supported",
    "partially_supported",
    "mischaracterized",
    "unsupported",
    "could_not_verify",
]
ConfidenceLevel = Literal["high", "medium", "low"]


class CitationVerdict(BaseModel):
    citation_id: str
    existence: ExistenceAssessment
    existence_reasoning: str
    known_actual_holding: str | None  # only if the case is genuinely known; else None
    support_verdict: SupportVerdict
    support_reasoning: str
    jurisdiction_concern: str | None  # e.g. out-of-state authority in a CA motion
    confidence: ConfidenceLevel


class CitationVerification(BaseModel):
    verdicts: list[CitationVerdict]


# ---------------------------------------------------------------------------
# Stage 3 — QuoteChecker
# ---------------------------------------------------------------------------

QuoteVerdict = Literal["accurate", "doctored", "fabricated", "could_not_verify"]


class QuoteCheck(BaseModel):
    citation_id: str
    quoted_text: str
    verdict: QuoteVerdict
    known_actual_language: str | None  # only if genuinely known; else None
    reasoning: str
    confidence: ConfidenceLevel


class QuoteChecking(BaseModel):
    checks: list[QuoteCheck]


# ---------------------------------------------------------------------------
# Stage 4 — CrossDocChecker
# ---------------------------------------------------------------------------

FactStatus = Literal["consistent", "contradicted", "unsupported", "could_not_verify"]


class EvidenceQuote(BaseModel):
    document: str  # source document stem, e.g. "police_report"
    quote: str  # verbatim excerpt from that document


class FactCheck(BaseModel):
    fact_id: str
    claim_text: str  # verbatim claim from the brief
    brief_location: str
    status: FactStatus
    evidence: list[EvidenceQuote]
    reasoning: str
    confidence: ConfidenceLevel


class CrossDocCheck(BaseModel):
    facts: list[FactCheck]


# ---------------------------------------------------------------------------
# Stage 5 — ConfidenceAdjudicator (operates on assembled findings)
# ---------------------------------------------------------------------------

FindingCategory = Literal[
    "fabricated_citation",
    "doctored_quote",
    "mischaracterized_holding",
    "cross_document_contradiction",
    "unsupported_assertion",
    "misleading_framing",
    "could_not_verify",
]
Severity = Literal["high", "medium", "low"]


class Finding(BaseModel):
    finding_id: str
    category: FindingCategory
    severity: Severity
    title: str
    description: str
    brief_location: str
    evidence: list[EvidenceQuote]
    source_agent: str


class AdjudicatedFinding(BaseModel):
    finding_id: str
    category: FindingCategory
    severity: Severity
    title: str
    description: str
    brief_location: str
    evidence: list[EvidenceQuote]
    source_agent: str
    confidence: float  # 0.0 - 1.0
    confidence_reasoning: str
    duplicate_of: str | None  # finding_id this duplicates, if any


class Adjudication(BaseModel):
    findings: list[AdjudicatedFinding]


# ---------------------------------------------------------------------------
# Stage 6 — JudicialMemoWriter
# ---------------------------------------------------------------------------


class JudicialMemo(BaseModel):
    memo: str  # single paragraph addressed to the court


# ---------------------------------------------------------------------------
# Final report returned by POST /analyze
# ---------------------------------------------------------------------------

StageState = Literal["ok", "failed", "skipped"]


class StageStatus(BaseModel):
    name: str
    state: StageState
    error: str | None
    duration_ms: int


class VerificationReport(BaseModel):
    case_caption: str
    document_analyzed: str
    findings: list[AdjudicatedFinding]
    could_not_verify: list[Finding]
    judicial_memo: str | None
    stages: list[StageStatus]
    model_fast: str
    model_reasoning: str
