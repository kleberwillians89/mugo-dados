from __future__ import annotations

import os
import time
import traceback
from contextvars import ContextVar, Token
from typing import Any, Dict, Optional

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from services.auth import get_user_id_from_bearer
from services.tenant import resolve_connection_id


_REQUEST_ID: ContextVar[str] = ContextVar("request_id", default="")


def _set_request_id(value: str) -> Token[str]:
    return _REQUEST_ID.set(str(value or ""))


def _reset_request_id(token: Token[str]) -> None:
    _REQUEST_ID.reset(token)


def _pick_client_id(client_id: Optional[str], x_client_id: Optional[str]) -> Optional[str]:
    return (client_id or x_client_id or "").strip() or None


async def _validated_connection_id(
    *,
    client_id: str,
    connection_id: Optional[str],
    authorization: Optional[str],
) -> Optional[str]:
    return await resolve_connection_id(
        connection_id,
        client_id=client_id,
        authorization=authorization,
    )


def _require_cron_secret(x_cron_secret: Optional[str]) -> None:
    expected = (os.getenv("CRON_SECRET") or "").strip()
    if not expected:
        raise HTTPException(status_code=500, detail="CRON_SECRET não configurado")
    if not x_cron_secret or x_cron_secret.strip() != expected:
        raise HTTPException(status_code=401, detail="Cron não autorizado")


def _request_origin(request: Request) -> str:
    return f"{request.url.scheme}://{request.url.netloc}"


def _clean(value: Optional[str]) -> str:
    return str(value or "").strip()


def _clip(value: Optional[str], size: int = 240) -> str:
    text = _clean(value)
    if len(text) <= size:
        return text
    return f"{text[:size]}..."


async def _user_from_authorization(authorization: Optional[str]) -> str:
    try:
        uid = await get_user_id_from_bearer(authorization)
        return _clean(uid) or "-"
    except Exception as exc:
        return f"auth_lookup_failed:{exc.__class__.__name__}"


async def _log_endpoint_call(
    *,
    endpoint: str,
    authorization: Optional[str],
    x_client_id: Optional[str],
    client_id: Optional[str] = None,
    connection_id: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    days: Optional[int] = None,
) -> str:
    user_id = await _user_from_authorization(authorization)
    print(
        "[api][call] "
        f"endpoint={endpoint} user={user_id} x_client_id={_clean(x_client_id) or '-'} "
        f"client_id={_clean(client_id) or '-'} connection_id={_clean(connection_id) or '-'} "
        f"days={days if days is not None else '-'} "
        f"start={_clean(start) or '-'} end={_clean(end) or '-'}"
    )
    return user_id


def _log_endpoint_error(
    *,
    endpoint: str,
    exc: Exception,
    user_id: Optional[str],
    x_client_id: Optional[str],
    client_id: Optional[str] = None,
    connection_id: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    days: Optional[int] = None,
) -> None:
    print(
        "[api][error] "
        f"endpoint={endpoint} user={_clean(user_id) or '-'} x_client_id={_clean(x_client_id) or '-'} "
        f"client_id={_clean(client_id) or '-'} connection_id={_clean(connection_id) or '-'} "
        f"days={days if days is not None else '-'} "
        f"start={_clean(start) or '-'} end={_clean(end) or '-'} "
        f"error_type={exc.__class__.__name__} error={_clip(str(exc), 500) or '-'}"
    )
    print(traceback.format_exc())


def _structured_error_response(
    *,
    endpoint: str,
    exc: Exception,
    status_code: int,
    code: str,
) -> JSONResponse:
    public_message = getattr(exc, "public_message", None)
    public_code = getattr(exc, "code", None)
    retryable = getattr(exc, "retryable", None)
    if isinstance(exc, HTTPException):
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        message = _clip(
            str(detail.get("message") or (exc.detail if isinstance(exc.detail, str) else "")), 500
        ) or f"HTTP {exc.status_code}"
        public_code = detail.get("code") or public_code
    elif isinstance(public_message, str) and public_message.strip():
        message = _clip(public_message, 500)
    else:
        message = "Não foi possível concluir a consulta."
    normalized_code = str(public_code or code).upper()
    request_id = _REQUEST_ID.get()
    normalized_retryable = bool(retryable) if isinstance(retryable, bool) else status_code == 429 or status_code >= 500
    return JSONResponse(
        status_code=status_code,
        content={
            "ok": False,
            "code": normalized_code,
            "message": message,
            "status": status_code,
            "retryable": normalized_retryable,
            "path": endpoint,
            "request_id": request_id,
            "detail": {"code": normalized_code, "message": message, "request_id": request_id, "reason": "request_failed"},
        },
    )


def _runtime_error_status(exc: Exception, *, default_status: int = 400) -> int:
    explicit_status = getattr(exc, "status_code", None)
    if isinstance(explicit_status, int):
        return explicit_status
    message = _clean(str(exc)).lower()
    config_signals = (
        "não configurado",
        "nao configurado",
        "configure ",
        "inválida",
        "invalida",
        "missing environment variable",
        "invalid environment variable",
        "credenciais do ga4",
        "google_application_credentials",
        "ga4_credentials_path",
        "ambiente local/dev",
    )
    if any(signal in message for signal in config_signals):
        return 500
    return default_status


def _started() -> float:
    return time.perf_counter()


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _cache_key(parts: Dict[str, Any]) -> str:
    normalized = {k: str(v) for k, v in sorted(parts.items(), key=lambda item: item[0])}
    return "|".join([f"{k}={v}" for k, v in normalized.items()])


def _log_endpoint_done(
    *,
    endpoint: str,
    started: float,
    user_id: Optional[str],
    x_client_id: Optional[str],
    client_id: Optional[str] = None,
    connection_id: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    days: Optional[int] = None,
    cache_hit: Optional[bool] = None,
) -> None:
    cache_text = "-"
    if cache_hit is not None:
        cache_text = "1" if cache_hit else "0"
    print(
        "[api][done] "
        f"endpoint={endpoint} user={_clean(user_id) or '-'} x_client_id={_clean(x_client_id) or '-'} "
        f"client_id={_clean(client_id) or '-'} connection_id={_clean(connection_id) or '-'} "
        f"days={days if days is not None else '-'} "
        f"start={_clean(start) or '-'} end={_clean(end) or '-'} "
        f"cache_hit={cache_text} duration_ms={_elapsed_ms(started)}"
    )
