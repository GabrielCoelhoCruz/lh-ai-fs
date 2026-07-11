"""Adjudication sanitization: enforce integrity on adjudicator output."""

from __future__ import annotations

from schemas import AdjudicatedFinding, Adjudication, Finding

_FALLBACK_CONFIDENCE = {"high": 0.8, "medium": 0.6, "low": 0.4}


def passthrough_adjudication(findings: list[Finding]) -> list[AdjudicatedFinding]:
    """Degraded mode when the adjudicator stage fails: heuristic confidence."""
    return [
        AdjudicatedFinding(
            **f.model_dump(),
            confidence=_FALLBACK_CONFIDENCE[f.severity],
            confidence_reasoning=(
                "Adjudication stage unavailable; heuristic confidence assigned "
                "from severity."
            ),
            duplicate_of=None,
        )
        for f in findings
    ]


def resolve_duplicate_of(
    adj: AdjudicatedFinding,
    by_id: dict[str, AdjudicatedFinding],
    order_index: dict[str, int],
) -> str | None:
    """Return a valid canonical earlier target, or None if the link is invalid.

    Rejects self-references, missing ids, cycles, and targets that are not
    earlier in input order. Chain links are rewritten to the canonical root.
    """
    target = adj.duplicate_of
    if target is None:
        return None
    if target == adj.finding_id or target not in by_id:
        return None

    seen: set[str] = set()
    current: str | None = target
    while current is not None:
        if current == adj.finding_id or current in seen:
            return None
        if current not in by_id:
            return None
        if order_index[current] >= order_index[adj.finding_id]:
            return None
        node = by_id[current]
        if node.duplicate_of is None:
            return current
        seen.add(current)
        current = node.duplicate_of
    return None


def sanitize_adjudication(
    input_findings: list[Finding],
    adjudication: Adjudication | None,
) -> list[AdjudicatedFinding]:
    """Enforce semantic integrity on adjudicator output."""
    if not input_findings:
        return []

    if adjudication is None or not adjudication.findings:
        return passthrough_adjudication(input_findings)

    by_input = {f.finding_id: f for f in input_findings}
    by_output: dict[str, AdjudicatedFinding] = {}

    for adj in adjudication.findings:
        if adj.finding_id not in by_input:
            continue
        src = by_input[adj.finding_id]
        confidence = max(0.0, min(1.0, adj.confidence))
        by_output[adj.finding_id] = AdjudicatedFinding(
            finding_id=src.finding_id,
            category=src.category,
            severity=adj.severity,
            title=adj.title,
            description=adj.description,
            brief_location=src.brief_location,
            evidence=src.evidence,
            source_agent=src.source_agent,
            confidence=confidence,
            confidence_reasoning=adj.confidence_reasoning,
            duplicate_of=adj.duplicate_of,
        )

    result: list[AdjudicatedFinding] = []
    for f in input_findings:
        if f.finding_id in by_output:
            result.append(by_output[f.finding_id])
        else:
            result.append(
                AdjudicatedFinding(
                    **f.model_dump(),
                    confidence=_FALLBACK_CONFIDENCE[f.severity],
                    confidence_reasoning=(
                        "Adjudicator omitted this finding; restored from input."
                    ),
                    duplicate_of=None,
                )
            )

    order_index = {f.finding_id: i for i, f in enumerate(result)}
    by_id = {f.finding_id: f for f in result}
    cleaned: list[AdjudicatedFinding] = []
    for adj in result:
        dup = resolve_duplicate_of(adj, by_id, order_index)
        if dup != adj.duplicate_of:
            cleaned.append(adj.model_copy(update={"duplicate_of": dup}))
        else:
            cleaned.append(adj)
    return cleaned
