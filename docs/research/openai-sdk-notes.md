# OpenAI SDK notes (verified against official docs, July 2026)

**Blocking:** `gpt-4o` (scaffold default in `backend/llm.py`) was retired from the API Feb 16-17, 2026 — along with gpt-4.1, gpt-4.1-mini, o4-mini. Must switch model IDs. Docs moved: platform.openai.com/docs → developers.openai.com/api/docs.

## Current structured-output pattern

Responses API is current; Chat Completions labeled legacy. `client.beta.chat.completions.parse` graduated → don't use `.beta.`.

```python
import os
from openai import OpenAI, APIError, APITimeoutError, RateLimitError, BadRequestError
from pydantic import BaseModel

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    timeout=60.0,    # SDK default 600s — too high for a web backend
    max_retries=3,   # default 2; auto-retries connection errors, 408/409/429/5xx
)

def call_structured(system: str, user: str, response_model: type[BaseModel],
                    model: str = "gpt-5.4-nano", effort: str = "minimal") -> BaseModel:
    try:
        resp = client.responses.parse(
            model=model,
            reasoning={"effort": effort},   # replaces temperature; GPT-5.x rejects temperature
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            text_format=response_model,
        )
    except BadRequestError as e:
        raise RuntimeError(f"Schema rejected by API: {e}") from e   # unsupported schema keyword/shape

    result = resp.output_parsed
    if result is None:
        if resp.status == "incomplete":
            # reasoning tokens consume output budget first; raise max_output_tokens or lower effort
            raise RuntimeError(f"Truncated: {resp.incomplete_details.reason}")
        raise RuntimeError(f"No structured output (likely refusal): {resp.output_text}")
    return result  # validated Pydantic instance
```

Three terminal failure modes (not retryable): safety refusal (`output_parsed is None`), truncation (`status == "incomplete"`), schema 400 (`BadRequestError`). With `strict: true` the API guarantees schema conformance — client-side Pydantic parse failure is not a normal event.

## Models + pricing (per 1M tokens)

| Model | Input | Cached in | Output | Role |
|---|---|---|---|---|
| gpt-5.6-sol | $5.00 | $0.50 | $30.00 | flagship reasoning |
| gpt-5.6-terra | $2.50 | $0.25 | $15.00 | balanced |
| gpt-5.6-luna | $1.00 | $0.10 | $6.00 | cost-optimized |
| gpt-5.4-mini | $0.75 | $0.075 | $4.50 | cheap-fast |
| gpt-5.4-nano | $0.20 | $0.02 | $1.25 | cheapest |

Pipeline routing: extraction/classification steps → `gpt-5.4-nano` (effort minimal/low); verification/reasoning steps → `gpt-5.6-terra` (effort high); `gpt-5.6-sol` only if terra underperforms in evals. Reasoning tokens bill as output tokens — main cost driver on verification. Repeated system prompts hit cached-input rates automatically (~90% input discount). Pin suffixed IDs (`-terra`), not bare `gpt-5.6`.

## Strict-schema constraints

- `additionalProperties: false` on every object; every field in `required` (optional = union with null). Root must be object. `$defs`/`$ref`/recursion OK.
- Caps: ≤100 properties total, ≤5 nesting levels, ≤500 enum values total, ≤15k chars of property names/enum/const values.
- Unsupported keywords (per Azure mirror, may lag native): minLength/maxLength/pattern/format, minimum/maximum/multipleOf, min/maxItems, min/maxProperties, uniqueItems. Native docs show minLength/minimum/maximum in examples — verify before relying; safest to avoid.
- Design: flat, shallow Pydantic models; split anything >~50 props or >3 levels into sub-steps.

Sources: developers.openai.com/api/docs/guides/structured-outputs, /guides/migrate-to-responses, /guides/reasoning, /pricing, /models, /deprecations; github.com/openai/openai-python README.
