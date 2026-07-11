# Reflection

## How I worked

Per the brief's "use everything — that's the job": this submission was built AI-first, and the workflow itself is the part I'd defend hardest. Before writing pipeline code I ran three parallel research passes: (1) an adversarial audit of the four documents to build a ground-truth flaw inventory, (2) web verification of every authority the MSJ cites against Justia/CourtListener/SCOCAL (result: 10 of 12 authorities fabricated or defective — full dossier in `docs/research/caselaw-dossier.md`), and (3) a check of current OpenAI SDK/model reality (which caught that the scaffold's `gpt-4o` was retired from the API in Feb 2026 — the starter code errors as shipped).

Building the gold set *before* the pipeline was the highest-leverage decision. It forced scoring conventions to be decided up front (see below), gave the eval precision traps teeth, and meant prompts were written against known failure modes instead of hopes.

## Design decisions and tradeoffs

**Deterministic orchestrator, LLMs never route.** Stage order, retries, degradation, and finding assembly are plain Python; agents only judge. This costs flexibility (no dynamic "agent decides what to check next") and buys debuggability and honest partial reports. For a verification product, inspectability wins.

**Six agents instead of three.** Extraction, citation verification, and quote checking could be one prompt. Splitting them keeps roles non-overlapping (extraction is mechanical and cheap; verification is knowledge-bound; quote auditing is a different epistemic task), lets each run at the right model tier, and makes the adjudicator's deduplication meaningful (e.g., the Privette doctored quote is legitimately visible to two agents; the adjudicator merges, preserving the audit trail).

**No legal database in the prototype.** Citation verification rides model knowledge with hard uncertainty discipline: "real" only for genuinely recognized authorities, `could_not_verify` otherwise, holdings never reconstructed. The eval encodes the same convention — for fabricated citations, either `likely_fabricated` or an honest `could_not_verify` scores as correct; a confident invented holding is what gets punished. In production this is the first thing I'd replace with a CourtListener existence check (see production plan §5). One deterministic signal made it into the prototype anyway: a reporter-series/year sanity check (887 F.2d cannot be 1991).

**Hallucination metric is mechanical, not LLM-judged.** Every evidence quote in a finding must literally appear in the cited source document (normalized, ellipsis-aware). An LLM judging "did the LLM hallucinate" is circular; string containment is not. The same check doubles as a prompt-injection tripwire in the production design.

**Eval matching is hybrid.** Citation-level gold items match deterministically by case name; fact-level findings are mapped by an LLM judge. Judge errors are possible — the full finding→gold mapping is dumped to `evals/results.json` so any score can be audited by hand. The footnote string cite is scored fractionally (flagged cases / 6) so bulk-fabrication detection isn't all-or-nothing.

**Sequential stages.** The verifier/quote/cross-doc stages could run concurrently (they're independent); I kept execution sequential for simplicity and readable failure semantics. For a minutes-tolerant workload the latency cost is acceptable at prototype scale; the production plan moves the whole pipeline behind a queue anyway, where per-stage parallelism is a worker concern.

## What I'd do differently with more time

- **Run the evals more.** The harness supports `--runs N` for variance, but LLM pipelines deserve a proper stability report (flakiness per gold item across 10 runs), not a point estimate.
- **CourtListener API in the prototype** — it's free, and existence checks as facts rather than model opinions would likely be the single biggest recall/precision jump on F7–F9-style flaws.
- **A claim-extraction stage separate from claim-checking.** The CrossDocChecker does both in one call; splitting would make its recall measurable independently and its outputs reusable.
- **F12-style argument-level defects** used to fall between agent mandates. Shipped a deterministic `DeadlineChecker` instead of widening a prompt — see the Jul 2026 addendum.

## Honest accounting

Any eval numbers reported in `evals/results.json` come from real runs of `python run_evals.py` — nothing cherry-picked; the harness saves the raw reports it scored alongside the scores. Where the pipeline misses a gold flaw, the miss is visible in per-flaw credit. Time spent: research and gold-set construction consumed roughly as much as implementation, which was the point — the AI-heavy workflow shifts human effort from typing code to deciding what "correct" means and verifying it.

## Addendum — truncation bug and eval integrity (Jul 2026)

**Root cause of low recall (41.7% across 3 runs).** Not detection quality — a token-budgeting bug. The OpenAI Responses API counts reasoning tokens against `max_output_tokens`. At the former 4,000-token cap with `effort="high"`, CitationVerifier and CrossDocChecker consumed the entire budget on reasoning alone (logs showed reasoning delta = exactly 4,000, zero visible output) and failed every run with `incomplete response: max_output_tokens`. That killed F6 and made ~7 of 12 flaws plus both uncertainty cases uncatchable.

**Fix.** Raised the global default from 4,000 → 16,000 tokens (`llm.py`, `run_evals.py`). Rationale: observed reasoning use at high effort is ~4,000+; 16,000 leaves room for reasoning plus structured JSON. Billing is per token actually used, so only the previously-truncated calls cost more.

**Eval integrity flaw.** F7/F8/F9 earned credit 1.0 via `cnv_acceptable` matching against stage-failure backfill entries — assembly emits "No verification produced…" when a verifier crashes, which looks like honest could-not-verify to the scorer. Fix: `Finding.backfilled=True` on assembly backfills; scoring excludes backfilled CNV from `cnv_acceptable` credit and uncertainty handling. `results.json` now reports `backfill_excluded` counts.

**Before/after.** Pre-fix (3 runs, 4k cap): recall 41.7%, precision 78.3%, hallucination 0%; CitationVerifier and CrossDocChecker failed every run with `incomplete response: max_output_tokens`; F7/F8/F9 earned false credit via backfill CNV. Post-fix (3 runs, 16k cap): recall 47.2%, precision 73.5%, hallucination 0%; zero truncation errors; run 1 CitationVerifier completed (50% recall, F6/F7/F8/F9 all credited via real findings); runs 2–3 hit 180s timeouts on some stages but backfill-exclusion counts (12 on run 2) confirm honest scoring when stages fail.

**Not doing (deliberate).** Retry-with-escalating-cap machinery — complexity > value for a take-home; noted here for production.

## Addendum — timeout stability + replay cache (Jul 2026)

**Problem after the truncation fix.** With the 16k output cap, CitationVerifier and CrossDocChecker at `effort="high"` reasoned long enough to hit the 180s client timeout. Across runs, recall swung 0.25–0.667 depending on which stages completed — unstable numbers for a take-home submission, and every prompt tweak cost real API tokens.

**Effort tradeoff.** Dropped CitationVerifier and CrossDocChecker from `high` → `medium` (QuoteChecker stays `high`; F5 depends on it). ConfidenceAdjudicator already completes reliably at medium (~20–140s observed). Medium trades some theoretical reasoning depth for timeout stability; we never measured un-truncated high without timeout, so the ceiling is unknown — stable honest numbers beat a theoretical max.

**Final live numbers (cache OFF, 3 runs, `--max-api-calls 21`, 180s timeout).** Aggregate recall **80.6%**, precision **73.0%**, hallucination **0%**. Per-run recall: 0.917 / 0.75 / 0.75. Every stage `ok` in every run — zero timeouts, zero truncations, `backfill_excluded=0`. Persistent miss: F12 (argument-level coherence; known agent-mandate gap). Run-to-run variance is now small enough to publish.

**Replay cache (`BSD_LLM_CACHE`).** Optional record/replay in `llm.py` keyed on sha256(model, effort, system, user, response schema). Off by default; `BSD_LLM_CACHE=1` uses `backend/evals/llm-cache/` (gitignored). Hits skip `reserve()` and record no usage. Judge always passes `cache=False`. Schema changes invalidate keys automatically via `model_json_schema()`. Published results above are from live runs only.

## Addendum — deterministic deadline gate + precision (Jul 2026)

**Deterministic-gate philosophy.** The reporter-year sanity check in CitationVerifier already proved that some failure modes are cheaper and more reliable as pure functions than as LLM judgments. F12 is the same shape: a heading that says "Time-Barred" while the body concedes filing is inside the CCP 335.1 / 730-day window. `DeadlineChecker` parses incident + filing dates, requires a time-barred assertion and SOL context, and emits `misleading_framing` only when the math is self-defeating. Evidence quotes are regex match spans (verbatim substrings) so grounding keeps the finding. Result: F12 = 1.0 on all 5 live runs.

**Precision.** Assembly now merges multiple uncited-assertion extractions into one finding (one verbatim quote per assertion) instead of emitting near-duplicate "without supporting authority" rows. CrossDocChecker prompt adds a one-line guardrail: `unsupported` is for material, record-checkable facts; subjective state-of-mind / acceptance boilerplate goes to `could_not_verify`. Watched F10 (tenure) across re-runs — still 1.0 on 4/5; the single miss was claim non-extraction, not misrouting.

**Deliberately skipped.** CourtListener / any legal DB in the prototype — honest `could_not_verify` beats a fake existence check. Dynamic agent routing. Retry-with-escalating-cap machinery.

**Updated live numbers (cache OFF, 5 runs, `--max-api-calls 35`).** Recall **93.3% ± 9.1%**, precision **85.0% ± 3.4%**, hallucination **0%**. All seven stages `ok` every run. Full tables: `docs/eval-findings.md`.
