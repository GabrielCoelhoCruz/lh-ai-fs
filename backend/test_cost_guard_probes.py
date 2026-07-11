"""Offline probes for LLM cost, retry, and persistence guardrails."""

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent))

import llm
from llm import LLMBudget, LLMCallError, call_structured, env_int, llm_run, required_api_budget
from orchestrator import _run_stage
from run_evals import _write_json


class ProbeOutput(BaseModel):
    value: str


class FakeResponses:
    def __init__(self):
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            output_parsed=ProbeOutput(value="ok"),
            usage=SimpleNamespace(
                input_tokens=11,
                output_tokens=7,
                total_tokens=18,
                output_tokens_details=SimpleNamespace(reasoning_tokens=3),
            ),
        )


def test_budget_blocks_before_client_access():
    original_get_client = llm.get_client
    client_accessed = False

    def forbidden_client():
        nonlocal client_accessed
        client_accessed = True
        raise AssertionError("client must not be accessed")

    llm.get_client = forbidden_client
    try:
        with llm_run(LLMBudget(max_api_calls=0, sdk_max_retries=0)):
            try:
                call_structured("system", "user", ProbeOutput)
                raise AssertionError("budget error expected")
            except LLMCallError as exc:
                assert exc.kind == "budget"
        assert not client_accessed
    finally:
        llm.get_client = original_get_client


def test_budget_reserves_possible_sdk_retries():
    with llm_run(LLMBudget(max_api_calls=2, sdk_max_retries=2)):
        try:
            call_structured("system", "user", ProbeOutput)
            raise AssertionError("budget error expected")
        except LLMCallError as exc:
            assert exc.kind == "budget"


def test_nested_llm_run_reuses_outer_budget():
    outer = LLMBudget(max_api_calls=3, sdk_max_retries=0, max_output_tokens=500)
    inner = LLMBudget(
        max_api_calls=99,
        sdk_max_retries=0,
        max_output_tokens=9999,
        model_override="ignored-model",
    )
    with llm_run(outer) as stats:
        with llm_run(inner) as nested:
            assert nested is stats
            assert stats.max_api_calls == 3
            assert stats.max_output_tokens == 500
            assert stats.model_override is None


def test_usage_and_smoke_override_are_collected():
    fake_responses = FakeResponses()
    fake_client = SimpleNamespace(responses=fake_responses)
    original_get_client = llm.get_client
    llm.get_client = lambda: fake_client
    try:
        with llm_run(
            LLMBudget(
                max_api_calls=1,
                sdk_max_retries=0,
                model_override="cheap-model",
                effort_override="low",
                max_output_tokens=1000,
            )
        ) as stats:
            output = call_structured(
                "system",
                "user",
                ProbeOutput,
                model="expensive-model",
                effort="high",
                max_output_tokens=9000,
            )
            assert output.value == "ok"
            assert stats.logical_calls == 1
            assert stats.api_attempts_reserved == 1
            assert stats.input_tokens == 11
            assert stats.output_tokens == 7
            assert stats.reasoning_tokens == 3
            assert stats.total_tokens == 18
            assert stats.max_output_tokens == 1000
            assert stats.effort_override == "low"
            assert stats.as_dict()["effort_override"] == "low"
        assert fake_responses.calls[0]["model"] == "cheap-model"
        assert fake_responses.calls[0]["reasoning"] == {"effort": "low"}
        assert fake_responses.calls[0]["max_output_tokens"] == 1000
    finally:
        llm.get_client = original_get_client


def test_stage_retry_is_explicit():
    attempts = 0

    def flaky():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise LLMCallError("api", "temporary")
        return "ok"

    stages = []
    assert _run_stage("Probe", flaky, stages, retries=0) is None
    assert attempts == 1

    attempts = 0
    stages = []
    assert _run_stage("Probe", flaky, stages, retries=1) == "ok"
    assert attempts == 2


def test_eval_budget_accounts_for_both_retry_layers():
    assert (
        required_api_budget(
            1,
            use_judge=True,
            stage_retries=0,
            sdk_retries=0,
        )
        == 7
    )
    assert (
        required_api_budget(
            3,
            use_judge=True,
            stage_retries=1,
            sdk_retries=3,
        )
        == 156
    )


def test_atomic_json_write_replaces_complete_file():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "result.json"
        _write_json(path, {"completed_runs": 1})
        assert path.read_text().strip() == '{\n  "completed_runs": 1\n}'
        assert not path.with_suffix(".json.tmp").exists()


def test_full_run_default_budget_leaves_reasoning_headroom():
    from run_evals import EvalConfig

    assert EvalConfig().max_output_tokens >= 12000
    assert LLMBudget().max_output_tokens >= 12000
    assert env_int("BSD_LLM_MAX_OUTPUT_TOKENS", 16000) >= 12000


def test_cache_hit_consumes_zero_budget(monkeypatch, tmp_path):
    monkeypatch.setenv("BSD_LLM_CACHE", str(tmp_path))
    fake_responses = FakeResponses()
    fake_client = SimpleNamespace(responses=fake_responses)
    original_get_client = llm.get_client
    llm.get_client = lambda: fake_client
    try:
        with llm_run(LLMBudget(max_api_calls=2, sdk_max_retries=0)) as stats:
            first = call_structured("system", "user-cache", ProbeOutput)
            assert first.value == "ok"
            assert stats.api_attempts_reserved == 1
            assert len(fake_responses.calls) == 1
            assert list(tmp_path.glob("*.json"))

            second = call_structured("system", "user-cache", ProbeOutput)
            assert second == first
            assert stats.api_attempts_reserved == 1
            assert len(fake_responses.calls) == 1
    finally:
        llm.get_client = original_get_client


def test_cache_false_bypasses_even_with_env(monkeypatch, tmp_path):
    monkeypatch.setenv("BSD_LLM_CACHE", str(tmp_path))
    fake_responses = FakeResponses()
    fake_client = SimpleNamespace(responses=fake_responses)
    original_get_client = llm.get_client
    llm.get_client = lambda: fake_client
    try:
        with llm_run(LLMBudget(max_api_calls=3, sdk_max_retries=0)) as stats:
            call_structured("system", "user-bypass", ProbeOutput)
            assert stats.api_attempts_reserved == 1
            assert list(tmp_path.glob("*.json"))

            call_structured("system", "user-bypass", ProbeOutput, cache=False)
            assert stats.api_attempts_reserved == 2
            assert len(fake_responses.calls) == 2
    finally:
        llm.get_client = original_get_client


def test_cache_off_when_env_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("BSD_LLM_CACHE", raising=False)
    assert llm._llm_cache_dir() is None
    fake_responses = FakeResponses()
    fake_client = SimpleNamespace(responses=fake_responses)
    original_get_client = llm.get_client
    llm.get_client = lambda: fake_client
    try:
        with llm_run(LLMBudget(max_api_calls=2, sdk_max_retries=0)) as stats:
            call_structured("system", "user-off", ProbeOutput)
            call_structured("system", "user-off", ProbeOutput)
            assert stats.api_attempts_reserved == 2
            assert len(fake_responses.calls) == 2
            assert not list(tmp_path.glob("*.json"))
    finally:
        llm.get_client = original_get_client


def main() -> int:
    test_budget_blocks_before_client_access()
    test_budget_reserves_possible_sdk_retries()
    test_nested_llm_run_reuses_outer_budget()
    test_usage_and_smoke_override_are_collected()
    test_stage_retry_is_explicit()
    test_eval_budget_accounts_for_both_retry_layers()
    test_atomic_json_write_replaces_complete_file()
    test_full_run_default_budget_leaves_reasoning_headroom()
    print("All cost guard probe tests passed without API access.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
