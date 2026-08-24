#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OpenAI provider wrapper for JSON-object responses.

STREAMING + RELAXED variant:
- Prefer Responses streaming to keep the connection alive during long generations.
- Treat transport disconnects as retryable.
- Treat empty response payload as retryable.
- Longer exponential backoff on transient network failures.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import random
import re
import time
from base64 import b64encode
from typing import Any, Dict, Optional, Tuple

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - optional dependency at runtime
    OpenAI = Any  # type: ignore[assignment]


def make_idempotency_key(doc_hash: str, chunk_index: int, model: str, prompt: str) -> str:
    h = hashlib.sha256(prompt.encode("utf-8", errors="ignore")).hexdigest()[:24]
    return f"audion-audit|{doc_hash}|{chunk_index}|{model}|{h}"[:200]


def _get_attr(obj: Any, key: str, default: int = 0) -> int:
    if isinstance(obj, dict):
        return int(obj.get(key, default) or 0)
    return int(getattr(obj, key, default) or 0)




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
    u = getattr(resp, "usage", None)
    if not u:
        return usage

    usage["input_tokens"] = _get_attr(u, "input_tokens")
    usage["output_tokens"] = _get_attr(u, "output_tokens")
    usage["total_tokens"] = _get_attr(u, "total_tokens")

    details = None
    if isinstance(u, dict):
        details = u.get("output_tokens_details") or u.get("input_tokens_details")
    else:
        details = getattr(u, "output_tokens_details", None) or getattr(u, "input_tokens_details", None)

    if details:
        usage["reasoning_tokens"] = _get_attr(details, "reasoning_tokens")
    else:
        usage["reasoning_tokens"] = _get_attr(u, "reasoning_tokens")

    return usage


def _is_timeout_or_transient(msg: str) -> bool:
    markers = (
        "timeout",
        "timed out",
        "apitimeouterror",
        "readtimeout",
        "connection reset",
        "connection aborted",
        "server disconnected",
        "502",
        "503",
        "504",
    )
    return any(marker in msg for marker in markers)


def _is_transport_error(exc: Exception) -> bool:
    """Heuristic: treat typical httpx/httpcore/OpenAI connection failures as retryable."""
    name = exc.__class__.__name__.lower()
    msg = str(exc).lower()

    if "apiconnectionerror" in name:
        return True
    if "remoteprotocolerror" in name or "protocolerror" in name:
        return True
    if "connecterror" in name or "readerror" in name or "writeerror" in name:
        return True

    markers = (
        "server disconnected",
        "connection error",
        "connection reset",
        "connection aborted",
        "broken pipe",
        "econnreset",
        "econnaborted",
        "remote end closed connection",
        "unexpected eof",
        "tls",
        "ssl",
        "handshake",
    )
    return any(m in msg for m in markers)

def _is_rate_limited(msg: str) -> bool:
    markers = (
        "rate limit",
        "rate_limit_exceeded",
        "tokens per min",
        "too many requests",
        "error code: 429",
    )
    return any(marker in msg for marker in markers)


def _extract_retry_after_sec(msg: str) -> Optional[float]:
    m = re.search(r"try again in\s+([0-9]+(?:\.[0-9]+)?)s", msg, flags=re.IGNORECASE)
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None


def _read_text_from_part(part: Any) -> str:
    text_val: Any = None

    if isinstance(part, dict):
        if part.get("json") is not None:
            try:
                return json.dumps(part.get("json"), ensure_ascii=False)
            except Exception:
                pass

        text_val = part.get("text")
        if isinstance(text_val, dict):
            text_val = text_val.get("value") or text_val.get("text")
        if not text_val:
            ot = part.get("output_text")
            if isinstance(ot, str):
                text_val = ot
        if not text_val:
            args = part.get("arguments")
            if isinstance(args, str) and args.strip().startswith("{"):
                text_val = args
    else:
        json_obj = getattr(part, "json", None)
        if json_obj is not None:
            try:
                return json.dumps(json_obj, ensure_ascii=False)
            except Exception:
                pass

        text_obj = getattr(part, "text", None)
        if isinstance(text_obj, dict):
            text_val = text_obj.get("value") or text_obj.get("text")
        else:
            text_val = text_obj

        if not text_val:
            ot = getattr(part, "output_text", None)
            if isinstance(ot, str):
                text_val = ot
        if not text_val:
            args = getattr(part, "arguments", None)
            if isinstance(args, str) and args.strip().startswith("{"):
                text_val = args

    return str(text_val or "").strip()


def _extract_response_text(resp: Any) -> str:
    raw = getattr(resp, "output_text", None)
    if raw:
        return str(raw).strip()

    chunks = []
    output = getattr(resp, "output", None)
    if output and isinstance(output, list):
        for item in output:
            content = getattr(item, "content", None)
            if content is None and isinstance(item, dict):
                content = item.get("content")

            if content and isinstance(content, list):
                for part in content:
                    txt = _read_text_from_part(part)
                    if txt:
                        chunks.append(txt)
                continue

            # Fallback for tool/function style items with JSON arguments.
            args = None
            if isinstance(item, dict):
                args = item.get("arguments")
            else:
                args = getattr(item, "arguments", None)
            if isinstance(args, str) and args.strip().startswith("{"):
                chunks.append(args.strip())

    return "\n".join(chunks).strip()


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


def _file_to_data_url(path: str) -> str:
    mime = _guess_mime_type(path)
    with open(path, "rb") as fh:
        data = b64encode(fh.read()).decode("ascii")
    return f"data:{mime};base64,{data}"


def call_markdown_vision(
    client: OpenAI,
    *,
    model: str,
    instructions: str,
    user_prompt: str,
    image_paths: list[str],
    reasoning_effort: Optional[str],
    max_output_tokens: int,
    timeout_sec: float | None,
    max_retries: int,
    service_tier: str,
    use_idempotency: bool,
    doc_hash: str,
    chunk_index: int,
    verbosity: str = "low",
) -> Tuple[str, Dict[str, int], str]:
    last_raw = ""

    content = [{"type": "input_text", "text": user_prompt}]
    for image_path in image_paths:
        content.append(
            {
                "type": "input_image",
                "image_url": _file_to_data_url(image_path),
                "detail": "high",
            }
        )

    for attempt in range(1, max_retries + 1):
        try:
            headers: Dict[str, str] = {}
            if use_idempotency:
                headers["Idempotency-Key"] = make_idempotency_key(doc_hash, chunk_index, model, user_prompt)

            kwargs: Dict[str, Any] = {
                "model": model,
                "instructions": instructions,
                "input": [{"role": "user", "content": content}],
                "max_output_tokens": max_output_tokens,
                "text": {"verbosity": verbosity},
            }
            if reasoning_effort and str(reasoning_effort).lower() != "none":
                kwargs["reasoning"] = {"effort": reasoning_effort}
            if service_tier and service_tier != "auto":
                kwargs["service_tier"] = service_tier
            if headers:
                kwargs["extra_headers"] = headers
            if timeout_sec is not None:
                kwargs["timeout"] = timeout_sec

            def _create_with_compat(local_kwargs: Dict[str, Any]) -> Any:
                if hasattr(client.responses, "stream"):
                    try:
                        with client.responses.stream(**local_kwargs) as stream:
                            for _event in stream:
                                pass
                        return stream.get_final_response()
                    except TypeError:
                        lk = dict(local_kwargs)
                        lk.pop("service_tier", None)
                        lk.pop("extra_headers", None)
                        lk.pop("timeout", None)
                        with client.responses.stream(**lk) as stream:
                            for _event in stream:
                                pass
                        return stream.get_final_response()
                try:
                    return client.responses.create(**local_kwargs)
                except TypeError:
                    lk = dict(local_kwargs)
                    lk.pop("service_tier", None)
                    lk.pop("extra_headers", None)
                    lk.pop("timeout", None)
                    return client.responses.create(**lk)

            try:
                resp = _create_with_compat(kwargs)
            except Exception as create_exc:
                create_msg = str(create_exc).lower()
                if "reasoning.effort" in create_msg or ("unsupported parameter" in create_msg and "reasoning" in create_msg):
                    kwargs.pop("reasoning", None)
                    resp = _create_with_compat(kwargs)
                elif "text.verbosity" in create_msg and str(verbosity).lower() != "medium":
                    kwargs["text"] = {"verbosity": "medium"}
                    resp = _create_with_compat(kwargs)
                else:
                    raise
            last_raw = _extract_response_text(resp).strip()
            if not last_raw:
                raise ValueError("Empty model response text")
            tier = str(getattr(resp, "service_tier", "")) or str(getattr(resp, "serviceTier", "")) or "unknown"
            return last_raw, extract_usage(resp), tier

        except Exception as exc:
            msg = str(exc).lower()
            if _is_timeout_or_transient(msg) or _is_rate_limited(msg) or _is_transport_error(exc):
                if attempt < max_retries:
                    retry_after = _extract_retry_after_sec(msg)
                    if retry_after is not None:
                        sleep_sec = retry_after + random.uniform(0.2, 1.0)
                    elif _is_rate_limited(msg):
                        sleep_sec = min(45.0, 5.0 * attempt) + random.uniform(0.3, 1.2)
                    else:
                        sleep_sec = min(180.0, 4.0 * (1.9 ** (attempt - 1))) + random.uniform(0.3, 1.2)
                    _print_retry(attempt, max_retries, sleep_sec, exc)
                    time.sleep(sleep_sec)
                    continue

                if _is_rate_limited(msg):
                    raise RuntimeError("OpenAI vision rate limit exceeded and retries exhausted.") from exc
                raise RuntimeError(
                    f"OpenAI vision transport-failed/timeouted ({exc.__class__.__name__}) and retries are exhausted."
                ) from exc

            if attempt < max_retries:
                time.sleep(min(12.0, 2.0 * attempt))
                continue

            raise RuntimeError(f"OpenAI vision call failed: {exc}\nRAW(head): {last_raw[:400]}") from exc

    raise RuntimeError("Unreachable")


def call_json_object(
    client: OpenAI,
    *,
    model: str,
    instructions: str,
    user_prompt: str,
    reasoning_effort: Optional[str],
    max_output_tokens: int,
    timeout_sec: float | None = None,
    max_retries: int,
    service_tier: str,
    use_idempotency: bool,
    doc_hash: str,
    chunk_index: int,
    verbosity: str = "low",
) -> Tuple[Dict[str, Any], Dict[str, int], str]:
    """Call OpenAI Responses API and parse strict JSON object."""
    last_raw = ""

    for attempt in range(1, max_retries + 1):
        try:
            headers: Dict[str, str] = {}
            if use_idempotency:
                headers["Idempotency-Key"] = make_idempotency_key(doc_hash, chunk_index, model, user_prompt)

            kwargs: Dict[str, Any] = {
                "model": model,
                "instructions": instructions,
                "input": user_prompt,
                "text": {"format": {"type": "json_object"}, "verbosity": verbosity},
                "max_output_tokens": max_output_tokens,
            }
            if reasoning_effort and str(reasoning_effort).lower() != "none":
                kwargs["reasoning"] = {"effort": reasoning_effort}
            if service_tier and service_tier != "auto":
                kwargs["service_tier"] = service_tier
            if headers:
                kwargs["extra_headers"] = headers
            if timeout_sec is not None:
                kwargs["timeout"] = timeout_sec

            def _create_with_compat(local_kwargs: Dict[str, Any]) -> Any:
                # Prefer streaming to keep the HTTP connection active during long generations.
                # Falls back to non-streaming for older SDKs.
                if hasattr(client.responses, "stream"):
                    try:
                        with client.responses.stream(**local_kwargs) as stream:
                            for _event in stream:
                                # Consuming events keeps the connection alive.
                                pass
                        return stream.get_final_response()
                    except TypeError:
                        # Older SDK: stream() may not accept service_tier/extra_headers/timeout
                        lk = dict(local_kwargs)
                        lk.pop("service_tier", None)
                        lk.pop("extra_headers", None)
                        lk.pop("timeout", None)
                        with client.responses.stream(**lk) as stream:
                            for _event in stream:
                                pass
                        return stream.get_final_response()

                # Fallback: standard create()
                try:
                    return client.responses.create(**local_kwargs)
                except TypeError:
                    lk = dict(local_kwargs)
                    lk.pop("service_tier", None)
                    lk.pop("extra_headers", None)
                    lk.pop("timeout", None)
                    return client.responses.create(**lk)

            try:
                resp = _create_with_compat(kwargs)
            except Exception as create_exc:
                create_msg = str(create_exc).lower()
                if "text.verbosity" in create_msg and str(verbosity).lower() != "medium":
                    kwargs["text"] = {"format": {"type": "json_object"}, "verbosity": "medium"}
                    resp = _create_with_compat(kwargs)
                else:
                    raise

            last_raw = _extract_response_text(resp)
            normalized = _normalize_json_text(last_raw)
            if not normalized:
                raise ValueError("Empty model response text")

            obj = json.loads(normalized)
            tier = str(getattr(resp, "service_tier", "")) or str(getattr(resp, "serviceTier", "")) or "unknown"
            return obj, extract_usage(resp), tier

        except Exception as exc:
            msg = str(exc).lower()

            # Empty payload can happen on transient disconnects; treat as retryable.
            # (Handled by retry logic below.)

            if _is_timeout_or_transient(msg) or _is_rate_limited(msg) or _is_transport_error(exc):
                if attempt < max_retries:
                    retry_after = _extract_retry_after_sec(msg)
                    if retry_after is not None:
                        sleep_sec = retry_after + random.uniform(0.2, 1.0)
                    elif _is_rate_limited(msg):
                        sleep_sec = min(45.0, 5.0 * attempt) + random.uniform(0.3, 1.2)
                    else:
                        sleep_sec = min(180.0, 4.0 * (1.9 ** (attempt - 1))) + random.uniform(0.3, 1.2)
                    _print_retry(attempt, max_retries, sleep_sec, exc)
                    time.sleep(sleep_sec)
                    continue

                if _is_rate_limited(msg):
                    raise RuntimeError(
                        "OpenAI rate limit exceeded and retries exhausted. "
                        "Try again with --resume after cooldown, or reduce chunk size."
                    ) from exc

                raise RuntimeError(
                    f"OpenAI call transport-failed/timeouted ({exc.__class__.__name__}) and retries are exhausted."
                ) from exc

            if attempt < max_retries:
                time.sleep(min(12.0, 2.0 * attempt))
                continue

            raise RuntimeError(f"OpenAI call failed: {exc}\\nRAW(head): {last_raw[:400]}") from exc

    raise RuntimeError("Unreachable")
