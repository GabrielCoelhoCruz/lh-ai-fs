# BS Detector

Legal briefs lie. Not always intentionally — but they do. They cite cases that don't say what they claim. They quote authority with words quietly removed. They state facts that contradict the documents sitting right next to them.

Your task has two parts:

1. Build an AI pipeline that catches problems in the provided legal brief.
2. Design how that prototype becomes a production-ready MVP for real customers.

Treat both parts seriously. The production readiness plan is not an appendix; it is the second half of the challenge and will be a major focus of the follow-up interview.

## Setup

### Docker (recommended)

```bash
cp .env.example .env      # Add your OpenAI API key
docker compose up --build
```

The API runs at `http://localhost:8002`. The UI runs at `http://localhost:5175`.

Both services hot-reload — edit files on your host and changes appear automatically.

### Manual Setup

#### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env      # Add your OpenAI API key
uvicorn main:app --reload
```

The API runs at `http://localhost:8002`.

#### Frontend

```bash
cd frontend
npm install
npm run dev
```

The UI runs at `http://localhost:5175`.

## Challenge Structure

This challenge is designed for foundational engineers at an early startup. We want to see whether you can ship a working AI prototype and also reason about the system it would need to become: reliable, scalable, inspectable, secure, and usable by real legal teams.

You should submit both:

- **Part 1: Working Prototype** — a functioning BS Detector pipeline.
- **Part 2: Production Readiness Plan** — a system design document for scaling the prototype into an MVP production system.

## Part 1: Working Prototype

Inside `backend/documents/` you'll find a small case file: a Motion for Summary Judgment in a personal injury lawsuit (*Rivera v. Harmon Construction Group*), along with a police report, medical records, and a witness statement.

Build a multi-agent pipeline that analyzes these documents and produces a structured verification report.

Your pipeline should:

**Core (Tier 1)**
- Extract all citations from the Motion for Summary Judgment
- For each citation, assess whether the cited authority actually supports the proposition as stated
- Flag direct quotes for accuracy
- Produce structured output (JSON) — not a wall of prose

**Expected (Tier 2)**
- Build an eval harness that measures your pipeline's output quality. It must be runnable via a single command (e.g., `python run_evals.py`). At minimum, measure precision (avoiding false flags), recall (catching known flaws), and hallucination rate (not fabricating findings). You choose the approach — there's no prescribed framework or tooling.
- Cross-document consistency check: compare facts stated in the MSJ against the police report, medical records, and witness statement
- Express uncertainty appropriately — "could not verify" rather than fabricating a finding
- Pass structured data between agents, not raw text blobs

**Stretch (Tier 3)**
- At least 4 well-defined agents with distinct, non-overlapping roles
- A confidence scoring layer: each flag rated by how certain the pipeline is, with reasoning
- A judicial memo agent: synthesizes the top findings into a one-paragraph summary written for a judge
- Agent orchestration that handles failures gracefully
- A UI that displays the report in a structured, readable way — not just raw JSON
- A reflection document explaining the tradeoffs you made and what you'd do differently

## Part 2: Production Readiness Plan

After the prototype, write a serious production readiness plan for taking BS Detector to an MVP production system. Put it in `docs/production-readiness.md` or an equivalent document.

This should be treated as a standalone system design challenge. We are not asking for a generic "how to scale an app" essay. We are asking how **this** AI legal verification product should move from a local prototype to a production MVP for real legal users.

Assume the product will eventually need to handle confidential customer documents, long-running AI workflows, multiple users and organizations, quality-sensitive outputs, and growth beyond a single local process. You decide the rest of the assumptions. State them clearly.

Your plan should explain the architecture you would choose, the tradeoffs behind it, and how you would sequence the work. It should be concrete enough to defend in an interview, but it does not need to be exhaustive. We care more about your reasoning than whether you name a specific cloud service or framework.

We do **not** expect you to build this production system during the take-home. We do expect you to show how you think about turning a prototype into a product: where state lives, how work moves through the system, what can fail, what needs to be measured, what must be secure, and what you would build first.

Avoid boilerplate architecture. A strong answer makes opinionated choices, explains why they fit the product, and calls out what you are intentionally not solving yet.

## Deliverables

1. A working `POST /analyze` endpoint that returns a structured verification report
2. Agent code with clear, named agents and explicit prompts
3. A runnable eval suite with instructions in your README on how to run it
4. A production readiness plan for scaling this prototype into an MVP
5. A brief reflection (in the repo or as a separate file) on your design decisions and tradeoffs

## Time

Recommended timebox: 6 hours for the implementation and 2-3 hours for the production readiness plan. This is intentionally scoped beyond what most candidates will finish. Where you invest your time matters more than finishing everything. A well-tested pipeline that catches 3 flaws is stronger than an untested one that attempts 10, and a focused production plan with clear tradeoffs is stronger than a broad architecture full of buzzwords.

If you spend materially more or less time, note that in your reflection.

## Evals

We run your eval suite as part of our review. Document how to run it in your README. We care more about thoughtful metric design than perfect scores — an eval that honestly reports 60% recall tells us more than one that reports 100% on cherry-picked cases.

## AI Usage

Use everything. That's the job. We want to see how you use it, not whether you do.

## Evaluation

We are evaluating:

1. How you decompose the problem into agents
2. How precisely you write prompts
3. The quality of your eval approach — do you measure what matters?
4. How far you get through the spec
5. How you would scale the system into a production MVP, including AI workflow orchestration, database scalability, infrastructure, reliability, security, observability, and cost controls
6. How honest your reflection is

Not lines of code.

## Follow-Up Interview

If we move forward, the follow-up interview will focus on defending your implementation and your production readiness plan. Expect to walk through your architecture, explain bottlenecks, reason about AI workflow orchestration and database scalability, discuss infrastructure choices, and describe what you would build first as a founding engineer.
