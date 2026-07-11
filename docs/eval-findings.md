# Eval findings

Live, uncached pipeline runs against the planted gold set (`backend/evals/gold.json`).
Command:

```bash
cd backend
python run_evals.py --runs 5 --max-api-calls 35
```

`BSD_LLM_CACHE` was unset. Every stage (including the new deterministic `DeadlineChecker`) was `ok` on every run. Raw reports: `backend/evals/report-run{1..5}.json`. Auditable scores and finding→gold mappings: `backend/evals/results.json`.

## Headline metrics (5 runs)

| Run | Recall | Precision | Hallucination |
|-----|--------|-----------|---------------|
| 1 | 1.000 | 0.824 | 0.000 |
| 2 | 1.000 | 0.895 | 0.000 |
| 3 | 0.833 | 0.857 | 0.000 |
| 4 | 1.000 | 0.864 | 0.000 |
| 5 | 0.833 | 0.810 | 0.000 |
| **Mean ± std** | **0.933 ± 0.091** | **0.850 ± 0.034** | **0.000 ± 0.000** |

Published headline: **93.3% ± 9.1% recall / 85.0% ± 3.4% precision / 0% hallucination**.

Prior 3-run baseline (before DeadlineChecker + precision fixes): 80.6% ± 8.6% recall / 73.0% precision / 0% hallucination.

## Per-flaw credit (mean over 5 runs)

| Flaw | Mean credit | Per-run |
|------|-------------|---------|
| F1 | 1.00 | 1,1,1,1,1 |
| F2 | 0.80 | 1,1,0,1,1 |
| F3 | 0.80 | 1,1,0,1,1 |
| F4 | 1.00 | 1,1,1,1,1 |
| F5 | 1.00 | 1,1,1,1,1 |
| F6 | 1.00 | 1,1,1,1,1 |
| F7 | 1.00 | 1,1,1,1,1 |
| F8 | 1.00 | 1,1,1,1,1 |
| F9 | 1.00 | 1,1,1,1,1 |
| F10 | 0.80 | 1,1,1,1,0 |
| F11 | 0.80 | 1,1,1,1,0 |
| F12 | 1.00 | 1,1,1,1,1 |

F12 was 0.0 on every prior run; the deterministic `DeadlineChecker` now catches it every time (pure date math on the self-defeating Time-Barred section).

## Honest notes

- **F10 / F11 on run 5.** Missed once. Inspection of `report-run5.json`: CrossDocChecker never extracted the "eight years" tenure claim (not routed to `could_not_verify` either), and CitationExtractor emitted zero uncited assertions that run. Not a DeadlineChecker regression; not the unsupported-criteria guardrail misclassifying tenure (runs 1–4 still credit F10 at 1.0, with state-of-mind boilerplate correctly in CNV).
- **F2 / F3 on run 3.** One-run miss on PPE / Harmon-involvement contradictions — LLM variance in CrossDocChecker, unchanged by this pass.
- **F13.** Correctly `could_not_verify` on all five runs here. A prior historical 3-run session once flagged it as a flaw; documented, not chased.
- **Precision traps (P6 / P10).** Gold negatives intentionally penalize over-flagging employment boilerplate and similar true statements. The CrossDocChecker guardrail routes subjective state-of-mind / acceptance boilerplate to `could_not_verify` instead of `unsupported`, which is the main precision lift alongside merging duplicate uncited-assertion findings in assembly.
- **Dedup merge.** When CitationExtractor returns multiple uncited legal assertions, assembly now emits one merged `unsupported_assertion` finding (verbatim evidence quote per assertion) instead of near-duplicate "without supporting authority" rows that dragged precision.
- **DeadlineChecker rationale.** F12 is internal incoherence (heading vs body date math), not a cross-doc or citation problem. No LLM can be trusted to catch it reliably; a 15-line pure function can. Same philosophy as the reporter-year sanity check in CitationVerifier.
- **CourtListener deliberately omitted.** Prototype has no legal database. Fabricated-citation credit accepts honest `could_not_verify` or `likely_fabricated`; inventing a holding is what gets punished. Wiring CourtListener would be the first production upgrade (see `docs/production-readiness.md`), not a silent prototype dependency.
- **Provenance.** All numbers above come from live uncached pipeline runs (`BSD_LLM_CACHE` unset). Offline `--report` rescoring is deterministic-only (no judge) and understates recall for fact-level gold items — use it to audit grounding/citation matches, not as the published score.
