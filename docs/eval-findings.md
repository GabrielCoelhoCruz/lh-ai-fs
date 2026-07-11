# Eval findings

Live, uncached pipeline runs against the planted gold set (`backend/evals/gold.json`).
Command:

```bash
cd backend
python run_evals.py --runs 5 --max-api-calls 35
```

`BSD_LLM_CACHE` was unset. Every stage (including the deterministic `DeadlineChecker`) was `ok` on every run. Raw reports: `backend/evals/report-run{1..5}.json`. Auditable scores and finding→gold mappings: `backend/evals/results.json` (`llm_usage.max_api_calls: 35`, `logical_calls: 35`, per-run `llm_usage` non-null — one untainted live session).

## Headline metrics (5 runs)

| Run | Recall | Precision | Ungrounded evidence |
|-----|--------|-----------|---------------------|
| 1 | 1.000 | 0.765 | 0.000 |
| 2 | 1.000 | 0.750 | 0.000 |
| 3 | 0.917 | 0.769 | 0.000 |
| 4 | 1.000 | 0.917 | 0.000 |
| 5 | 1.000 | 0.824 | 0.000 |
| **Mean ± std** | **0.983 ± 0.037** | **0.805 ± 0.069** | **0.000 ± 0.000** |

Published headline: **98.3% ± 3.7% recall / 80.5% ± 6.9% precision / 0% ungrounded-evidence rate**.

**Integrity correction.** A prior published 85.0% precision was inflated: DeadlineChecker was renumbered with `finding-{len(findings)+1}`, which ignored CNV sequence consumption and collided (e.g. two `finding-19` rows on an earlier run 2), so F12 was counted as a TP twice. Fixed by keeping the stable `finding-deadline` id. These numbers are from a fresh live session after that fix — lower precision, correct accounting. Every report uses exactly one `finding-deadline`; no duplicate finding IDs.

"Ungrounded-evidence rate" (JSON key `hallucination_rate`) is a mechanical check that every evidence quote appears in the cited document — not a semantic hallucination score.

Prior 3-run baseline (before DeadlineChecker + precision fixes): 80.6% ± 8.6% recall / 73.0% precision / 0% ungrounded-evidence.

## Per-flaw credit (mean over 5 runs)

| Flaw | Mean credit | Per-run |
|------|-------------|---------|
| F1 | 1.00 | 1,1,1,1,1 |
| F2 | 1.00 | 1,1,1,1,1 |
| F3 | 1.00 | 1,1,1,1,1 |
| F4 | 0.80 | 1,1,0,1,1 |
| F5 | 1.00 | 1,1,1,1,1 |
| F6 | 1.00 | 1,1,1,1,1 |
| F7 | 1.00 | 1,1,1,1,1 |
| F8 | 1.00 | 1,1,1,1,1 |
| F9 | 1.00 | 1,1,1,1,1 |
| F10 | 1.00 | 1,1,1,1,1 |
| F11 | 1.00 | 1,1,1,1,1 |
| F12 | 1.00 | 1,1,1,1,1 |

F12 was 0.0 on every pre-DeadlineChecker run; the deterministic checker now catches it every time (pure date math on the self-defeating Time-Barred section), counted once per run after the ID fix.

## Honest notes

- **F4 on run 3.** One-run miss on the "no rebuttal evidence" contradiction — LLM variance in CrossDocChecker.
- **Precision variance.** Runs 1–3 sit in the mid-70s; run 4 hits 0.917. Mean 80.5% is the honest post-fix number — not the inflated 85.0%.
- **F13 / F14.** Correctly `could_not_verify` on all five runs.
- **Precision traps (P6 / P10).** Gold negatives intentionally penalize over-flagging employment boilerplate and similar true statements. The CrossDocChecker guardrail routes subjective state-of-mind / acceptance boilerplate to `could_not_verify` instead of `unsupported`.
- **Dedup merge.** When CitationExtractor returns multiple uncited legal assertions, assembly emits one merged `unsupported_assertion` finding (verbatim evidence quote per assertion).
- **DeadlineChecker rationale.** F12 is internal incoherence (heading vs body date math), not a cross-doc or citation problem. Same philosophy as the reporter-year sanity check in CitationVerifier.
- **CourtListener deliberately omitted.** Prototype has no legal database. Fabricated-citation credit accepts honest `could_not_verify` or `likely_fabricated`; inventing a holding is what gets punished.
- **Provenance.** All numbers above come from one live uncached session (`BSD_LLM_CACHE` unset, `--max-api-calls 35`, 35 logical calls). Offline `--report` writes `results-offline-*.json` and never overwrites live `results.json`.
