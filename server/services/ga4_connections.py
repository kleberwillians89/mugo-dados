from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from .ig_supabase import sb_select
from .integration_errors import IntegrationError
from .single_tenant import resolve_ga4_context_for_client


GA4_READ_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"


def _text(value: Any) -> str:
    return str(value or "").strip()


def normalize_ga4_property_id(value: Any) -> str:
    return _text(value).removeprefix("properties/").strip()


@dataclass(frozen=True)
class GA4ConnectionContext:
    client_id: str
    property_id: str
    connection_id: Optional[str]
    auth_mode: str


async def resolve_ga4_connection_context(client_id: str) -> GA4ConnectionContext:
    cid = _text(client_id)
    rows = await sb_select(
        "integration_connections",
        select=(
            "id,client_id,provider,status,external_key,scopes,metadata,"
            "token_expires_at,updated_at"
        ),
        filters={"client_id": f"eq.{cid}", "provider": "eq.ga4"},
        order="updated_at.desc",
        limit=20,
    )
    candidates = [
        row
        for row in rows
        if _text(row.get("status")).lower() != "disconnected"
    ]
    if candidates:
        row = candidates[0]
        if _text(row.get("client_id")) != cid:
            raise IntegrationError(
                "A conexão Google não pertence à empresa selecionada.",
                status_code=403,
                code="GA4_TENANT_MISMATCH",
                provider="google",
            )
        status = _text(row.get("status")).lower()
        if status in {"needs_reauth", "reauth_required", "token_expired", "error"}:
            raise IntegrationError(
                "A autorização Google expirou ou requer nova conexão.",
                status_code=401,
                code="GOOGLE_REAUTH_REQUIRED",
                provider="google",
            )
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        property_id = normalize_ga4_property_id(metadata.get("ga4_property_id"))
        if not property_id:
            raise IntegrationError(
                "Selecione uma propriedade GA4 na Central de Conexões.",
                status_code=409,
                code="GA4_PROPERTY_SELECTION_REQUIRED",
                provider="google",
            )
        scopes = {
            _text(scope)
            for scope in (row.get("scopes") or [])
            if _text(scope)
        }
        if scopes and GA4_READ_SCOPE not in scopes:
            raise IntegrationError(
                "A conexão Google não possui permissão de leitura do GA4.",
                status_code=403,
                code="GOOGLE_INSUFFICIENT_SCOPE",
                provider="google",
            )
        return GA4ConnectionContext(
            client_id=cid,
            property_id=property_id,
            connection_id=_text(row.get("id")) or None,
            auth_mode="oauth",
        )

    try:
        legacy_client_id, legacy_property_id = resolve_ga4_context_for_client(cid)
    except RuntimeError as exc:
        raise IntegrationError(
            "Nenhuma conexão Google ativa foi encontrada para a empresa selecionada.",
            status_code=404,
            code="GA4_CONNECTION_NOT_FOUND",
            provider="google",
        ) from exc
    return GA4ConnectionContext(
        client_id=legacy_client_id,
        property_id=normalize_ga4_property_id(legacy_property_id),
        connection_id=None,
        auth_mode="legacy",
    )
