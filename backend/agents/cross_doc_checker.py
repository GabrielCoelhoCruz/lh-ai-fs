"""Agent 4 — CrossDocChecker.

Extracts the brief's material factual claims and checks each one against the
rest of the case file (police report, medical records, witness statement).
This agent works only with the documents provided — no outside knowledge —
and must quote its evidence verbatim so findings are mechanically auditable.
"""

from llm import MODEL_REASONING, call_structured
from schemas import CrossDocCheck

PROMPT = """You are a fact-consistency auditor. You will receive a legal brief and the source documents from the same case file. Extract every material factual claim the brief makes, then check each claim against the source documents.

A material factual claim is a statement of fact the brief relies on: dates, times, locations, who employed whom, who directed the work, equipment and PPE worn, inspection and safety records, the plaintiff's experience, injuries, filing dates. Include the claims in the "Statement of Undisputed Material Facts" and factual assertions embedded in argument sections. Do not treat pure legal argument as factual claims.

For each claim, return:

1. claim_text — the claim VERBATIM from the brief.
2. brief_location — where it appears (e.g. "Section II, Fact 4").
3. status — one of:
   - "consistent": source documents affirmatively corroborate the claim.
   - "contradicted": at least one source document states something incompatible with the claim.
   - "unsupported": the brief asserts the claim as established fact, but no source document provides any basis for it (e.g. a specific tenure or qualification no document mentions).
   - "could_not_verify": the claim concerns something outside what these documents could show (e.g. internal company programs, inspection histories not in the file). This is a statement about the file's coverage, not a flaw.
4. evidence — for "consistent" and "contradicted", VERBATIM quotes from the source documents, each tagged with the document it came from. Copy the exact words — these quotes are checked mechanically against the source text, and a quote that does not appear in the document invalidates the finding. For "unsupported" and "could_not_verify", evidence may be empty.
5. reasoning — one to three sentences. For dates, do the arithmetic explicitly. For contradictions, state exactly which words conflict.
6. confidence — "high" when the documents speak directly; "medium"/"low" when inference is required.

Rules:
- Audit ONLY the brief's claims. Internal inconsistencies between or within the source documents themselves are out of scope — do not report them.
- Pay attention to what the brief OMITS: if source documents contain facts that directly undercut a claim's framing (e.g. who directed the work, safety concerns raised before an incident, actions taken afterwards), attach them as evidence to the relevant contradicted claim and explain the omission in reasoning.
- Check every date the brief states against every date the source documents state, including sequences that make a claimed date impossible (an event cannot follow another that depends on it).
- Report consistent claims too — completeness matters, and downstream consumers must know what was checked and held up.
"""


def check_facts(
    brief_text: str, source_documents: dict[str, str]
) -> CrossDocCheck:
    sources = "\n\n".join(
        f"===== SOURCE DOCUMENT: {name} =====\n{text}"
        for name, text in sorted(source_documents.items())
    )
    user = (
        f"===== BRIEF UNDER REVIEW: motion_for_summary_judgment =====\n"
        f"{brief_text}\n\n{sources}"
    )
    return call_structured(
        system=PROMPT,
        user=user,
        response_model=CrossDocCheck,
        model=MODEL_REASONING,
        effort="medium",
    )
