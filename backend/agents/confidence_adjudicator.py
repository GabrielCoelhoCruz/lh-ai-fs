"""Agent 5 — ConfidenceAdjudicator.

Takes the findings assembled from the verification agents, removes
duplicates, and rates how certain the pipeline should be in each finding,
with explicit reasoning. It may not invent findings and may not silently
drop them — duplicates are marked, not deleted, so the audit trail survives.
"""

import json

from llm import MODEL_REASONING, call_structured
from schemas import Adjudication, Finding

PROMPT = """You are the adjudication layer of a legal-brief verification pipeline. You receive findings produced by upstream verification agents. Your job:

1. DEDUPLICATE. If two findings describe the same underlying defect (e.g. a citation agent and a quote agent both flagging the same doctored quotation), keep the most complete one and set duplicate_of on the other(s) to the kept finding's finding_id. Findings about the same brief section but different defects are NOT duplicates.

2. SCORE CONFIDENCE. For each finding assign confidence between 0.0 and 1.0:
   - 0.9-1.0: mechanically checkable and the evidence is verbatim and unambiguous (e.g. a date stated differently across documents).
   - 0.7-0.9: strong evidence with minor interpretation (e.g. a well-known doctrine misstated).
   - 0.4-0.7: reasonable inference; a knowledgeable reviewer could push back.
   - below 0.4: weak or speculative — say why it was kept at all.
   Findings resting on the model's legal knowledge (rather than the provided documents) cap at 0.85 unless the authority is truly canonical.

3. EXPLAIN. confidence_reasoning must state what makes the finding certain or uncertain in one or two sentences — the specific evidence, not generic phrases.

4. ADJUST SEVERITY if clearly miscalibrated: "high" is for defects that would change the motion's outcome or constitute misrepresentation to the court; "medium" for material but arguable defects; "low" for technical or cosmetic issues.

Rules:
- NEVER add findings that are not in the input.
- NEVER remove a finding — mark duplicates instead.
- Keep finding_id, category, brief_location, evidence, and source_agent unchanged. You may tighten title and description for clarity, but do not change their meaning.
"""


def adjudicate(findings: list[Finding]) -> Adjudication:
    payload = json.dumps([f.model_dump() for f in findings], indent=2)
    return call_structured(
        system=PROMPT,
        user=f"FINDINGS TO ADJUDICATE (JSON):\n{payload}",
        response_model=Adjudication,
        model=MODEL_REASONING,
        effort="medium",
    )
