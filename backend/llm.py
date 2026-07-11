"""Single guarded LLM entry point for every pipeline agent.

Callers get structured Pydantic output, a hard network-attempt budget, and
aggregate token usage. SDK retries default to zero so one logical stage call
cannot silently become several paid calls.

Progress is emitted via the ``llm`` logger (INFO). Library code never writes
to stdout; enable the logger from CLI entry points that want progress.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, TypeVar

from dotenv import load_dotenv
from openai import APIError, BadRequestError, OpenAI
from pydantic import BaseModel

load_dotenv()

log = logging.getLogger(__name__)

MODEL_FAST = os.getenv("BSD_MODEL_FAST", "gpt-5.4-nano")
MODEL_REASONING = os.getenv("BSD_MODEL_REASONING", "gpt-5.6-terra")

PIPELINE_LOGICAL_CALLS = 6
JUDGE_LOGICAL_CALLS = 1

# Default on-disk replay cache when BSD_LLM_CACHE=1 (off unless env is set).
_DEFAULT_LLM_CACHE_DIR = Path(__file__).resolve().parent / "evals" / "llm-cache"


class LLMCallError(RuntimeError):
    def __init__(self, kind: str, detail: str):
        super().__init__(f"[{kind}] {detail}")
        self.kind = kind
        self.detail = detail


@dataclass(frozen=True)
class LLMBudget:
    """Single source of truth for one guarded LLM scope."""

    max_api_calls: int = 7
    sdk_max_retries: int = 0
    timeout_s: float = 180.0
    max_output_tokens: int = 16000
    model_override: str | None = None
    effort_override: str | None = None

    def __post_init__(self) -> None:
        if self.max_api_calls < 0 or self.sdk_max_retries < 0:
            raise ValueError("API-call budget and SDK retries must be non-negative")
        if self.timeout_s <= 0 or self.max_output_tokens <= 0:
            raise ValueError("timeout and max_output_tokens must be positive")

    @classmethod
    def from_env(cls) -> LLMBudget:
        return cls(
            max_api_calls=env_int("BSD_MAX_API_CALLS", 7),
            sdk_max_retries=env_int("BSD_LLM_MAX_RETRIES", 0),
            timeout_s=float(os.getenv("BSD_LLM_TIMEOUT_S", "180")),
            max_output_tokens=env_int("BSD_LLM_MAX_OUTPUT_TOKENS", 16000),
        )


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMRunStats:
    budget: LLMBudget
    logical_calls: int = 0
    api_attempts_reserved: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0

    @property
    def max_api_calls(self) -> int:
        return self.budget.max_api_calls

    @property
    def sdk_max_retries(self) -> int:
        return self.budget.sdk_max_retries

    @property
    def timeout_s(self) -> float:
        return self.budget.timeout_s

    @property
    def max_output_tokens(self) -> int:
        return self.budget.max_output_tokens

    @property
    def model_override(self) -> str | None:
        return self.budget.model_override

    @property
    def effort_override(self) -> str | None:
        return self.budget.effort_override

    def reserve(self) -> int:
        """Reserve the worst-case network attempts for the next SDK call."""
        attempts = 1 + self.sdk_max_retries
        after = self.api_attempts_reserved + attempts
        if after > self.max_api_calls:
            raise LLMCallError(
                "budget",
                "API-call budget exhausted before request. "
                f"Reserved {self.api_attempts_reserved}/{self.max_api_calls}; "
                f"the next call could use {attempts} attempt(s).",
            )
        self.logical_calls += 1
        self.api_attempts_reserved = after
        return self.logical_calls

    def record_usage(self, usage: TokenUsage | None) -> None:
        if usage is None:
            return
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.reasoning_tokens += usage.reasoning_tokens
        self.total_tokens += usage.total_tokens

    def as_dict(self) -> dict[str, int | float | str | None]:
        return {
            "max_api_calls": self.max_api_calls,
            "logical_calls": self.logical_calls,
            "api_attempts_reserved": self.api_attempts_reserved,
            "sdk_max_retries": self.sdk_max_retries,
            "timeout_s": self.timeout_s,
            "max_output_tokens": self.max_output_tokens,
            "model_override": self.model_override,
            "effort_override": self.effort_override,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "total_tokens": self.total_tokens,
        }


def required_api_budget(
    runs: int,
    *,
    use_judge: bool,
    stage_retries: int,
    sdk_retries: int,
) -> int:
    """Worst-case network attempts for runs × (pipeline stages [+ judge]) × SDK."""
    if runs < 1 or stage_retries < 0 or sdk_retries < 0:
        raise ValueError("runs must be >= 1; retries must be >= 0")
    pipeline = PIPELINE_LOGICAL_CALLS * (1 + stage_retries)
    judge = JUDGE_LOGICAL_CALLS if use_judge else 0
    return runs * (pipeline + judge) * (1 + sdk_retries)


def _usage_from_response(resp: object) -> TokenUsage | None:
    usage = getattr(resp, "usage", None)
    if usage is None:
        return None
    details = getattr(usage, "output_tokens_details", None)
    return TokenUsage(
        input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
        reasoning_tokens=int(getattr(details, "reasoning_tokens", 0) or 0),
    )


_run_stats: ContextVar[LLMRunStats | None] = ContextVar(
    "llm_run_stats", default=None
)
# Process-global client, keyed by (api_key, timeout, retries). Safe for the
# sync single-flight pipeline; overlapping concurrent configs would cross-wire.
_client: OpenAI | None = None
_client_config: tuple[str | None, float, int] | None = None


def env_int(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value < 0:
        raise ValueError(f"{name} must be zero or greater")
    return value


# Back-compat alias used by older call sites / probes.
_env_int = env_int


@contextmanager
def llm_run(budget: LLMBudget | None = None) -> Iterator[LLMRunStats]:
    """Create one budget/usage scope. Nested calls reuse the outer scope.

    When nested, ``budget`` is ignored — the outer scope owns the limits.
    """
    existing = _run_stats.get()
    if existing is not None:
        yield existing
        return

    stats = LLMRunStats(budget=budget or LLMBudget.from_env())
    token = _run_stats.set(stats)
    try:
        yield stats
    finally:
        _run_stats.reset(token)


def current_run_stats() -> LLMRunStats | None:
    return _run_stats.get()


def effective_model(model: str) -> str:
    stats = current_run_stats()
    return stats.model_override if stats and stats.model_override else model


def get_client() -> OpenAI:
    """Return a client configured for the current guarded run."""
    global _client, _client_config
    stats = current_run_stats()
    retries = (
        stats.sdk_max_retries if stats else env_int("BSD_LLM_MAX_RETRIES", 0)
    )
    timeout = (
        stats.timeout_s
        if stats
        else float(os.getenv("BSD_LLM_TIMEOUT_S", "180"))
    )
    api_key = os.getenv("OPENAI_API_KEY")
    config = (api_key, timeout, retries)
    if _client is None or _client_config != config:
        _client = OpenAI(
            api_key=api_key,
            timeout=timeout,
            max_retries=retries,
        )
        _client_config = config
    return _client


T = TypeVar("T", bound=BaseModel)


def _llm_cache_dir() -> Path | None:
    """Return cache directory when BSD_LLM_CACHE is set; else None (off)."""
    raw = os.getenv("BSD_LLM_CACHE")
    if raw is None or raw.strip() == "":
        return None
    if raw.strip() == "1":
        return _DEFAULT_LLM_CACHE_DIR
    return Path(raw).expanduser()


def _cache_key(
    *,
    model: str,
    effort: str,
    system: str,
    user: str,
    response_model: type[BaseModel],
) -> str:
    payload = {
        "model": model,
        "effort": effort,
        "system": system,
        "user": user,
        "schema": response_model.model_json_schema(),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _read_cache(path: Path, response_model: type[T]) -> T | None:
    if not path.is_file():
        return None
    return response_model.model_validate_json(path.read_text(encoding="utf-8"))


def _write_cache(path: Path, parsed: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(f"{path.suffix}.tmp")
    temp.write_text(parsed.model_dump_json(), encoding="utf-8")
    temp.replace(path)


def call_structured(
    system: str,
    user: str,
    response_model: type[T],
    model: str = MODEL_FAST,
    effort: str = "low",
    max_output_tokens: int | None = None,
    cache: bool = True,
) -> T:
    """Call one model within a hard attempt budget and return typed output."""
    with llm_run() as stats:
        return _call_structured(
            stats,
            system,
            user,
            response_model,
            model,
            effort,
            max_output_tokens,
            cache=cache,
        )


def _call_structured(
    stats: LLMRunStats,
    system: str,
    user: str,
    response_model: type[T],
    model: str,
    effort: str,
    max_output_tokens: int | None,
    cache: bool = True,
) -> T:
    selected_model = stats.model_override or model
    selected_effort = stats.effort_override or effort
    selected_output_limit = (
        stats.max_output_tokens
        if max_output_tokens is None
        else min(max_output_tokens, stats.max_output_tokens)
    )

    cache_dir = _llm_cache_dir() if cache else None
    cache_path: Path | None = None
    key: str | None = None
    if cache_dir is not None:
        key = _cache_key(
            model=selected_model,
            effort=selected_effort,
            system=system,
            user=user,
            response_model=response_model,
        )
        cache_path = cache_dir / f"{key}.json"
        hit = _read_cache(cache_path, response_model)
        if hit is not None:
            log.info(
                "[llm] call cached: model=%s key=%s",
                selected_model,
                key[:12],
            )
            return hit

    call_number = stats.reserve()
    log.info(
        "[llm] call %s starting: model=%s effort=%s max_output_tokens=%s "
        "reserved_attempts=%s/%s",
        call_number,
        selected_model,
        selected_effort,
        selected_output_limit,
        stats.api_attempts_reserved,
        stats.max_api_calls,
    )

    try:
        resp = get_client().responses.parse(
            model=selected_model,
            reasoning={"effort": selected_effort},
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            text_format=response_model,
            max_output_tokens=selected_output_limit,
        )
    except BadRequestError as e:
        raise LLMCallError("bad_schema", str(e)) from e
    except APIError as e:
        raise LLMCallError("api", str(e)) from e

    stats.record_usage(_usage_from_response(resp))
    log.info(
        "[llm] call %s complete: input=%s output=%s reasoning=%s total=%s "
        "cumulative",
        call_number,
        stats.input_tokens,
        stats.output_tokens,
        stats.reasoning_tokens,
        stats.total_tokens,
    )

    parsed = resp.output_parsed
    if parsed is None:
        if getattr(resp, "status", None) == "incomplete":
            reason = getattr(resp.incomplete_details, "reason", "unknown")
            raise LLMCallError("truncated", f"incomplete response: {reason}")
        raise LLMCallError("refusal", resp.output_text or "no structured output")

    if cache_path is not None:
        _write_cache(cache_path, parsed)
    return parsed
