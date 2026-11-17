"""Tests for the rate limiter / retry gateway. No network, fake clock."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runner.gateway import (  # noqa: E402
    PLACEHOLDER_SIGNATURE, DailyQuotaExhausted, Gateway, GatewayConfig,
    ModelLimit, Provider, RateLimiter, add_placeholder_signatures, parse_quota_error,
)
from runner.run_batch import is_done, plan, sim_path  # noqa: E402

REAL_429 = (
    "Error code: 429 - Quota exceeded for metric: generativelanguage.googleapis.com/"
    "generate_content_free_tier_requests, limit: 15, model: gemini-3.5-flash-lite\\n"
    "Please retry in 34.136350965s.', 'status': 'RESOURCE_EXHAUSTED', 'details': [{'quotaId': "
    "'GenerateRequestsPerMinutePerProjectPerModel-FreeTier', 'quotaValue': '15'}, "
    "{'retryDelay': '34s'}]"
)


class Clock:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def test_rpm_window_blocks_then_releases(tmp_path):
    clock = Clock()
    rl = RateLimiter({"m": ModelLimit(rpm=2, rpd=100)}, tmp_path / "q.json", clock, clock.sleep)
    assert rl.acquire("m") == 0
    assert rl.acquire("m") == 0
    waited = rl.acquire("m")  # third call in the same minute must wait ~60s
    assert 59 < waited < 61


def test_daily_budget_persists_across_restarts(tmp_path):
    clock = Clock()
    limits = {"m": ModelLimit(rpm=100, rpd=3)}
    rl = RateLimiter(limits, tmp_path / "q.json", clock, clock.sleep)
    for _ in range(3):
        rl.acquire("m")
    with pytest.raises(DailyQuotaExhausted):
        rl.acquire("m")
    rl2 = RateLimiter(limits, tmp_path / "q.json", clock, clock.sleep)  # "restart"
    assert rl2.remaining_today("m") == 0
    clock.t += 24 * 3600  # next quota day
    assert rl2.remaining_today("m") == 3


def test_parse_real_minute_429():
    info = parse_quota_error(REAL_429)
    assert info == {"scope": "minute", "limit": 15, "retry_delay": 34.136350965}


def test_parse_daily_429():
    info = parse_quota_error("quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier', 'quotaValue': '500'")
    assert info["scope"] == "day" and info["limit"] == 500


def test_placeholder_signature_only_when_missing():
    msgs = [
        {"role": "assistant", "tool_calls": [
            {"id": "a", "function": {"name": "f", "arguments": "{}"}},
            {"id": "b", "function": {"name": "f", "arguments": "{}"},
             "extra_content": {"google": {"thought_signature": "REAL"}}}]},
        {"role": "user", "content": "hi"},
    ]
    out = add_placeholder_signatures(msgs)
    sigs = [c["extra_content"]["google"]["thought_signature"] for c in out[0]["tool_calls"]]
    assert sigs == [PLACEHOLDER_SIGNATURE, "REAL"]
    assert "extra_content" not in msgs[0]["tool_calls"][0]  # input not mutated


def _gateway(tmp_path, fn, rpd=100):
    cfg = GatewayConfig(default_model="m", limits={"m": ModelLimit(rpm=1000, rpd=rpd, provider="p")},
                        providers={"p": Provider(api_base="https://example.test/v1/", key_env="X_KEY",
                                                 extra_body={"thinking": {"type": "disabled"}})},
                        state_path=tmp_path / "q.json", cost_log_path=tmp_path / "cost.csv")
    return Gateway(cfg, fn, sleep=lambda s: None)


def _ok():
    return SimpleNamespace(usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15))


def test_retries_minute_429_then_succeeds_and_logs(tmp_path):
    calls = []

    def fn(**kw):
        calls.append(kw)
        if len(calls) == 1:
            err = RuntimeError(REAL_429)
            err.status_code = 429
            raise err
        return _ok()

    gw = _gateway(tmp_path, fn)
    gw.completion(model="m", messages=[{"role": "user", "content": "x"}], seed=1)
    assert len(calls) == 2 and "seed" not in calls[0]
    assert gw.observed_limits == {"m": {"minute": 15}}
    assert gw.limiter.used_today("m") == 2  # failed attempts count against quota
    rows = (tmp_path / "cost.csv").read_text().strip().splitlines()
    assert len(rows) == 2 and ",ok,2," in rows[1]


def test_daily_429_stops_and_marks_exhausted(tmp_path):
    def fn(**kw):
        err = RuntimeError("429 quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier'")
        err.status_code = 429
        raise err

    gw = _gateway(tmp_path, fn)
    with pytest.raises(DailyQuotaExhausted):
        gw.completion(model="m", messages=[])
    assert gw.limiter.remaining_today("m") == 0


def test_non_retryable_error_is_raised_once(tmp_path):
    calls = []

    def fn(**kw):
        calls.append(1)
        err = RuntimeError("400 bad request")
        err.status_code = 400
        raise err

    with pytest.raises(RuntimeError):
        _gateway(tmp_path, fn).completion(model="m", messages=[])
    assert len(calls) == 1


def test_resume_plan_skips_done_and_reruns_infra_errors(tmp_path):
    sim_path(tmp_path, "1", 0).write_text('{"termination_reason": "user_stop"}')
    sim_path(tmp_path, "2", 0).write_text('{"termination_reason": "infrastructure_error"}')
    assert is_done(sim_path(tmp_path, "1", 0))
    assert plan(["1", "2"], 2, tmp_path) == [("2", 0), ("1", 1), ("2", 1)]


def test_malformed_tool_call_retried_then_raised(tmp_path):
    from runner.gateway import MalformedToolCall
    calls = []

    def fn(**kw):
        calls.append(1)
        raise RuntimeError("finish_reason ... 'function_call_filter: MALFORMED_FUNCTION_CALL'")

    with pytest.raises(MalformedToolCall):
        _gateway(tmp_path, fn).completion(model="m", messages=[])
    assert len(calls) == 3  # 1 try + 2 retries


def test_crash_is_retried_on_resume_then_counted_as_failure(tmp_path):
    from runner.run_batch import MAX_CRASHES, record_crash
    path = sim_path(tmp_path, "7", 0)
    for i in range(MAX_CRASHES):
        assert not is_done(path)
        record_crash(path, "7", 0, RuntimeError("boom"))
    assert is_done(path)  # gives up: kept as a failed run with reward 0
    import json
    assert json.loads(path.read_text())["reward_info"]["reward"] == 0.0


def test_provider_routing_and_zhipu_daily_code(tmp_path):
    seen = {}

    def fn(**kw):
        seen.update(kw)
        return _ok()

    _gateway(tmp_path, fn).completion(model="m", messages=[
        {"role": "assistant", "tool_calls": [{"id": "a", "function": {"name": "f", "arguments": "{}"}}]}])
    assert seen["api_base"] == "https://example.test/v1/" and seen["model"] == "openai/m"
    assert seen["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "extra_content" not in seen["messages"][0]["tool_calls"][0]  # signatures are Gemini-only
    assert parse_quota_error('{"error":{"code":"1304","message":"该API已达今日调用次数限额"}}')["scope"] == "day"


def test_extract_json_handles_fences_and_chatter():
    from runner.gateway import extract_json
    assert extract_json('{"a": 1}') == '{"a": 1}'
    assert extract_json('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert extract_json('Here you go:\n{"a": [1, 2]}\nDone.') == '{"a": [1, 2]}'
    assert extract_json("no json here") == "no json here"


def test_shards_are_disjoint_and_cover_everything():
    from runner.run_batch import parse_shard, shard_tasks
    ids = [str(i) for i in range(7)]
    a, b = shard_tasks(ids, parse_shard("0/2")), shard_tasks(ids, parse_shard("1/2"))
    assert not set(a) & set(b) and sorted(a + b) == ids
    assert shard_tasks(ids, parse_shard(None)) == ids
    with pytest.raises(ValueError):
        parse_shard("2/2")


def test_overload_is_retried_long_and_never_counted_as_agent_failure(tmp_path):
    from runner.gateway import is_overload
    from runner.run_batch import MAX_CRASHES, record_crash
    calls = []

    def fn(**kw):
        calls.append(1)
        if len(calls) < 4:
            err = RuntimeError("RateLimitError: 该模型当前访问量过大，请您稍后再试")
            err.status_code = 429
            raise err
        return _ok()

    _gateway(tmp_path, fn).completion(model="m", messages=[])
    assert len(calls) == 4
    assert is_overload("code 1305 overloaded") and not is_overload("1304 今日调用次数限额")
    path = sim_path(tmp_path, "8", 0)
    for _ in range(MAX_CRASHES + 2):
        record_crash(path, "8", 0, RuntimeError("RateLimitError: 该模型当前访问量过大"))
    assert not is_done(path)  # still pending, not a failed run
