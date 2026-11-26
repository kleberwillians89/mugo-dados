"""Resolucao unica de credencial/modelo de IA por empresa.

Sem linha persistida, clientes existentes continuam em ``platform_managed``.
Em ``byok`` a chave global nunca e consultada.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict

import httpx

from .crypto import decrypt_secret, encrypt_secret
from .ig_supabase import sb_get_one_by, sb_insert, sb_update

TABLE = "client_ai_settings"
DEFAULT_MODEL = "gpt-4.1-mini"
ALLOWED_MODELS: Dict[str, Dict[str, int]] = {
    "gpt-4.1-mini": {"max_output_tokens": 32768},
    "gpt-4.1": {"max_output_tokens": 32768},
    "gpt-4o-mini": {"max_output_tokens": 16384},
    "gpt-4o": {"max_output_tokens": 16384},
    "gpt-5": {"max_output_tokens": 32768},
    "gpt-5-mini": {"max_output_tokens": 32768},
}
OPERATION_LIMITS = {
    "default": 8192,
    "chat": 4096,
    "summary": 4096,
    "calendar": 8192,
    "matrix": 16384,
}


class AiRuntimeError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 409):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class AiRuntime:
    client_id: str
    mode: str
    provider: str
    model: str
    api_key: str


def model_catalog() -> list[Dict[str, Any]]:
    return [{"provider": "openai", "model": model, **limits} for model, limits in ALLOWED_MODELS.items()]


def validate_model(model: str) -> str:
    selected = str(model or "").strip()
    if selected not in ALLOWED_MODELS:
        raise AiRuntimeError("AI_MODEL_UNAVAILABLE", "O modelo selecionado nao esta liberado.", 422)
    return selected


def bounded_output_tokens(operation: str, requested: int | None, model: str) -> int:
    operation_limit = OPERATION_LIMITS.get(operation, OPERATION_LIMITS["default"])
    provider_limit = ALLOWED_MODELS[validate_model(model)]["max_output_tokens"]
    if requested is None:
        return min(operation_limit, provider_limit)
    if int(requested) <= 0:
        raise AiRuntimeError("AI_TOKEN_LIMIT_INVALID", "O limite de saida e invalido.", 422)
    return min(int(requested), operation_limit, provider_limit)


async def _row(client_id: str) -> Dict[str, Any] | None:
    # Testes/unitarios e ferramentas locais sem Supabase preservam o modo legado.
    # Em producao SUPABASE_URL e obrigatoria e a consulta continua fail-closed.
    if not (os.getenv("SUPABASE_URL") or "").strip():
        return None
    return await sb_get_one_by(TABLE, filters={"client_id": f"eq.{client_id}"})


async def public_settings(client_id: str) -> Dict[str, Any]:
    row = await _row(client_id)
    if not row:
        return {
            "client_id": client_id, "mode": "platform_managed", "provider": "openai",
            "model": (os.getenv("OPENAI_MODEL") or DEFAULT_MODEL).strip(),
            "credential_status": "platform", "has_credential": False,
            "credential_updated_at": None, "validated_at": None,
        }
    return {
        "client_id": client_id,
        "mode": row.get("mode") or "platform_managed",
        "provider": "openai",
        "model": row.get("model") or DEFAULT_MODEL,
        "credential_status": row.get("credential_status") or "missing",
        "has_credential": bool(row.get("encrypted_api_key")),
        "credential_updated_at": row.get("credential_updated_at"),
        "validated_at": row.get("validated_at"),
    }


async def resolve(client_id: str | None, requested_model: str | None = None) -> AiRuntime:
    cid = str(client_id or "").strip()
    if not cid:
        try:
            from .tenant import _REQUEST_CLIENT
            cid = str(_REQUEST_CLIENT.get() or "").strip()
        except Exception:  # noqa: BLE001 -- a ausencia do contexto e tratada abaixo
            cid = ""
    if not cid:
        environment = (os.getenv("APP_ENV") or "").strip().lower()
        if environment in {"production", "prod"}:
            raise AiRuntimeError("AI_TENANT_REQUIRED", "Empresa nao identificada.", 400)
        cid = "local-test"
    row = await _row(cid)
    mode = str((row or {}).get("mode") or "platform_managed")
    configured_model = str((row or {}).get("model") or os.getenv("OPENAI_MODEL") or DEFAULT_MODEL)
    model = validate_model(configured_model if mode == "byok" else (requested_model or configured_model))
    if mode == "byok":
        encrypted = str((row or {}).get("encrypted_api_key") or "")
        if not encrypted:
            raise AiRuntimeError("AI_BYOK_CREDENTIAL_MISSING", "Cadastre uma chave OpenAI para esta empresa.")
        try:
            key = decrypt_secret(encrypted)
        except RuntimeError as exc:
            raise AiRuntimeError("AI_BYOK_CREDENTIAL_INVALID", "A credencial desta empresa nao pode ser utilizada.", 503) from exc
        if not key:
            raise AiRuntimeError("AI_BYOK_CREDENTIAL_MISSING", "Cadastre uma chave OpenAI para esta empresa.")
        return AiRuntime(cid, mode, "openai", model, key)
    if mode != "platform_managed":
        raise AiRuntimeError("AI_MODE_INVALID", "A configuracao de IA desta empresa e invalida.", 503)
    key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        raise AiRuntimeError("AI_PROVIDER_NOT_CONFIGURED", "A IA da plataforma nao esta configurada.", 503)
    return AiRuntime(cid, mode, "openai", model, key)


async def validate_openai_key(api_key: str, model: str, *, timeout: float = 15) -> None:
    selected = validate_model(model)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                f"https://api.openai.com/v1/models/{selected}",
                headers={"Authorization": f"Bearer {api_key}"},
            )
    except httpx.TimeoutException as exc:
        raise AiRuntimeError("AI_PROVIDER_TIMEOUT", "A OpenAI demorou para validar a chave.", 504) from exc
    except httpx.HTTPError as exc:
        raise AiRuntimeError("AI_PROVIDER_ERROR", "Nao foi possivel validar a chave agora.", 502) from exc
    if response.status_code == 401:
        raise AiRuntimeError("AI_PROVIDER_AUTH", "A chave OpenAI e invalida.", 422)
    if response.status_code == 403:
        raise AiRuntimeError("AI_PROVIDER_PERMISSION", "A chave nao possui acesso ao modelo selecionado.", 422)
    if response.status_code == 404:
        raise AiRuntimeError("AI_MODEL_UNAVAILABLE", "O modelo selecionado nao esta disponivel para esta chave.", 422)
    if response.status_code >= 400:
        raise AiRuntimeError("AI_PROVIDER_ERROR", "A OpenAI recusou a validacao da chave.", 502)


async def save_settings(*, client_id: str, user_id: str, mode: str, model: str, api_key: str | None) -> Dict[str, Any]:
    selected_mode = str(mode or "").strip()
    if selected_mode not in {"platform_managed", "byok"}:
        raise AiRuntimeError("AI_MODE_INVALID", "Selecione um modo de IA valido.", 422)
    selected_model = validate_model(model)
    current = await _row(client_id)
    now = datetime.now(timezone.utc).isoformat()
    encrypted = (current or {}).get("encrypted_api_key")
    status = (current or {}).get("credential_status") or "missing"
    validated_at = (current or {}).get("validated_at")
    credential_updated_at = (current or {}).get("credential_updated_at")
    raw = str(api_key or "").strip()
    if raw:
        await validate_openai_key(raw, selected_model)
        encrypted = encrypt_secret(raw)
        status, validated_at, credential_updated_at = "valid", now, now
    elif selected_mode == "byok" and not encrypted:
        raise AiRuntimeError("AI_BYOK_CREDENTIAL_MISSING", "Cadastre e valide uma chave OpenAI.", 422)
    elif selected_mode == "byok" and encrypted and selected_model != str((current or {}).get("model") or ""):
        try:
            existing_key = decrypt_secret(str(encrypted))
        except RuntimeError as exc:
            raise AiRuntimeError("AI_BYOK_CREDENTIAL_INVALID", "A credencial desta empresa precisa ser cadastrada novamente.", 503) from exc
        await validate_openai_key(existing_key, selected_model)
        status, validated_at = "valid", now
    payload = {
        "mode": selected_mode, "provider": "openai", "model": selected_model,
        "encrypted_api_key": encrypted, "credential_status": status,
        "credential_updated_at": credential_updated_at, "validated_at": validated_at,
        "updated_by": user_id, "updated_at": now,
    }
    if current:
        await sb_update(TABLE, filters={"client_id": f"eq.{client_id}"}, patch=payload, returning="minimal")
    else:
        await sb_insert(TABLE, {"client_id": client_id, **payload}, returning="minimal")
    return await public_settings(client_id)


async def revoke_credential(*, client_id: str, user_id: str) -> Dict[str, Any]:
    current = await _row(client_id)
    if not current:
        return await public_settings(client_id)
    now = datetime.now(timezone.utc).isoformat()
    await sb_update(TABLE, filters={"client_id": f"eq.{client_id}"}, patch={
        "mode": "platform_managed", "encrypted_api_key": None, "credential_status": "missing",
        "credential_updated_at": now, "validated_at": None, "updated_by": user_id, "updated_at": now,
    }, returning="minimal")
    return await public_settings(client_id)
