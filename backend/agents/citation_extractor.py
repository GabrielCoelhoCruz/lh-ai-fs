"""Agent 1 — CitationExtractor.

Reads the brief and produces a structured inventory of every legal authority
it relies on. Pure extraction: no judgment about whether authorities are real
or correctly used — that belongs to the verifier agents downstream.
"""

from llm import MODEL_FAST, call_structured
from schemas import CitationExtraction

PROMPT = """You are a legal citation extractor. You will receive the full text of a legal brief.

Extract EVERY legal authority the brief cites: cases, statutes, and regulations. Include authorities cited in footnotes. When several cases appear in a single string cite, produce one entry per case.

For each authority record:
- citation_id: "cite-1", "cite-2", ... in order of first appearance.
- kind: "case", "statute", "regulation", or "other".
- case_name: the party caption (e.g. "Privette v. Superior Court"); null for statutes.
- full_citation: the citation VERBATIM as printed in the brief, including reporter, pinpoint, court, and year.
- reporter / volume / first_page / pinpoint / year: parsed components; null for any component not present.
- quoted_text: if the brief attributes a direct quotation to this authority (text inside quotation marks presented as the authority's own words), copy it VERBATIM, without the surrounding quotation marks. Otherwise null. Do not treat the brief's own paraphrase as a quote.
- asserted_proposition: one or two sentences stating what the brief claims this authority establishes. State the brief's claim faithfully, even if you suspect it is wrong.
- brief_location: where the citation appears (e.g. "Section III.A, paragraph 1" or "Footnote 1").

Separately, collect uncited_legal_assertions: statements of legal doctrine or legal rules the brief advances WITHOUT citing any authority (e.g. an entire argument section that states a doctrine and applies it, citing nothing). Record the assertion verbatim and its location. Factual claims are not legal assertions — only statements about what the law is.

Rules:
- Copy text exactly. Never paraphrase inside full_citation, quoted_text, or assertion text.
- Do not skip authorities that look unimportant or duplicative.
- Do not add authorities that are not in the brief.
"""


def extract_citations(brief_text: str) -> CitationExtraction:
    return call_structured(
        system=PROMPT,
        user=f"BRIEF TEXT:\n\n{brief_text}",
        response_model=CitationExtraction,
        model=MODEL_FAST,
        effort="low",
    )
