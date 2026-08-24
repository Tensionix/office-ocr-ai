#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gemini provider wrapper for JSON-object responses.

Built for google-genai SDK.
Handles transport disconnects, rate limits, and enforces JSON output.
"""

from __future__ import annotations

import json
import mimetypes
import os
import random
import re
import threading
import time
from typing import Any, Dict, Iterable, Optional, Tuple

try:
    from google import genai
    from google.genai import types
except Exception:  # pragma: no cover - optional dependency at runtime
    genai = Any  # type: ignore[assignment]
    types = Any  # type: ignore[assignment]

def _print_retry(attempt: int, max_retries: int, sleep_sec: float, exc: Exception) -> None:
    try:
        msg = str(exc)
    except Exception:
        msg = ""
    msg = msg.replace("\n", " ")
    if len(msg) > 220:
        msg = msg[:220] + "…"
    print(f"  [NET] retry {attempt}/{max_retries} in {sleep_sec:.1f}s: {exc.__class__.__name__}: {msg}")

def extract_usage(resp: Any) -> Dict[str, int]:
    usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "reasoning_tokens": 0}
    meta = getattr(resp, "usage_metadata", None)
    if not meta:
        return usage
    
    usage["input_tokens"] = getattr(meta, "prompt_token_count", 0) or 0
    usage["output_tokens"] = getattr(meta, "candidates_token_count", 0) or 0
    usage["total_tokens"] = getattr(meta, "total_token_count", 0) or 0
    return usage


def _response_finish_reasons(resp: Any) -> str:
    values: list[str] = []
    for candidate in getattr(resp, "candidates", None) or []:
        reason = getattr(candidate, "finish_reason", None)
        if reason is not None:
            values.append(str(getattr(reason, "value", reason)))
    return ", ".join(values)

def _is_transport_error(exc: Exception) -> bool:
    name = exc.__class__.__name__.lower()
    msg = str(exc).lower()

    if "apierror" in name and ("503" in msg or "502" in msg or "504" in msg):
        return True
    if "remoteprotocolerror" in name or "protocolerror" in name:
        return True
    
    # Catch httpx transport issues often wrapped in Google SDK errors
    markers = (
        "connecterror", "readerror", "writeerror", "timeout", "network",
        "connection reset", "connection aborted", "server disconnected",
        "broken pipe", "eof", "unexpected eof", "ssl", "tls", "handshake"
    )
    return any(m in msg for m in markers) or any(m in name for m in markers)

def _is_rate_limited(msg: str) -> bool:
    markers = ("429", "quota", "rate limit", "too many requests")
    return any(m in msg for m in markers)


def _is_timeout_or_transient(msg: str) -> bool:
    markers = (
        "timeout",
        "timed out",
        "readtimeout",
        "connecttimeout",
        "server disconnected",
        "connection reset",
        "connection aborted",
        "empty model response text",
        "502",
        "503",
        "504",
    )
    return any(marker in msg for marker in markers)


def _extract_retry_after_sec(msg: str) -> Optional[float]:
    m = re.search(r"try again in\s+([0-9]+(?:\.[0-9]+)?)s", msg, flags=re.IGNORECASE)
    if not m:
        m = re.search(r"retry after\s+([0-9]+(?:\.[0-9]+)?)\s*s", msg, flags=re.IGNORECASE)
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except Exception:
        return default


class _AdaptiveRequestGate:
    """Process-local request pacing with 429 cooldown memory for Gemini."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._state: Dict[str, Dict[str, float]] = {}

    def _base_delay_range(self, model: str) -> tuple[float, float]:
        default_min = _env_float("GEMINI_REQUEST_DELAY_MIN_SEC", 0.3)
        default_max = _env_float("GEMINI_REQUEST_DELAY_MAX_SEC", 0.8)
        return max(0.0, default_min), max(default_min, default_max)

    def _get_state(self, model: str) -> Dict[str, float]:
        with self._lock:
            state = self._state.get(model)
            if state is None:
                state = {
                    "next_allowed_at": 0.0,
                    "cooldown_until": 0.0,
                    "rate_limit_streak": 0.0,
                    "last_rate_limit_at": 0.0,
                }
                self._state[model] = state
            return state

    def before_request(self, model: str) -> None:
        min_delay, max_delay = self._base_delay_range(model)

        while True:
            now = time.monotonic()
            with self._lock:
                state = self._get_state(model)
                wait_until = max(state["next_allowed_at"], state["cooldown_until"])
                if now >= wait_until:
                    sampled_delay = 0.0
                    if max_delay > 0.0:
                        sampled_delay = random.uniform(min_delay, max_delay)
                    state["next_allowed_at"] = now + sampled_delay
                    return
                sleep_sec = wait_until - now

            if sleep_sec > 0.25:
                print(f"  [PACE] wait {sleep_sec:.1f}s before {model}")
            time.sleep(min(sleep_sec, 2.0))

    def on_success(self, model: str) -> None:
        with self._lock:
            state = self._get_state(model)
            state["rate_limit_streak"] = 0.0
            state["last_rate_limit_at"] = 0.0

    def on_rate_limit(self, model: str, retry_after: Optional[float]) -> float:
        max_cooldown = max(5.0, _env_float("GEMINI_RATE_LIMIT_MAX_COOLDOWN_SEC", 60.0))
        with self._lock:
            state = self._get_state(model)
            state["rate_limit_streak"] += 1.0
            state["last_rate_limit_at"] = time.monotonic()

            streak = int(state["rate_limit_streak"])
            adaptive_floor = min(max_cooldown, 10.0 * (1.7 ** max(0, streak - 1)))
            target = max(retry_after or 0.0, adaptive_floor)
            target = min(max_cooldown, target) + random.uniform(0.5, 1.5)

            state["cooldown_until"] = max(state["cooldown_until"], time.monotonic() + target)
            state["next_allowed_at"] = max(state["next_allowed_at"], state["cooldown_until"])
            return target


_REQUEST_GATE = _AdaptiveRequestGate()


def _normalize_model_key(model: str) -> str:
    return str(model or "").strip().removeprefix("models/").lower()


class _AdaptiveModelFailover:
    """Process-local Gemini model failover after repeated 429/quota errors."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._active_index: Dict[tuple[str, ...], int] = {}
        self._rate_limit_streak: Dict[tuple[str, ...], int] = {}

    def chain_for(self, requested_model: str, model_chain: Optional[Iterable[str]] = None) -> tuple[str, ...]:
        model = _normalize_model_key(requested_model)
        if model_chain is None:
            return (model,)
        chain = tuple(_normalize_model_key(item) for item in model_chain if _normalize_model_key(item))
        if not chain:
            return (model,)
        if model in chain:
            return chain[chain.index(model):]
        return (model, *chain)

    def current_model(self, requested_model: str, model_chain: Optional[Iterable[str]] = None) -> str:
        chain = self.chain_for(requested_model, model_chain)
        with self._lock:
            index = self._active_index.get(chain, 0)
            index = max(0, min(index, len(chain) - 1))
            self._active_index[chain] = index
            return chain[index]

    def on_success(self, requested_model: str, model_chain: Optional[Iterable[str]] = None) -> None:
        chain = self.chain_for(requested_model, model_chain)
        with self._lock:
            self._rate_limit_streak[chain] = 0

    def on_rate_limit(self, requested_model: str, model_chain: Optional[Iterable[str]] = None) -> Optional[str]:
        chain = self.chain_for(requested_model, model_chain)
        with self._lock:
            streak = self._rate_limit_streak.get(chain, 0) + 1
            self._rate_limit_streak[chain] = streak
            index = self._active_index.get(chain, 0)
            if streak >= 2 and index < len(chain) - 1:
                index += 1
                self._active_index[chain] = index
                self._rate_limit_streak[chain] = 0
                return chain[index]
        return None


_MODEL_FAILOVER = _AdaptiveModelFailover()


def _remaining_time(deadline_monotonic: Optional[float]) -> Optional[float]:
    if deadline_monotonic is None:
        return None
    return deadline_monotonic - time.monotonic()

def _normalize_json_text(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return text

    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].lstrip()

    if text and not text.lstrip().startswith("{"):
        left = text.find("{")
        right = text.rfind("}")
        if left != -1 and right != -1 and right > left:
            text = text[left:right + 1]

    return text.strip()


def _guess_mime_type(path: str) -> str:
    mime, _ = mimetypes.guess_type(path)
    return mime or "application/octet-stream"


def _service_tier_value(value: Optional[str]) -> Optional[str]:
    text = str(value or "").strip().lower()
    if text in {"", "auto", "default", "standard"}:
        return None
    if text == "flex":
        return "flex"
    return text


def _generate_content_once(
    client: genai.Client,
    *,
    model: str,
    contents: Any,
    config: Any,
    use_stream: bool,
    timeout_sec: Optional[float],
) -> Tuple[str, Dict[str, int], str]:
    local_config = config
    if timeout_sec is not None:
        # google-genai HttpOptions.timeout is milliseconds, while project
        # settings and provider APIs use seconds.
        timeout_ms = max(1_000, int(float(timeout_sec) * 1000))
        local_config = config.model_copy(update={"http_options": types.HttpOptions(timeout=timeout_ms)})

    if use_stream and hasattr(client.models, "generate_content_stream"):
        chunks: list[str] = []
        latest_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "reasoning_tokens": 0}
        started_at = time.monotonic()
        next_heartbeat_at = started_at + 15.0
        stream: Iterable[Any] = client.models.generate_content_stream(
            model=model,
            contents=contents,
            config=local_config,
        )
        for chunk in stream:
            now = time.monotonic()
            if now >= next_heartbeat_at:
                print(f"  [NET] Gemini stream active {int(now - started_at)}s")
                next_heartbeat_at = now + 15.0
            chunk_text = (getattr(chunk, "text", "") or "")
            if chunk_text:
                chunks.append(chunk_text)
            chunk_usage = extract_usage(chunk)
            if any(chunk_usage.values()):
                latest_usage = chunk_usage

        text = "".join(chunks).strip()
        if not text:
            raise ValueError("Empty model response text")
        return text, latest_usage, "stream"

    resp = client.models.generate_content(
        model=model,
        contents=contents,
        config=local_config,
    )
    text = (getattr(resp, "text", "") or "").strip()
    if not text:
        reasons = _response_finish_reasons(resp)
        suffix = f"; finish_reason={reasons}" if reasons else ""
        raise ValueError(f"Empty Gemini response text{suffix}")
    return text, extract_usage(resp), "default"


def call_markdown_vision(
    client: genai.Client,
    *,
    model: str,
    model_chain: Optional[Iterable[str]] = None,
    system_instruction: str,
    user_prompt: str,
    image_paths: list[str],
    temperature: float = 0.0,
    timeout_sec: Optional[float] = None,
    deadline_monotonic: Optional[float] = None,
    max_retries: int = 3,
    sleep_after_sec: float = 0.0,
    use_stream: Optional[bool] = None,
    service_tier: Optional[str] = None,
) -> Tuple[str, Dict[str, int], str]:
    last_raw = ""
    parts: list[Any] = [user_prompt]
    for image_path in image_paths:
        with open(image_path, "rb") as fh:
            data = fh.read()
        parts.append(types.Part.from_bytes(data=data, mime_type=_guess_mime_type(image_path)))

    tier = _service_tier_value(service_tier)
    config_kwargs: dict[str, Any] = {
        "system_instruction": system_instruction,
        "temperature": temperature,
    }
    if tier:
        config_kwargs["service_tier"] = tier
    config = types.GenerateContentConfig(**config_kwargs)
    prefer_stream = _env_float("GEMINI_USE_STREAM", 1.0) > 0.0 if use_stream is None else bool(use_stream)

    for attempt in range(1, max_retries + 1):
        active_model = _MODEL_FAILOVER.current_model(model, model_chain)
        try:
            _REQUEST_GATE.before_request(active_model)
            remaining = _remaining_time(deadline_monotonic)
            if remaining is not None and remaining <= 0:
                raise TimeoutError("Gemini vision file deadline exceeded.")
            last_raw, usage, route = _generate_content_once(
                client,
                model=active_model,
                contents=parts,
                config=config,
                use_stream=prefer_stream,
                timeout_sec=min(timeout_sec, remaining) if timeout_sec is not None and remaining is not None else (remaining if remaining is not None else timeout_sec),
            )

            if sleep_after_sec > 0:
                time.sleep(sleep_after_sec)

            _REQUEST_GATE.on_success(active_model)
            _MODEL_FAILOVER.on_success(model, model_chain)
            return last_raw, usage, f"{route}:{tier}" if tier else route

        except Exception as exc:
            msg = str(exc).lower()
            if "finish_reason=recitation" in msg:
                raise RuntimeError("Gemini returned empty OCR response; finish_reason=RECITATION.") from exc
            if prefer_stream and (
                "generate_content_stream" in msg
                or "not implemented" in msg
                or "not supported" in msg
                or "unexpected keyword" in msg
            ):
                prefer_stream = False
                continue
            if _is_timeout_or_transient(msg) or _is_rate_limited(msg) or _is_transport_error(exc):
                if attempt < max_retries:
                    retry_after = _extract_retry_after_sec(msg)
                    if _is_rate_limited(msg):
                        adaptive_sleep = _REQUEST_GATE.on_rate_limit(active_model, retry_after)
                        switched_model = _MODEL_FAILOVER.on_rate_limit(model, model_chain)
                        if switched_model:
                            sleep_sec = min(5.0, max(0.5, adaptive_sleep))
                            remaining = _remaining_time(deadline_monotonic)
                            if remaining is not None:
                                if remaining <= 0:
                                    raise RuntimeError("Gemini vision file deadline exceeded.") from exc
                                sleep_sec = min(sleep_sec, max(0.0, remaining))
                                if sleep_sec <= 0:
                                    raise RuntimeError("Gemini vision file deadline exceeded.") from exc
                            print(f"  [429x2] switching Gemini model {active_model} -> {switched_model}")
                            time.sleep(sleep_sec)
                            continue
                        if retry_after is not None:
                            sleep_sec = max(adaptive_sleep, retry_after + random.uniform(0.2, 1.0))
                        else:
                            sleep_sec = adaptive_sleep
                    elif retry_after is not None:
                        sleep_sec = retry_after + random.uniform(0.2, 1.0)
                    else:
                        sleep_sec = min(180.0, 4.0 * (1.9 ** (attempt - 1))) + random.uniform(0.3, 1.2)
                    remaining = _remaining_time(deadline_monotonic)
                    if remaining is not None:
                        if remaining <= 0:
                            raise RuntimeError("Gemini vision file deadline exceeded.") from exc
                        sleep_sec = min(sleep_sec, max(0.0, remaining))
                        if sleep_sec <= 0:
                            raise RuntimeError("Gemini vision file deadline exceeded.") from exc
                    _print_retry(attempt, max_retries, sleep_sec, exc)
                    time.sleep(sleep_sec)
                    continue

                if _is_rate_limited(msg):
                    raise RuntimeError("Gemini vision rate limit exceeded and retries exhausted.") from exc
                raise RuntimeError(f"Gemini vision transport/timeout failed ({exc.__class__.__name__}).") from exc

            if attempt < max_retries:
                time.sleep(min(15.0, 3.0 * attempt))
                continue

            raise RuntimeError(f"Gemini vision call failed: {exc}\nRAW(head): {last_raw[:400]}") from exc

    raise RuntimeError("Unreachable")

def call_structured(
    client: genai.Client,
    *,
    model: str,
    model_chain: Optional[Iterable[str]] = None,
    system_instruction: str,
    user_prompt: str,
    temperature: float = 0.0,
    timeout_sec: Optional[float] = None,
    deadline_monotonic: Optional[float] = None,
    max_retries: int = 3,
    sleep_after_sec: float = 0.0,
    use_stream: Optional[bool] = None,
    service_tier: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, int], str]:
    
    last_raw = ""
    tier = _service_tier_value(service_tier)
    config_kwargs: dict[str, Any] = {
        "system_instruction": system_instruction,
        "temperature": temperature,
        "response_mime_type": "application/json",
    }
    if tier:
        config_kwargs["service_tier"] = tier
    config = types.GenerateContentConfig(**config_kwargs)
    prefer_stream = _env_float("GEMINI_USE_STREAM", 1.0) > 0.0 if use_stream is None else bool(use_stream)

    for attempt in range(1, max_retries + 1):
        active_model = _MODEL_FAILOVER.current_model(model, model_chain)
        try:
            _REQUEST_GATE.before_request(active_model)
            remaining = _remaining_time(deadline_monotonic)
            if remaining is not None and remaining <= 0:
                raise TimeoutError("Gemini file deadline exceeded.")
            last_raw, usage, route = _generate_content_once(
                client,
                model=active_model,
                contents=user_prompt,
                config=config,
                use_stream=prefer_stream,
                timeout_sec=min(timeout_sec, remaining) if timeout_sec is not None and remaining is not None else (remaining if remaining is not None else timeout_sec),
            )
            normalized = _normalize_json_text(last_raw)
            if not normalized:
                raise ValueError("Empty model response text")

            obj = json.loads(normalized)
            
            if sleep_after_sec > 0:
                time.sleep(sleep_after_sec)
                
            _REQUEST_GATE.on_success(active_model)
            _MODEL_FAILOVER.on_success(model, model_chain)
            return obj, usage, f"{route}:{tier}" if tier else route

        except Exception as exc:
            msg = str(exc).lower()
            if "finish_reason=recitation" in msg:
                raise RuntimeError("Gemini returned empty response; finish_reason=RECITATION.") from exc
            if prefer_stream and (
                "generate_content_stream" in msg
                or "not implemented" in msg
                or "not supported" in msg
                or "unexpected keyword" in msg
            ):
                prefer_stream = False
                continue

            if _is_timeout_or_transient(msg) or _is_rate_limited(msg) or _is_transport_error(exc):
                if attempt < max_retries:
                    retry_after = _extract_retry_after_sec(msg)
                    if _is_rate_limited(msg):
                        adaptive_sleep = _REQUEST_GATE.on_rate_limit(active_model, retry_after)
                        switched_model = _MODEL_FAILOVER.on_rate_limit(model, model_chain)
                        if switched_model:
                            sleep_sec = min(5.0, max(0.5, adaptive_sleep))
                            remaining = _remaining_time(deadline_monotonic)
                            if remaining is not None:
                                if remaining <= 0:
                                    raise RuntimeError("Gemini file deadline exceeded.") from exc
                                sleep_sec = min(sleep_sec, max(0.0, remaining))
                                if sleep_sec <= 0:
                                    raise RuntimeError("Gemini file deadline exceeded.") from exc
                            print(f"  [429x2] switching Gemini model {active_model} -> {switched_model}")
                            time.sleep(sleep_sec)
                            continue
                        if retry_after is not None:
                            sleep_sec = max(adaptive_sleep, retry_after + random.uniform(0.2, 1.0))
                        else:
                            sleep_sec = adaptive_sleep
                    elif retry_after is not None:
                        sleep_sec = retry_after + random.uniform(0.2, 1.0)
                    else:
                        sleep_sec = min(180.0, 4.0 * (1.9 ** (attempt - 1))) + random.uniform(0.3, 1.2)
                    remaining = _remaining_time(deadline_monotonic)
                    if remaining is not None:
                        if remaining <= 0:
                            raise RuntimeError("Gemini file deadline exceeded.") from exc
                        sleep_sec = min(sleep_sec, max(0.0, remaining))
                        if sleep_sec <= 0:
                            raise RuntimeError("Gemini file deadline exceeded.") from exc
                    
                    _print_retry(attempt, max_retries, sleep_sec, exc)
                    time.sleep(sleep_sec)
                    continue

                if _is_rate_limited(msg):
                    raise RuntimeError("Gemini rate limit exceeded and retries exhausted.") from exc

                raise RuntimeError(f"Gemini transport/timeout failed ({exc.__class__.__name__}).") from exc

            # Unknown API errors
            if attempt < max_retries:
                time.sleep(min(15.0, 3.0 * attempt))
                continue

            raise RuntimeError(f"Gemini call failed: {exc}\nRAW(head): {last_raw[:400]}") from exc

    raise RuntimeError("Unreachable")
