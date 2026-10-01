from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from .meta_config import META_GRAPH_BASE_URL


META_BASE = META_GRAPH_BASE_URL
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_SENSITIVE_QUERY_KEYS = {
    "access_token", "client_secret", "code", "fb_exchange_token", "state",
    "input_token", "appsecret_proof",
}


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _clip(value: Any, size: int = 600) -> str:
    text = _safe_str(value)
    if len(text) <= size:
        return text
    return f"{text[:size]}..."


def _safe_url(value: Any) -> str:
    raw = _safe_str(value)
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
        query = urlencode([
            (key, "[redacted]" if key.lower() in _SENSITIVE_QUERY_KEYS else item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        ])
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, parsed.fragment))
    except Exception:
        return raw.split("?", 1)[0]


def _context_text(context: Optional[Dict[str, Any]]) -> str:
    parts = []
    for key, value in (context or {}).items():
        if str(key).lower() in _SENSITIVE_QUERY_KEYS or "secret" in str(key).lower():
            continue
        text = _safe_str(value)
        if text:
            parts.append(f"{key}={text}")
    return " ".join(parts) if parts else "-"


def _parse_error_payload(response: httpx.Response) -> Dict[str, Any]:
    try:
        payload = response.json()
    except Exception:
        return {}
    if isinstance(payload, dict):
        error_obj = payload.get("error")
        if isinstance(error_obj, dict):
            return error_obj
    return {}


class MetaApiError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        error_code: Optional[int] = None,
        error_subcode: Optional[int] = None,
        retryable: bool = False,
        invalid_oauth: bool = False,
        rate_limited: bool = False,
        response_text: str = "",
        url: str = "",
        trace_id: str = "",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.error_subcode = error_subcode
        self.retryable = retryable
        self.invalid_oauth = invalid_oauth
        self.rate_limited = rate_limited
        self.response_text = response_text
        self.url = url
        # fbtrace_id da Meta (identificador público para suporte; não é segredo).
        self.trace_id = trace_id


def _http_error_from_response(response: httpx.Response) -> MetaApiError:
    error_payload = _parse_error_payload(response)
    error_code = error_payload.get("code")
    error_subcode = error_payload.get("error_subcode")
    message = _safe_str(error_payload.get("message")) or _clip(response.text)
    invalid_oauth = (
        int(error_code or 0) == 190
        or _safe_str(error_payload.get("type")).lower() == "oauthexception"
        or "oauth" in message.lower()
    )
    rate_limited = response.status_code == 429 or int(error_code or 0) in {4, 17, 32, 613}
    retryable = response.status_code in _RETRYABLE_STATUS_CODES or rate_limited
    return MetaApiError(
        f"Meta API error {response.status_code}: {message or 'unknown_error'}",
        status_code=response.status_code,
        error_code=int(error_code) if str(error_code or "").isdigit() else None,
        error_subcode=int(error_subcode) if str(error_subcode or "").isdigit() else None,
        retryable=retryable and not invalid_oauth,
        invalid_oauth=invalid_oauth,
        rate_limited=rate_limited,
        response_text=_clip(response.text),
        url=_safe_url(response.request.url),
        trace_id=_safe_str(error_payload.get("fbtrace_id")) or _safe_str(response.headers.get("x-fb-trace-id")),
    )


def _network_error(exc: Exception, *, url: str) -> MetaApiError:
    return MetaApiError(
        f"Meta request failed: {_safe_str(exc) or exc.__class__.__name__}",
        status_code=None,
        retryable=isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)),
        invalid_oauth=False,
        rate_limited=False,
        response_text="",
        url=_safe_url(url),
    )


async def meta_get_json(
    path_or_url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    timeout: int = 45,
    retries: int = 3,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    target_url = path_or_url if path_or_url.startswith("http") else f"{META_BASE}{path_or_url}"
    max_attempts = max(1, int(retries or 1))

    for attempt in range(1, max_attempts + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(target_url, params=params)
            if response.status_code >= 400:
                err = _http_error_from_response(response)
                if err.retryable and attempt < max_attempts:
                    print(
                        "[meta_http][retry] "
                        f"attempt={attempt}/{max_attempts} reason=http_{err.status_code} "
                        f"context={_context_text(context)} url={_clip(_safe_url(target_url), 220)}"
                    )
                    await asyncio.sleep(min(1.5, 0.35 * attempt))
                    continue
                print(
                    "[meta_http][error] "
                    f"attempt={attempt}/{max_attempts} status={err.status_code or '-'} "
                    f"invalid_oauth={1 if err.invalid_oauth else 0} retryable={1 if err.retryable else 0} "
                    f"context={_context_text(context)} url={_clip(_safe_url(target_url), 220)}"
                )
                raise err

            payload = response.json()
            if not isinstance(payload, dict):
                raise MetaApiError(
                    "Meta API retornou payload inválido.",
                    status_code=response.status_code,
                    retryable=False,
                    response_text=_clip(response.text),
                    url=_safe_url(response.request.url),
                )
            return payload
        except MetaApiError:
            raise
        except Exception as exc:
            err = _network_error(exc, url=target_url)
            if err.retryable and attempt < max_attempts:
                print(
                    "[meta_http][retry] "
                    f"attempt={attempt}/{max_attempts} reason={exc.__class__.__name__} "
                    f"context={_context_text(context)} url={_clip(_safe_url(target_url), 220)}"
                )
                await asyncio.sleep(min(1.5, 0.35 * attempt))
                continue
            print(
                "[meta_http][error] "
                f"attempt={attempt}/{max_attempts} status=- invalid_oauth=0 retryable={1 if err.retryable else 0} "
                f"context={_context_text(context)} url={_clip(_safe_url(target_url), 220)}"
            )
            raise err

    raise RuntimeError("Meta HTTP flow should have returned or raised earlier.")


def dump_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return "{}"
