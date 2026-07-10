"""Single LLM entry point for all agents.

Uses the Responses API structured-output helper (`client.responses.parse`)
so every agent call returns a validated Pydantic instance, never raw text.
GPT-5.x models are reasoning-native: cost/quality is steered per call via
`reasoning.effort`, not temperature (which they reject).

Failure modes are surfaced as LLMCallError with a machine-readable `kind`
so the orchestrator can decide per stage whether to retry, degrade, or skip:
- "refusal"    — model declined; not retryable with the same input
- "truncated"  — reasoning + output exceeded max_output_tokens
- "bad_schema" — request-time 400, the schema itself was rejected
- "api"        — terminal transport/API error after SDK retries
"""

import os
from typing import TypeVar

from dotenv import load_dotenv
from openai import APIError, BadRequestError, OpenAI
from pydantic import BaseModel

load_dotenv()

# Cheap-fast for extraction/classification; strong for verification reasoning.
MODEL_FAST = os.getenv("BSD_MODEL_FAST", "gpt-5.4-nano")
MODEL_REASONING = os.getenv("BSD_MODEL_REASONING", "gpt-5.6-terra")

_client: OpenAI | None = None


def get_client() -> OpenAI:
    """Lazy client so the app can start (and tests can import) without a key."""
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            timeout=float(os.getenv("BSD_LLM_TIMEOUT_S", "120")),
            max_retries=3,  # SDK auto-retries connection errors, 408/409/429/5xx
        )
    return _client


T = TypeVar("T", bound=BaseModel)


class LLMCallError(RuntimeError):
    def __init__(self, kind: str, detail: str):
        super().__init__(f"[{kind}] {detail}")
        self.kind = kind
        self.detail = detail


def call_structured(
    system: str,
    user: str,
    response_model: type[T],
    model: str = MODEL_FAST,
    effort: str = "low",
    max_output_tokens: int | None = None,
) -> T:
    """Call the model and return a schema-validated instance of response_model."""
    kwargs: dict = {}
    if max_output_tokens is not None:
        kwargs["max_output_tokens"] = max_output_tokens
    try:
        resp = get_client().responses.parse(
            model=model,
            reasoning={"effort": effort},
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            text_format=response_model,
            **kwargs,
        )
    except BadRequestError as e:
        raise LLMCallError("bad_schema", str(e)) from e
    except APIError as e:
        raise LLMCallError("api", str(e)) from e

    parsed = resp.output_parsed
    if parsed is None:
        if getattr(resp, "status", None) == "incomplete":
            reason = getattr(resp.incomplete_details, "reason", "unknown")
            raise LLMCallError("truncated", f"incomplete response: {reason}")
        raise LLMCallError("refusal", resp.output_text or "no structured output")
    return parsed
