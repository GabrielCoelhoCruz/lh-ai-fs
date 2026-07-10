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
- **F12-style argument-level defects** (a heading contradicted by its own body text) fall between my agents' mandates — a seventh "internal coherence" agent, or a broader mandate for the cross-doc checker, would cover it. I chose to ship the eval that exposes the gap rather than widen a prompt at the deadline; an eval that honestly shows a miss is worth more than a prompt stretched to hide it.

## Honest accounting

Eval numbers reported in the README/`evals/results.json` are from real runs of `python run_evals.py` — nothing cherry-picked; the harness saves the raw reports it scored. Where the pipeline misses a gold flaw, the miss is visible in per-flaw credit. Time spent: research and gold-set construction consumed roughly as much as implementation, which was the point — the AI-heavy workflow shifts human effort from typing code to deciding what "correct" means and verifying it.
