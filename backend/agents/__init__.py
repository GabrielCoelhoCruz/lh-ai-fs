"""BS Detector pipeline agents.

Six LLM agents with distinct, non-overlapping roles (plus deterministic `DeadlineChecker` in the orchestrator):

1. CitationExtractor    — brief text -> structured citation inventory
2. CitationVerifier     — does each cited authority exist / support the claim?
3. QuoteChecker         — are direct quotes accurate to the cited authority?
4. CrossDocChecker      — do the brief's factual claims match the case file?
5. ConfidenceAdjudicator — dedupe findings, score confidence with reasoning
6. JudicialMemoWriter   — one-paragraph synthesis for the court

Agents communicate exclusively through the Pydantic models in schemas.py.
"""

from agents.citation_extractor import extract_citations
from agents.citation_verifier import verify_citations
from agents.confidence_adjudicator import adjudicate
from agents.cross_doc_checker import check_facts
from agents.judicial_memo import write_memo
from agents.quote_checker import check_quotes

__all__ = [
    "extract_citations",
    "verify_citations",
    "check_quotes",
    "check_facts",
    "adjudicate",
    "write_memo",
]
