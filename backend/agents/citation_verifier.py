"""Agent 2 — CitationVerifier.

For each extracted citation, assesses (a) whether the cited authority appears
to exist and (b) whether it supports the proposition the brief asserts.

The pipeline has no legal database. Verification rides on the model's
knowledge of case law, so the prompt enforces strict uncertainty discipline:
"could_not_verify" is the required answer when the model does not genuinely
recognize an authority — fabricating a holding is the worst possible failure.

A deterministic reporter-series sanity check runs before the LLM call and its
result is passed to the model as a signal (e.g. a year outside the reporter
series' publication range is evidence of fabrication).
"""

import json

from llm import MODEL_REASONING, call_structured
from schemas import CitationExtraction, CitationVerification

# Publication ranges for common reporter series. Deterministic, cheap signal:
# a citation whose year falls outside its reporter's range cannot be real.
REPORTER_YEARS: dict[str, tuple[int, int]] = {
    "F.2d": (1924, 1993),
    "F.3d": (1993, 2021),
    "F.4th": (2021, 2100),
    "F. Supp.": (1932, 1998),
    "F. Supp. 2d": (1998, 2014),
    "F. Supp. 3d": (2014, 2100),
    "Cal.3d": (1969, 1991),
    "Cal.4th": (1991, 2016),
    "Cal.5th": (2016, 2100),
    "Cal.App.4th": (1991, 2016),
    "Cal.App.5th": (2016, 2100),
    "S.W.3d": (1999, 2100),
    "So.3d": (2008, 2100),
}

PROMPT = """You are a legal citation verifier reviewing citations extracted from a brief. You have NO access to a legal database; you may rely only on authorities you genuinely know from your training. Your single most important duty is epistemic honesty: a wrong "real" or an invented holding is far worse than "could_not_verify".

For each citation, return:

1. existence — one of:
   - "real": ONLY if you genuinely recognize this specific case or statute AND the citation details (court, reporter, year) are consistent with what you know. Landmark and frequently-cited authorities qualify; obscure ones rarely do.
   - "likely_fabricated": you do not recognize the case AND there are concrete fabrication signals. Signals include: a reporter-year mismatch flagged in the input; a parenthetical that fits the brief's argument suspiciously well; authority from an irrelevant jurisdiction; a well-known-sounding rule of law that does not actually exist.
   - "could_not_verify": you do not recognize the case and have no concrete signal either way. This is the correct, professional answer for obscure citations — use it freely.

2. existence_reasoning — the specific basis for your assessment. Name the signals you used.

3. known_actual_holding — ONLY if existence is "real" and you genuinely know the holding, summarize it in one or two sentences. Otherwise null. NEVER reconstruct, guess, or improvise a holding.

4. support_verdict — compare the asserted_proposition against what the authority actually holds:
   - "supported": the authority genuinely stands for the proposition.
   - "partially_supported": the authority supports a weaker or narrower version; the brief overstates it (e.g. converting a rebuttable presumption into an absolute rule).
   - "mischaracterized": the authority is real but holds something materially different from the proposition.
   - "unsupported": the proposition finds no footing in the authority at all.
   - "could_not_verify": you cannot assess because you do not know the authority.
   If existence is "likely_fabricated" or "could_not_verify", support_verdict must be "could_not_verify" — you cannot evaluate support against a case you do not know.

5. jurisdiction_concern — if the authority's jurisdiction is irrelevant or non-binding for this brief (e.g. Texas or Florida intermediate appellate cases cited in a California state-law motion), say so in one sentence. Otherwise null.

6. confidence — "high" only when you are certain about a well-known authority; "medium" for solid but not certain assessments; "low" whenever you are near the "could_not_verify" boundary.

Also consider what the brief OMITS: if you know controlling authority that cuts against the proposition (e.g. recognized exceptions to a doctrine the brief presents as absolute), mention it in support_reasoning.
"""


def _reporter_sanity(citations: CitationExtraction) -> list[str]:
    """Return deterministic fabrication signals: year outside reporter range."""
    signals = []
    for c in citations.citations:
        if c.reporter and c.year:
            rng = REPORTER_YEARS.get(c.reporter.strip())
            if rng and not (rng[0] <= c.year <= rng[1]):
                signals.append(
                    f"{c.citation_id}: year {c.year} is outside the publication "
                    f"range of reporter {c.reporter} ({rng[0]}-{rng[1]})"
                )
    return signals


def verify_citations(
    citations: CitationExtraction, brief_context: str
) -> CitationVerification:
    signals = _reporter_sanity(citations)
    signal_block = (
        "\n".join(signals) if signals else "none detected"
    )
    user = (
        "CITATIONS (JSON):\n"
        f"{json.dumps([c.model_dump() for c in citations.citations], indent=2)}\n\n"
        f"DETERMINISTIC REPORTER-RANGE SIGNALS:\n{signal_block}\n\n"
        "BRIEF CONTEXT (for jurisdiction and argument framing):\n"
        f"{brief_context}"
    )
    return call_structured(
        system=PROMPT,
        user=user,
        response_model=CitationVerification,
        model=MODEL_REASONING,
        effort="high",
    )
