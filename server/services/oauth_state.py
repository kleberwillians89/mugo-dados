from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from .ig_supabase import sb_insert, sb_select, sb_update


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode((value + "=" * ((4 - len(value) % 4) % 4)).encode("ascii"))


def _secret() -> str:
    value = _env("OAUTH_STATE_SECRET") or _env("TOKEN_ENCRYPTION_KEY")
    if len(value) < 32:
        raise RuntimeError("OAUTH_STATE_SECRET deve ter ao menos 32 caracteres.")
    return value


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sign(raw: bytes) -> str:
    return _b64(hmac.new(_secret().encode("utf-8"), raw, hashlib.sha256).digest())


async def create_oauth_state(
    *,
    provider: str,
    user_id: str,
    client_id: str,
    redirect_uri: str,
    context: Dict[str, Any] | None = None,
    ttl_seconds: int = 600,
) -> str:
    nonce = secrets.token_urlsafe(32)
    payload = {
        "sid": secrets.token_urlsafe(24),
        "provider": provider,
        "nonce": nonce,
        "iat": int(_now().timestamp()),
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    state = f"{_b64(raw)}.{_sign(raw)}"
    await sb_insert(
        "oauth_sessions",
        {
            "provider": provider,
            "state_hash": _hash(state),
            "nonce_hash": _hash(nonce),
            "user_id": user_id,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "context": context or {},
            "expires_at": _iso(_now() + timedelta(seconds=max(60, ttl_seconds))),
        },
        returning="minimal",
    )
    return state


async def consume_oauth_state(state: str, *, provider: str) -> Dict[str, Any]:
    value = str(state or "").strip()
    try:
        encoded, signature = value.split(".", 1)
        raw = _unb64(encoded)
    except Exception as exc:
        raise RuntimeError("State OAuth inválido.") from exc
    if not hmac.compare_digest(signature, _sign(raw)):
        raise RuntimeError("State OAuth inválido.")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise RuntimeError("State OAuth inválido.") from exc
    if payload.get("provider") != provider:
        raise RuntimeError("State OAuth pertence a outro provedor.")

    rows = await sb_select(
        "oauth_sessions",
        filters={"state_hash": f"eq.{_hash(value)}", "provider": f"eq.{provider}"},
        limit=1,
    )
    row = rows[0] if rows else None
    if not row:
        raise RuntimeError("State OAuth inválido ou desconhecido.")
    if row.get("consumed_at"):
        raise RuntimeError("Callback OAuth já utilizado.")
    expires_at = datetime.fromisoformat(str(row.get("expires_at")).replace("Z", "+00:00"))
    if expires_at <= _now():
        raise RuntimeError("State OAuth expirado.")
    if not hmac.compare_digest(str(row.get("nonce_hash") or ""), _hash(str(payload.get("nonce") or ""))):
        raise RuntimeError("Nonce OAuth inválido.")

    consumed_at = _iso(_now())
    updated = await sb_update(
        "oauth_sessions",
        filters={"id": f"eq.{row['id']}", "consumed_at": "is.null"},
        patch={"consumed_at": consumed_at},
        returning="representation",
    )
    if not updated:
        raise RuntimeError("Callback OAuth já utilizado.")
    return updated[0]
