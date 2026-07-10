"""Eval harness for the BS Detector pipeline.

    python run_evals.py [--runs N] [--report PATH]

Runs the pipeline against the case file and scores the output against the
ground-truth gold set (evals/gold.json). Three headline metrics:

- recall        — of the 12 known planted flaws, how many were caught.
                  The footnote string cite (F9) is scored fractionally
                  (flagged cases / 6) so bulk-fabrication detection is not
                  all-or-nothing.
- precision     — of the findings the pipeline emitted, how many correspond
                  to real flaws. Findings that flag true statements (the
                  gold set's negatives / precision traps) count against it.
- hallucination — fraction of findings whose evidence quotes do NOT appear
                  in the source documents. Checked mechanically, not by an
                  LLM: a finding citing evidence that isn't in the file is a
                  fabricated finding regardless of how plausible it sounds.

Also reported: uncertainty handling — the two claims that cannot be checked
against the file (OSHA inspection record, IIPP) must surface as
could-not-verify, not as flaw findings and not as silent omissions.

Matching strategy: citation-level gold items are matched deterministically by
case name; everything else is matched by an LLM judge that maps each finding
to a gold id (or none). Judge mistakes are possible; results.json records the
full mapping so every score is auditable.

Scoring conventions (decided up front, documented in gold.json):
- For citations that do not exist, either "likely_fabricated" or an honest
  "could_not_verify" counts as correct — the pipeline has no legal database,
  and a confident fabricated *holding* is the failure mode we punish, not
  honest uncertainty.
- Duplicate-marked findings are excluded from precision (dedup is the
  adjudicator doing its job, not a false positive).
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from llm import MODEL_REASONING, call_structured
from main import load_documents
from orchestrator import run_pipeline
from schemas import VerificationReport

EVALS_DIR = Path(__file__).parent / "evals"
GOLD_PATH = EVALS_DIR / "gold.json"


# ---------------------------------------------------------------------------
# Evidence grounding (deterministic hallucination check)
# ---------------------------------------------------------------------------


def _norm(s: str) -> str:
    s = s.lower()
    for a, b in [
        ("‘", "'"), ("’", "'"), ("“", '"'), ("”", '"'),
        ("—", "-"), ("–", "-"), ("…", "..."),
    ]:
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip()


def quote_grounded(quote: str, document_text: str) -> bool:
    """True if the quote appears in the document (ellipsis-elided quotes are
    checked segment by segment)."""
    doc = _norm(document_text)
    segments = [seg.strip(" .\"'") for seg in _norm(quote).split("...")]
    segments = [seg for seg in segments if len(seg) >= 12] or [
        _norm(quote).strip(" .\"'")
    ]
    return all(seg in doc for seg in segments)


# ---------------------------------------------------------------------------
# LLM judge (maps findings to gold ids)
# ---------------------------------------------------------------------------


class GoldMatch(BaseModel):
    finding_id: str
    gold_id: str | None  # a positive id, a negative id, or null for no match


class JudgeOutput(BaseModel):
    matches: list[GoldMatch]


JUDGE_PROMPT = """You are scoring a legal-verification pipeline against a ground-truth gold set. You receive (a) gold items — real flaws ("positives") and true statements that must not be flagged ("negatives") — and (b) the findings the pipeline produced.

For EACH finding, decide which single gold item it corresponds to:
- a positive id, if the finding describes the same underlying defect (same claim, same documents, same problem — the wording need not match);
- a negative id, if the finding flags something the gold set marks as true/consistent (a false positive);
- null, if the finding matches nothing in the gold set.

Rules: be strict — partial topical overlap is not a match; the defect itself must be the same. One gold id per finding. Never invent gold ids."""


def judge_matches(gold: dict, findings: list[dict]) -> dict[str, str | None]:
    payload = {
        "gold_positives": [
            {"id": p["id"], "summary": p["summary"]} for p in gold["positives"]
        ],
        "gold_negatives": [
            {"id": n["id"], "summary": n["summary"]} for n in gold["negatives"]
        ],
        "pipeline_findings": findings,
    }
    result = call_structured(
        system=JUDGE_PROMPT,
        user=json.dumps(payload, indent=2),
        response_model=JudgeOutput,
        model=MODEL_REASONING,
        effort="medium",
    )
    return {m.finding_id: m.gold_id for m in result.matches}


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _mentions(item_texts: list[str], names: list[str]) -> bool:
    blob = _norm(" ".join(item_texts))
    return any(_norm(n) in blob for n in names)


def score_report(report: VerificationReport, gold: dict, documents: dict) -> dict:
    live = [f for f in report.findings if f.duplicate_of is None]
    cnv = report.could_not_verify

    finding_texts = {
        f.finding_id: [f.title, f.description] + [e.quote for e in f.evidence]
        for f in live
    }
    cnv_texts = {
        f.finding_id: [f.title, f.description] + [e.quote for e in f.evidence]
        for f in cnv
    }

    # --- deterministic citation matching -----------------------------------
    matched: dict[str, str | None] = {}
    credit: dict[str, float] = {p["id"]: 0.0 for p in gold["positives"]}

    for p in gold["positives"]:
        names = p.get("citation_names")
        if not names:
            continue
        hits_findings = [
            fid
            for fid, texts in finding_texts.items()
            if _mentions(texts, names)
            and next(f for f in live if f.finding_id == fid).category
            in p["categories"]
        ]
        hits_cnv = (
            [fid for fid, texts in cnv_texts.items() if _mentions(texts, names)]
            if p.get("cnv_acceptable")
            else []
        )
        if p.get("fractional"):
            flagged_names = {
                n
                for n in names
                if any(
                    _mentions(texts, [n])
                    for texts in list(finding_texts.values()) + list(cnv_texts.values())
                )
            }
            credit[p["id"]] = len(flagged_names) / len(names)
        elif hits_findings or hits_cnv:
            credit[p["id"]] = 1.0
        for fid in hits_findings:
            matched[fid] = p["id"]

    # --- LLM judge for the rest --------------------------------------------
    unjudged = [
        {
            "finding_id": f.finding_id,
            "category": f.category,
            "title": f.title,
            "description": f.description,
            "brief_location": f.brief_location,
        }
        for f in live
        if f.finding_id not in matched
    ]
    if unjudged:
        judged = judge_matches(gold, unjudged)
        matched.update(judged)

    pos_ids = {p["id"]: p for p in gold["positives"]}
    neg_ids = {n["id"] for n in gold["negatives"]}
    for fid, gid in matched.items():
        if gid in pos_ids and credit[gid] == 0.0:
            f = next(f for f in live if f.finding_id == fid)
            if f.category in pos_ids[gid]["categories"]:
                credit[gid] = 1.0

    # --- precision -----------------------------------------------------------
    tp = fp = 0
    per_finding = []
    for f in live:
        gid = matched.get(f.finding_id)
        is_tp = gid in pos_ids and f.category in pos_ids[gid]["categories"]
        tp += is_tp
        fp += not is_tp
        per_finding.append(
            {
                "finding_id": f.finding_id,
                "category": f.category,
                "title": f.title,
                "matched_gold": gid,
                "counts_as": "TP" if is_tp else ("FP-trap" if gid in neg_ids else "FP"),
            }
        )

    # --- hallucination (mechanical evidence grounding) ----------------------
    ungrounded = []
    for f in live:
        bad = [
            e.quote
            for e in f.evidence
            if e.document in documents
            and not quote_grounded(e.quote, documents[e.document])
        ]
        if bad:
            ungrounded.append({"finding_id": f.finding_id, "quotes": bad})

    # --- uncertainty handling ------------------------------------------------
    cnv_results = {}
    for item in gold["expected_could_not_verify"]:
        in_cnv = any(_mentions(texts, item["match_hints"]) for texts in cnv_texts.values())
        flagged_as_flaw = any(
            _mentions(texts, item["match_hints"]) for texts in finding_texts.values()
        )
        cnv_results[item["id"]] = (
            "correct (could_not_verify)"
            if in_cnv and not flagged_as_flaw
            else ("WRONG: flagged as flaw" if flagged_as_flaw else "missed (silent)")
        )

    n_pos = len(gold["positives"])
    recall = sum(credit.values()) / n_pos
    precision = tp / len(live) if live else 0.0
    halluc = len(ungrounded) / len(live) if live else 0.0

    return {
        "recall": round(recall, 3),
        "precision": round(precision, 3),
        "hallucination_rate": round(halluc, 3),
        "findings_emitted": len(live),
        "duplicates_marked": len(report.findings) - len(live),
        "per_gold_credit": {k: round(v, 3) for k, v in credit.items()},
        "per_finding": per_finding,
        "ungrounded_evidence": ungrounded,
        "uncertainty_handling": cnv_results,
        "stage_states": {s.name: s.state for s in report.stages},
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description="Run BS Detector evals")
    ap.add_argument("--runs", type=int, default=1, help="pipeline runs to score")
    ap.add_argument(
        "--report",
        type=str,
        default=None,
        help="score a saved report JSON instead of running the pipeline",
    )
    args = ap.parse_args()

    gold = json.loads(GOLD_PATH.read_text())
    documents = load_documents()
    results = []

    for i in range(args.runs):
        if args.report:
            raw = json.loads(Path(args.report).read_text())
            report = VerificationReport.model_validate(raw.get("report", raw))
        else:
            print(f"[run {i + 1}/{args.runs}] running pipeline...", flush=True)
            report = run_pipeline(documents)
            out = EVALS_DIR / f"report-run{i + 1}.json"
            out.write_text(json.dumps(report.model_dump(), indent=2))
            print(f"[run {i + 1}] report saved to {out}", flush=True)
        print(f"[run {i + 1}] scoring...", flush=True)
        results.append(score_report(report, gold, documents))
        if args.report:
            break

    agg = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "runs": results,
        "aggregate": {
            m: round(sum(r[m] for r in results) / len(results), 3)
            for m in ("recall", "precision", "hallucination_rate")
        },
    }
    (EVALS_DIR / "results.json").write_text(json.dumps(agg, indent=2))

    print("\n=== BS Detector eval results ===")
    for m, v in agg["aggregate"].items():
        print(f"  {m:20s} {v:.1%}")
    r = results[-1]
    print(f"  findings emitted     {r['findings_emitted']} "
          f"(+{r['duplicates_marked']} marked duplicate)")
    print("\n  per-flaw credit:")
    for gid, c in r["per_gold_credit"].items():
        print(f"    {gid:4s} {c:.2f}")
    print("\n  uncertainty handling:")
    for gid, verdict in r["uncertainty_handling"].items():
        print(f"    {gid:4s} {verdict}")
    if r["ungrounded_evidence"]:
        print("\n  UNGROUNDED EVIDENCE (hallucinations):")
        for u in r["ungrounded_evidence"]:
            print(f"    {u['finding_id']}: {u['quotes'][0][:80]}...")
    print(f"\n  full detail: {EVALS_DIR / 'results.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
