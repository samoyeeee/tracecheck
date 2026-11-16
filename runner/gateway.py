"""LLM gateway: every model call in the project goes through here.

It wraps ``litellm.completion`` (which tau2 uses for the agent, the user
simulator and the NL-assertion judge) and adds what a free-tier run needs:

1. Rate limiting   - a per-model requests-per-minute window and a per-model
                     requests-per-day counter that survives restarts.
2. Retries         - per-minute 429s wait for the server's retryDelay; 5xx and
                     timeouts back off exponentially.
3. Clean stop      - when the daily quota is gone we raise DailyQuotaExhausted
                     (a BaseException, so tau2's own retry loops do not swallow
                     it) and the batch runner stops and can be resumed later.
4. Usage log       - one CSV row per call in results/cost_log.csv.
5. Provider shims  - route each model to its provider's OpenAI-compatible
                     endpoint (Gemini, Zhipu GLM), drop the
                     unsupported ``seed`` param, and add the documented
                     placeholder thought signature to replayed tool calls
                     (tau2's message model drops the real one, and Gemini 3.x
                     rejects tool calls without any signature).

Nothing here reads or stores an API key value; the OpenAI client picks it up
from the environment variable named by its provider's ``key_env``.
"""

from __future__ import annotations

import csv
import json
import os
import random
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

# Placeholder accepted by the Gemini API when the real signature is unavailable.
PLACEHOLDER_SIGNATURE = "skip_thought_signature_validator"
# Gemini daily quotas reset at midnight Pacific time.
QUOTA_TZ = ZoneInfo("America/Los_Angeles")

COST_LOG_FIELDS = [
    "timestamp", "run_tag", "role", "model", "requested_model", "status",
    "attempts", "wait_seconds", "latency_seconds", "prompt_tokens",
    "completion_tokens", "total_tokens", "billed_cost_usd", "list_price_cost_usd",
]


class DailyQuotaExhausted(BaseException):
    """The model's free-tier daily quota is used up. Resume after the reset."""


class MalformedToolCall(Exception):
    """The model kept producing an unparseable tool call (a model failure)."""


@dataclass
class ModelLimit:
    rpm: int
    rpd: int
    provider: str = "gemini"


@dataclass
class Provider:
    """An OpenAI-compatible endpoint and its quirks."""
    api_base: str
    key_env: str
    # Gemini 3.x rejects replayed tool calls that carry no thought signature.
    placeholder_signatures: bool = False
    # Extra JSON body fields sent on every call (e.g. Zhipu's thinking switch).
    extra_body: dict = field(default_factory=dict)


@dataclass
class GatewayConfig:
    default_model: str
    limits: dict[str, ModelLimit]
    providers: dict[str, Provider] = field(default_factory=dict)
    # Non-Gemini model names tau2 hardcodes (e.g. the NL-assertion judge) are
    # rewritten to this model so a zero-budget run never calls a paid API.
    judge_model: Optional[str] = None
    max_transient_retries: int = 6
    max_minute_retries: int = 8
    max_malformed_retries: int = 2
    # USD per 1M tokens {model: [input, output]}; empty -> list price "unknown".
    list_prices: dict[str, list[float]] = field(default_factory=dict)
    state_path: Path = Path("results/quota_state.json")
    cost_log_path: Path = Path("results/cost_log.csv")


def quota_day(now: Optional[float] = None) -> str:
    """The quota day (Pacific date) that ``now`` falls into."""
    ts = time.time() if now is None else now
    return datetime.fromtimestamp(ts, QUOTA_TZ).strftime("%Y-%m-%d")


class RateLimiter:
    """Per-model RPM sliding window + persistent RPD counter.

    Every *attempt* is counted, including ones that end in an error, because
    the provider counts them too.
    """

    def __init__(
        self,
        limits: dict[str, ModelLimit],
        state_path: Path,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.limits = limits
        self.state_path = Path(state_path)
        self.clock = clock
        self.sleep = sleep
        self._lock = threading.Lock()
        self._windows: dict[str, deque] = {}
        self._state = self._load()

    # -- persistence -------------------------------------------------------
    def _load(self) -> dict:
        if self.state_path.exists():
            try:
                return json.loads(self.state_path.read_text())
            except json.JSONDecodeError:
                pass
        return {}

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._state, indent=1, sort_keys=True))
        tmp.replace(self.state_path)

    def _day_entry(self, model: str) -> dict:
        day = quota_day(self.clock())
        entry = self._state.setdefault(model, {})
        if entry.get("day") != day:
            entry.clear()
            entry.update({"day": day, "requests": 0, "exhausted": False})
        return entry

    # -- public API --------------------------------------------------------
    def used_today(self, model: str) -> int:
        with self._lock:
            return self._day_entry(model)["requests"]

    def remaining_today(self, model: str) -> int:
        with self._lock:
            entry = self._day_entry(model)
            if entry["exhausted"]:
                return 0
            return max(0, self.limits[model].rpd - entry["requests"])

    def mark_exhausted(self, model: str) -> None:
        """The server said the daily quota is gone (it is the source of truth)."""
        with self._lock:
            self._day_entry(model)["exhausted"] = True
            self._save()

    def acquire(self, model: str) -> float:
        """Block until a request slot is free. Returns seconds waited."""
        limit = self.limits[model]
        waited = 0.0
        while True:
            with self._lock:
                entry = self._day_entry(model)
                if entry["exhausted"] or entry["requests"] >= limit.rpd:
                    raise DailyQuotaExhausted(
                        f"{model}: daily budget of {limit.rpd} requests used "
                        f"({entry['requests']} sent on quota day {entry['day']})."
                    )
                window = self._windows.setdefault(model, deque())
                now = self.clock()
                while window and now - window[0] >= 60.0:
                    window.popleft()
                if len(window) < limit.rpm:
                    window.append(now)
                    entry["requests"] += 1
                    self._save()
                    return waited
                pause = 60.0 - (now - window[0]) + 0.05
            self.sleep(pause)
            waited += pause


# -- 429 parsing ------------------------------------------------------------
def parse_quota_error(text: str) -> dict:
    """Pull scope ("minute"/"day"), limit and retry delay out of a Gemini 429."""
    info: dict[str, Any] = {"scope": None, "limit": None, "retry_delay": None}
    m = re.search(r"quotaId['\"]?\s*[:=]\s*['\"]([A-Za-z\-]+)", text)
    quota_id = m.group(1) if m else ""
    # Zhipu: business code 1304 = daily call limit reached.
    if "PerDay" in quota_id or re.search(r"per day|\b1304\b|今日", text, re.I):
        info["scope"] = "day"
    elif "PerMinute" in quota_id or re.search(r"per minute", text, re.I):
        info["scope"] = "minute"
    m = re.search(r"quotaValue['\"]?\s*[:=]\s*['\"]?(\d+)", text)
    if m:
        info["limit"] = int(m.group(1))
    m = re.search(r"retry in ([\d.]+)s", text) or re.search(
        r"retryDelay['\"]?\s*[:=]\s*['\"]?([\d.]+)s", text
    )
    if m:
        info["retry_delay"] = float(m.group(1))
    return info


def add_placeholder_signatures(messages: list[dict]) -> list[dict]:
    """Give replayed assistant tool calls a thought signature if they lack one."""
    out = []
    for msg in messages:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            msg = dict(msg)
            calls = []
            for call in msg["tool_calls"]:
                call = dict(call)
                google = dict((call.get("extra_content") or {}).get("google") or {})
                if not google.get("thought_signature"):
                    google["thought_signature"] = PLACEHOLDER_SIGNATURE
                    call["extra_content"] = {"google": google}
                calls.append(call)
            msg["tool_calls"] = calls
        out.append(msg)
    return out


def extract_json(text: Optional[str]) -> Optional[str]:
    """Return the JSON payload of a reply that may be fenced or have chatter around it."""
    if not text:
        return text
    stripped = text.strip()
    try:
        json.loads(stripped)
        return stripped
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*(.*?)```", stripped, re.S)
    candidates = [m.group(1).strip()] if m else []
    start, end = stripped.find("{"), stripped.rfind("}")
    if start != -1 and end > start:
        candidates.append(stripped[start:end + 1])
    for candidate in candidates:
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            continue
    return text  # not recoverable: let the caller fail loudly


# -- the gateway ------------------------------------------------------------
class Gateway:
    def __init__(self, config: GatewayConfig, completion_fn: Callable, sleep=time.sleep):
        self.config = config
        self._completion = completion_fn
        self._sleep = sleep
        self.limiter = RateLimiter(config.limits, config.state_path, sleep=sleep)
        self._log_lock = threading.Lock()
        self.run_tag = ""
        self.role_by_model: dict[str, str] = {}
        self.observed_limits: dict[str, dict] = {}  # what 429s told us

    def _resolve_model(self, requested: str) -> str:
        name = requested.split("/")[-1]
        if name in self.config.limits:
            return name
        # A model tau2 hardcodes (judge etc.): send it to our judge model.
        return self.config.judge_model or self.config.default_model

    def _log(self, row: dict) -> None:
        path = self.config.cost_log_path
        with self._log_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            new = not path.exists()
            with path.open("a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=COST_LOG_FIELDS)
                if new:
                    writer.writeheader()
                writer.writerow(row)

    def _list_price(self, model: str, prompt: int, completion: int) -> str:
        price = self.config.list_prices.get(model)
        if not price:
            return ""  # unknown: we do not guess prices
        return f"{(prompt * price[0] + completion * price[1]) / 1e6:.6f}"

    def completion(self, *args, **kwargs):
        requested = kwargs.get("model") or (args[0] if args else "")
        model = self._resolve_model(requested)
        role = kwargs.pop("tracecheck_role", "") or (
            "judge" if model != requested.split("/")[-1] else self.role_by_model.get(model, "")
        )
        kwargs["model"] = f"openai/{model}"
        provider = self.config.providers[self.config.limits[model].provider]
        kwargs["api_base"] = provider.api_base
        kwargs.pop("seed", None)  # not accepted by the compatible endpoint
        if role == "judge":
            kwargs.pop("reasoning_effort", None)  # tuned for the OpenAI judge model
        kwargs["num_retries"] = 0  # retries are handled here, and counted
        kwargs["api_key"] = os.environ.get(provider.key_env, "")
        if provider.extra_body:
            kwargs["extra_body"] = {**provider.extra_body, **(kwargs.get("extra_body") or {})}
        if kwargs.get("messages") and provider.placeholder_signatures:
            kwargs["messages"] = add_placeholder_signatures(kwargs["messages"])
        args = args[1:] if args else args

        attempts = transient = minute_hits = malformed = 0
        waited = 0.0
        while True:
            waited += self.limiter.acquire(model)
            attempts += 1
            start = time.time()
            try:
                response = self._completion(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - classified below
                text = str(exc)
                status = getattr(exc, "status_code", None)
                if status == 429 or "RESOURCE_EXHAUSTED" in text:
                    info = parse_quota_error(text)
                    if info["limit"]:
                        self.observed_limits.setdefault(model, {})[info["scope"]] = info["limit"]
                    if info["scope"] == "day":
                        self.limiter.mark_exhausted(model)
                        self._log(self._row(requested, model, role, "daily_quota", attempts, waited, start))
                        raise DailyQuotaExhausted(f"{model}: server reports daily quota exhausted. {text[:300]}") from exc
                    minute_hits += 1
                    if minute_hits > self.config.max_minute_retries:
                        self._log(self._row(requested, model, role, "rate_limited", attempts, waited, start))
                        raise
                    pause = (info["retry_delay"] or 30.0) + random.uniform(1, 3)
                elif "MALFORMED_FUNCTION_CALL" in text:  # checked before 5xx: litellm wraps it as a 500
                    # The model emitted a broken tool call and litellm cannot
                    # parse the response. Retry a little; if it keeps happening
                    # it is a genuine model failure and the caller records it.
                    malformed += 1
                    self._log(self._row(requested, model, role, "malformed_call", attempts, waited, start))
                    if malformed > self.config.max_malformed_retries:
                        raise MalformedToolCall(f"{model}: malformed function call x{malformed}") from exc
                    # At temperature 0 the same broken call tends to repeat.
                    kwargs["temperature"] = max(kwargs.get("temperature") or 0.0, 0.5)
                    pause = 1.0
                elif status in (500, 502, 503, 504) or status is None and re.search(
                    r"timed? ?out|connection|UNAVAILABLE|overloaded", text, re.I
                ):
                    transient += 1
                    if transient > self.config.max_transient_retries:
                        self._log(self._row(requested, model, role, "error", attempts, waited, start))
                        raise
                    pause = min(120.0, 4.0 * 2 ** (transient - 1)) + random.uniform(0, 2)
                else:
                    self._log(self._row(requested, model, role, "error", attempts, waited, start))
                    raise
                self._sleep(pause)
                waited += pause
                continue
            if role == "judge":
                # tau2 json.loads() the judge reply as-is; some models wrap it
                # in a Markdown code fence, which would crash a finished run.
                try:
                    msg = response.choices[0].message
                    msg.content = extract_json(msg.content)
                except (AttributeError, IndexError):
                    pass
            usage = getattr(response, "usage", None)
            prompt = getattr(usage, "prompt_tokens", 0) or 0
            completion = getattr(usage, "completion_tokens", 0) or 0
            total = getattr(usage, "total_tokens", 0) or prompt + completion
            row = self._row(requested, model, role, "ok", attempts, waited, start)
            row.update(prompt_tokens=prompt, completion_tokens=completion, total_tokens=total,
                       list_price_cost_usd=self._list_price(model, prompt, completion))
            self._log(row)
            return response

    def _row(self, requested, model, role, status, attempts, waited, start) -> dict:
        return {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "run_tag": self.run_tag, "role": role, "model": model,
            "requested_model": requested, "status": status, "attempts": attempts,
            "wait_seconds": f"{waited:.1f}", "latency_seconds": f"{time.time() - start:.2f}",
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
            "billed_cost_usd": "0", "list_price_cost_usd": "",
        }


_installed: Optional[Gateway] = None


def install(config: GatewayConfig) -> Gateway:
    """Route all litellm.completion calls (ours and tau2's) through the gateway."""
    global _installed
    if _installed is not None:
        return _installed
    import litellm
    import tau2.utils.llm_utils as llm_utils

    litellm.suppress_debug_info = True
    gateway = Gateway(config, litellm.completion)
    litellm.completion = gateway.completion
    if hasattr(llm_utils, "completion"):  # tau2 imported the name directly
        llm_utils.completion = gateway.completion
    # tau2 logs an error per call for models litellm has no price for.
    llm_utils.get_response_cost = lambda *a, **k: 0.0
    _installed = gateway
    return gateway
