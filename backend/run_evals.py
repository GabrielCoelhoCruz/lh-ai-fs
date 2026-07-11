"""Eval harness for the BS Detector pipeline.

    python run_evals.py [--runs N] [--report PATH]
    python run_evals.py --smoke
    python run_evals.py --runs 3 --max-api-calls 21

Runs the pipeline against the case file and scores the output against the
ground-truth gold set (evals/gold.json). Three headline metrics:

- recall        — of the 12 known planted flaws, how many were caught.
                  The footnote string cite (F9) is scored fractionally
                  (flagged cases / 6) so bulk-fabrication detection is not
                  all-or-nothing.
- precision     — of the findings the pipeline emitted, how many correspond
                  to real flaws. Findings that flag true statements (the
                  gold set's negatives / precision traps) count against it.
- ungrounded-evidence rate (also labeled hallucination_rate in JSON for
                  continuity) — fraction of findings whose evidence quotes
                  do NOT appear in the source documents. Checked mechanically,
                  not by an LLM: a finding citing evidence that isn't in the
                  file is fabricated evidence regardless of how plausible it
                  sounds. This is not a semantic "hallucination" score.

Also reported: uncertainty handling — the two claims that cannot be checked
against the file (OSHA inspection record, IIPP) must surface as
could-not-verify, not as flaw findings and not as silent omissions.

Matching strategy: citation-level gold items are matched deterministically by
case name; everything else is matched by an LLM judge during live pipeline
runs. Offline rescoring (--report) is deterministic-only and never invokes the
judge; it writes evals/results-offline.json and never overwrites the live
evals/results.json. Judge mistakes are possible on live runs; results.json
records the full mapping so every score is auditable.

Scoring conventions (decided up front, documented in gold.json):
- For citations that do not exist, either "likely_fabricated" or an honest
  "could_not_verify" counts as correct — the pipeline has no legal database,
  and a confident fabricated *holding* is the failure mode we punish, not
  honest uncertainty.
- Duplicate-marked findings are excluded from precision (dedup is the
  adjudicator doing its job, not a false positive).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from grounding import norm, quote_grounded
from llm import (
    MODEL_FAST,
    MODEL_REASONING,
    LLMBudget,
    LLMCallError,
    call_structured,
    llm_run,
    required_api_budget,
)
from main import load_documents
from orchestrator import run_pipeline
from schemas import AdjudicatedFinding, Finding, VerificationReport

EVALS_DIR = Path(__file__).parent / "evals"
GOLD_PATH = EVALS_DIR / "gold.json"

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvalConfig:
    runs: int = 1
    smoke: bool = False
    report: str | None = None
    max_api_calls: int = 7
    sdk_retries: int = 0
    stage_retries: int = 0
    timeout_s: float = 180.0
    max_output_tokens: int = 16000

    @property
    def use_judge(self) -> bool:
        return self.report is None and not self.smoke

    @property
    def mode(self) -> str:
        if self.report:
            return "offline"
        return "smoke" if self.smoke else "full"

    def llm_budget(self) -> LLMBudget:
        return LLMBudget(
            max_api_calls=self.max_api_calls,
            sdk_max_retries=self.sdk_retries,
            timeout_s=self.timeout_s,
            max_output_tokens=self.max_output_tokens,
            model_override=MODEL_FAST if self.smoke else None,
            effort_override="low" if self.smoke else None,
        )

    def required_budget(self) -> int:
        return required_api_budget(
            self.runs,
            use_judge=self.use_judge,
            stage_retries=self.stage_retries,
            sdk_retries=self.sdk_retries,
        )


def parse_args(argv: list[str] | None = None) -> EvalConfig:
    ap = argparse.ArgumentParser(description="Run BS Detector evals")
    ap.add_argument("--runs", type=int, default=1, help="pipeline runs to score")
    ap.add_argument(
        "--report",
        type=str,
        default=None,
        help=(
            "score a saved report JSON instead of running the pipeline; "
            "writes evals/results-offline-<stem>.json (never overwrites "
            "evals/results.json)"
        ),
    )
    ap.add_argument(
        "--smoke",
        action="store_true",
        help=(
            "run once with the fast model, low effort, no retries, and "
            "deterministic scoring"
        ),
    )
    ap.add_argument(
        "--max-api-calls",
        type=int,
        default=7,
        help="hard cap on possible network attempts for the entire command",
    )
    ap.add_argument(
        "--sdk-retries",
        type=int,
        default=0,
        help="OpenAI SDK retries per logical call (default: 0)",
    )
    ap.add_argument(
        "--stage-retries",
        type=int,
        default=0,
        help="whole-stage retries after a terminal SDK failure (default: 0)",
    )
    ap.add_argument(
        "--timeout-s",
        type=float,
        default=None,
        help="timeout per SDK call (default: full 180, smoke 60)",
    )
    ap.add_argument(
        "--max-output-tokens",
        type=int,
        default=None,
        help="hard output/reasoning token cap per call (full 16000, smoke 1200)",
    )
    args = ap.parse_args(argv)

    if args.runs < 1:
        ap.error("--runs must be at least 1")
    if args.max_api_calls < 0 or args.sdk_retries < 0 or args.stage_retries < 0:
        ap.error("call budgets and retry counts must be zero or greater")
    if args.timeout_s is not None and args.timeout_s <= 0:
        ap.error("--timeout-s must be greater than zero")
    if args.max_output_tokens is not None and args.max_output_tokens <= 0:
        ap.error("--max-output-tokens must be greater than zero")
    if args.report and args.smoke:
        ap.error("--report is already offline; do not combine it with --smoke")

    runs = 1 if args.smoke else args.runs
    if args.smoke and args.runs != 1:
        print("[smoke] forcing one run", flush=True)

    smoke = bool(args.smoke)
    timeout_s = (
        args.timeout_s
        if args.timeout_s is not None
        else (60.0 if smoke else 180.0)
    )
    max_output_tokens = (
        args.max_output_tokens
        if args.max_output_tokens is not None
        else (1200 if smoke else 16000)
    )
    return EvalConfig(
        runs=runs,
        smoke=smoke,
        report=args.report,
        max_api_calls=args.max_api_calls,
        sdk_retries=args.sdk_retries,
        stage_retries=args.stage_retries,
        timeout_s=timeout_s,
        max_output_tokens=max_output_tokens,
    )


# ---------------------------------------------------------------------------
# LLM judge (maps findings to gold ids)
# ---------------------------------------------------------------------------


class GoldMatch(BaseModel):
    finding_id: str
    gold_id: str | None


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
        cache=False,
    )
    return {m.finding_id: m.gold_id for m in result.matches}


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _mentions(item_texts: list[str], names: list[str]) -> bool:
    blob = norm(" ".join(item_texts))
    return any(norm(n) in blob for n in names)


def _finding_texts(items: list[AdjudicatedFinding] | list[Finding]) -> dict[str, list[str]]:
    return {
        f.finding_id: [f.title, f.description] + [e.quote for e in f.evidence]
        for f in items
    }


def _match_positive(
    positive: dict,
    live: list[AdjudicatedFinding],
    finding_texts: dict[str, list[str]],
    cnv_texts: dict[str, list[str]],
) -> tuple[float, list[str]]:
    """Return (credit, finding_ids matched to this gold positive)."""
    categories = positive["categories"]
    live_by_id = {f.finding_id: f for f in live}
    names = positive.get("citation_names")

    if names:
        def finding_matches(fid: str, needles: list[str]) -> bool:
            f = live_by_id[fid]
            return f.category in categories and _mentions(finding_texts[fid], needles)

        hits = [fid for fid in finding_texts if finding_matches(fid, names)]
        cnv_hits = (
            [fid for fid, texts in cnv_texts.items() if _mentions(texts, names)]
            if positive.get("cnv_acceptable")
            else []
        )
        if positive.get("fractional"):
            flagged = 0
            for name in names:
                in_findings = any(finding_matches(fid, [name]) for fid in finding_texts)
                in_cnv = positive.get("cnv_acceptable") and any(
                    _mentions(texts, [name]) for texts in cnv_texts.values()
                )
                if in_findings or in_cnv:
                    flagged += 1
            return flagged / len(names), hits

        if hits or cnv_hits:
            return 1.0, hits
        return 0.0, []

    hints = positive.get("match_hints", [])
    if positive.get("cnv_acceptable") and hints:
        if any(_mentions(texts, hints) for texts in cnv_texts.values()):
            return 1.0, []
    return 0.0, []


def score_report(
    report: VerificationReport,
    gold: dict,
    documents: dict,
    *,
    use_judge: bool = True,
) -> dict:
    live = [f for f in report.findings if f.duplicate_of is None]
    cnv_all = report.could_not_verify
    cnv_genuine = [f for f in cnv_all if not f.backfilled]
    backfill_excluded = len(cnv_all) - len(cnv_genuine)
    finding_texts = _finding_texts(live)
    cnv_texts = _finding_texts(cnv_genuine)

    matched: dict[str, str | None] = {}
    credit: dict[str, float] = {p["id"]: 0.0 for p in gold["positives"]}

    for positive in gold["positives"]:
        score, hit_ids = _match_positive(positive, live, finding_texts, cnv_texts)
        credit[positive["id"]] = score
        for fid in hit_ids:
            matched[fid] = positive["id"]

    if use_judge:
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
            matched.update(judge_matches(gold, unjudged))

    pos_ids = {p["id"]: p for p in gold["positives"]}
    neg_ids = {n["id"] for n in gold["negatives"]}
    for fid, gid in matched.items():
        if gid in pos_ids and credit[gid] == 0.0:
            f = next(f for f in live if f.finding_id == fid)
            if f.category in pos_ids[gid]["categories"]:
                credit[gid] = 1.0

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

    ungrounded = []
    for f in live:
        bad = [
            e.quote
            for e in f.evidence
            if e.document not in documents
            or not quote_grounded(e.quote, documents[e.document])
        ]
        if bad:
            ungrounded.append({"finding_id": f.finding_id, "quotes": bad})

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
        "backfill_excluded": backfill_excluded,
        "per_gold_credit": {k: round(v, 3) for k, v in credit.items()},
        "per_finding": per_finding,
        "ungrounded_evidence": ungrounded,
        "uncertainty_handling": cnv_results,
        "stage_states": {s.name: s.state for s in report.stages},
    }


# ---------------------------------------------------------------------------
# Persistence / reporting
# ---------------------------------------------------------------------------


def _write_json(path: Path, payload: dict) -> None:
    """Atomically replace JSON so interruption cannot leave a partial file."""
    temp = path.with_suffix(f"{path.suffix}.tmp")
    temp.write_text(json.dumps(payload, indent=2))
    temp.replace(path)


def _usage_delta(before: dict, after: dict) -> dict:
    counters = (
        "logical_calls",
        "api_attempts_reserved",
        "input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "total_tokens",
    )
    result = {key: after[key] - before[key] for key in counters}
    result["model_override"] = after["model_override"]
    result["effort_override"] = after.get("effort_override")
    result["timeout_s"] = after["timeout_s"]
    result["max_output_tokens"] = after["max_output_tokens"]
    return result


def _aggregate(results: list[dict], usage: dict | None) -> dict:
    aggregate_metrics = {
        metric: round(sum(r[metric] for r in results) / len(results), 3)
        for metric in ("recall", "precision", "hallucination_rate")
    }
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "completed_runs": len(results),
        "runs": results,
        "aggregate": aggregate_metrics,
        "llm_usage": usage,
    }


def _persist_results(
    results: list[dict],
    usage: dict | None,
    *,
    path: Path | None = None,
) -> Path | None:
    if not results:
        return None
    out = path if path is not None else EVALS_DIR / "results.json"
    _write_json(out, _aggregate(results, usage))
    return out


def score_offline(report_path: str, gold: dict, documents: dict) -> list[dict]:
    raw = json.loads(Path(report_path).read_text())
    report = VerificationReport.model_validate(raw.get("report", raw))
    print("[offline] scoring saved report; no API calls", flush=True)
    results = [score_report(report, gold, documents, use_judge=False)]
    stem = Path(report_path).stem
    out = EVALS_DIR / f"results-offline-{stem}.json"
    _persist_results(results, None, path=out)
    print(f"[offline] wrote {out} (live results.json untouched)", flush=True)
    return results


def run_live(
    config: EvalConfig,
    gold: dict,
    documents: dict,
) -> tuple[list[dict], dict | None, int]:
    """Execute live eval runs. Returns (results, usage, exit_code)."""
    required = config.required_budget()
    if required > config.max_api_calls:
        print(
            "Refusing to start before spending tokens: the requested "
            f"configuration could use {required} API attempts, but "
            f"--max-api-calls is {config.max_api_calls}. Raise the cap "
            "explicitly or reduce runs/retries.",
            file=sys.stderr,
        )
        return [], None, 2

    print(
        f"[eval] mode={config.mode} runs={config.runs} max_api_calls="
        f"{config.max_api_calls} sdk_retries={config.sdk_retries} "
        f"stage_retries={config.stage_retries} timeout_s={config.timeout_s} "
        f"max_output_tokens={config.max_output_tokens}",
        flush=True,
    )

    results: list[dict] = []
    usage_snapshot: dict | None = None
    try:
        with llm_run(config.llm_budget()) as usage:
            for i in range(config.runs):
                before = usage.as_dict()
                print(f"[run {i + 1}/{config.runs}] running pipeline...", flush=True)
                report = run_pipeline(
                    documents,
                    stage_retries=config.stage_retries,
                )
                out = EVALS_DIR / f"report-run{i + 1}.json"
                _write_json(out, report.model_dump())
                print(f"[run {i + 1}] report saved to {out}", flush=True)
                print(f"[run {i + 1}] scoring...", flush=True)
                result = score_report(
                    report,
                    gold,
                    documents,
                    use_judge=config.use_judge,
                )
                result["llm_usage"] = _usage_delta(before, usage.as_dict())
                results.append(result)
                usage_snapshot = usage.as_dict()
                _persist_results(results, usage_snapshot)
                print(
                    f"[run {i + 1}] result saved; total_tokens={usage.total_tokens}",
                    flush=True,
                )
    except LLMCallError as exc:
        _persist_results(results, usage_snapshot)
        print(f"Eval stopped safely: {exc}", file=sys.stderr, flush=True)
        return results, usage_snapshot, 2
    except KeyboardInterrupt:
        _persist_results(results, usage_snapshot)
        print(
            "Eval interrupted. Every completed report/result remains saved.",
            file=sys.stderr,
            flush=True,
        )
        return results, usage_snapshot, 130

    return results, usage_snapshot, 0


def print_summary(
    results: list[dict],
    usage_snapshot: dict | None,
    *,
    detail_path: Path | None = None,
) -> None:
    if not results:
        return
    agg = _aggregate(results, usage_snapshot)
    print("\n=== BS Detector eval results ===")
    for metric, value in agg["aggregate"].items():
        label = metric
        if metric == "hallucination_rate":
            label = "ungrounded_evidence"
        print(f"  {label:20s} {value:.1%}")
    last_result = results[-1]
    print(
        f"  findings emitted     {last_result['findings_emitted']} "
        f"(+{last_result['duplicates_marked']} marked duplicate)"
    )
    print("\n  per-flaw credit:")
    for gold_id, credit in last_result["per_gold_credit"].items():
        print(f"    {gold_id:4s} {credit:.2f}")
    print("\n  uncertainty handling:")
    for gold_id, verdict in last_result["uncertainty_handling"].items():
        print(f"    {gold_id:4s} {verdict}")
    if last_result["ungrounded_evidence"]:
        print("\n  UNGROUNDED EVIDENCE (mechanical quote check):")
        for ungrounded in last_result["ungrounded_evidence"]:
            print(
                f"    {ungrounded['finding_id']}: "
                f"{ungrounded['quotes'][0][:80]}..."
            )
    if usage_snapshot is not None:
        print(
            "\n  LLM usage: "
            f"calls={usage_snapshot['logical_calls']} "
            f"reserved_attempts={usage_snapshot['api_attempts_reserved']}/"
            f"{usage_snapshot['max_api_calls']} "
            f"input={usage_snapshot['input_tokens']} "
            f"output={usage_snapshot['output_tokens']} "
            f"reasoning={usage_snapshot['reasoning_tokens']} "
            f"total={usage_snapshot['total_tokens']}"
        )
    path = detail_path if detail_path is not None else EVALS_DIR / "results.json"
    print(f"\n  full detail: {path}")


def _configure_progress_logging() -> None:
    """Surface llm/orchestrator progress on the CLI without polluting libraries."""
    logging.basicConfig(level=logging.INFO, format="%(message)s", force=True)
    for name in ("httpx", "httpcore", "openai"):
        logging.getLogger(name).setLevel(logging.WARNING)


# Back-compat for probes that imported the old helper name.
_required_api_budget = required_api_budget


def main(argv: list[str] | None = None) -> int:
    config = parse_args(argv)
    gold = json.loads(GOLD_PATH.read_text())
    documents = load_documents()

    if config.report:
        results = score_offline(config.report, gold, documents)
        stem = Path(config.report).stem
        print_summary(
            results,
            None,
            detail_path=EVALS_DIR / f"results-offline-{stem}.json",
        )
        return 0

    _configure_progress_logging()
    results, usage_snapshot, code = run_live(config, gold, documents)
    print_summary(results, usage_snapshot)
    return code


if __name__ == "__main__":
    sys.exit(main())