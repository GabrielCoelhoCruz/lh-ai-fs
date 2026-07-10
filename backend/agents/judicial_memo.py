"""Agent 6 — JudicialMemoWriter.

Synthesizes the adjudicated findings into a single paragraph a judge could
read in thirty seconds. Consumes only the pipeline's own findings — it adds
no new claims.
"""

import json

from llm import MODEL_REASONING, call_structured
from schemas import AdjudicatedFinding, JudicialMemo

PROMPT = """You are drafting a one-paragraph bench memorandum for a trial judge about defects found in a brief submitted to the court. You will receive the verified findings, ranked by severity and confidence.

Write exactly one paragraph (roughly 100-160 words) that:
- opens with the overall assessment in plain terms;
- identifies the most serious defects concretely (what was claimed, what the record or authority actually shows) — lead with the highest-severity, highest-confidence items;
- notes the scale of any pattern (e.g. how many cited authorities could not be located);
- maintains a formal, neutral register appropriate for chambers; no rhetoric, no advocacy.

Rules:
- Use ONLY the findings provided. Add no facts, citations, or characterizations of your own.
- Reflect stated confidence honestly: findings the pipeline could not fully verify are described as such ("could not be located in available reporters"), not asserted as certainties.
- No bullet points, no headings — a single flowing paragraph.
"""


def write_memo(findings: list[AdjudicatedFinding]) -> JudicialMemo:
    ranked = sorted(
        (f for f in findings if f.duplicate_of is None),
        key=lambda f: ({"high": 0, "medium": 1, "low": 2}[f.severity], -f.confidence),
    )
    payload = [
        {
            "category": f.category,
            "severity": f.severity,
            "confidence": f.confidence,
            "title": f.title,
            "description": f.description,
            "brief_location": f.brief_location,
        }
        for f in ranked
    ]
    return call_structured(
        system=PROMPT,
        user=f"VERIFIED FINDINGS (JSON, ranked):\n{json.dumps(payload, indent=2)}",
        response_model=JudicialMemo,
        model=MODEL_REASONING,
        effort="low",
    )
