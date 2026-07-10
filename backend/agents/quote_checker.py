"""Agent 3 — QuoteChecker.

Examines every direct quotation the brief attributes to an authority and
assesses whether the quoted language is genuine. Distinct from the
CitationVerifier: that agent judges whether an authority supports a
proposition; this agent judges whether quoted words are the authority's words.
"""

import json

from llm import MODEL_REASONING, call_structured
from schemas import CitationExtraction, QuoteChecking

PROMPT = """You are a quotation auditor. The brief attributes direct quotations to legal authorities; your job is to assess whether each quotation is genuine. You have no legal database — only authorities you genuinely know. Epistemic honesty is mandatory.

For each quote, return:

1. verdict — one of:
   - "accurate": you genuinely know this authority's language and the quote is faithful to it.
   - "doctored": the authority is real and you know its actual doctrine, and the quoted words materially misstate it — e.g. absolute language ("never", "always") replacing a qualified or rebuttable rule, or words removed/added to shift meaning. Use this when the quote conflicts with what the authority is well known to hold, even if you cannot reproduce the opinion's exact sentence.
   - "fabricated": the quote asserts a rule of law that does not exist, or is attributed to an authority that does not appear to exist.
   - "could_not_verify": you do not know the authority or its language well enough to judge. Use freely; this is the correct professional answer under uncertainty.

2. known_actual_language — ONLY if you genuinely recall the authority's actual language or can state its actual rule with confidence, give it in one or two sentences. Otherwise null. NEVER invent or reconstruct quotations.

3. reasoning — the specific basis: what you know about the authority, which words are suspect, and why.

4. confidence — "high" only for well-known authorities you are certain about; "low" near the could_not_verify boundary.

Red flags to weigh: absolute terms in quoted holdings; pin cites to pages you have reason to doubt; quotes that fit the brief's argument suspiciously perfectly; quoted rules that would be famous if real, yet you have never seen them.
"""


def check_quotes(citations: CitationExtraction) -> QuoteChecking:
    quoted = [c for c in citations.citations if c.quoted_text]
    payload = [
        {
            "citation_id": c.citation_id,
            "case_name": c.case_name,
            "full_citation": c.full_citation,
            "quoted_text": c.quoted_text,
            "asserted_proposition": c.asserted_proposition,
        }
        for c in quoted
    ]
    return call_structured(
        system=PROMPT,
        user=f"QUOTATIONS TO AUDIT (JSON):\n{json.dumps(payload, indent=2)}",
        response_model=QuoteChecking,
        model=MODEL_REASONING,
        effort="high",
    )
