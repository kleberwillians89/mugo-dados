"""
Camada canônica de leitura de conexões (Fase 3).

Consolida as duas fontes existentes — `integration_connections`
(autorização/configuração de meta, ga4, google_ads, shopify) e
`meta_connections` (projeções operacionais Meta: organic/paid, onde vive o
status real de sincronização) — num único contrato por cliente, sem alterar
nenhuma das duas tabelas e sem alterar os endpoints legados existentes.

Este módulo é SOMENTE LEITURA de composição: não insere, não atualiza, não
apaga. As escritas continuam exatamente onde já estavam (generic_connections,
meta_oauth, instagram_sync, ads_sync).
"""

from __future__ import annotations
from .request_performance import measured

from typing import Any, Dict, List, Optional

from .ig_supabase import sb_select

CANONICAL_PROVIDERS = ("meta", "ga4", "google_ads", "shopify")

# Status do provedor no eixo único "status" do contrato canônico.
_STATUS_DISCONNECTED = "disconnected"
_STATUS_CONNECTED = "connected"
_STATUS_NEEDS_CONFIGURATION = "needs_configuration"
_STATUS_TOKEN_EXPIRED = "token_expired"
_STATUS_PERMISSION_ERROR = "permission_error"

_SYNC_STATUS_MAP = {
    "success": "sync_success",
    "partial": "sync_success",
    "skipped": "sync_success",
    "error": "sync_error",
    "never": None,
    "": None,
}


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _metadata(row: Dict[str, Any]) -> Dict[str, Any]:
    value = row.get("metadata")
    return value if isinstance(value, dict) else {}


async def _load_integration_rows(client_id: str) -> List[Dict[str, Any]]:
    return await sb_select(
        "integration_connections",
        filters={"client_id": f"eq.{client_id}"},
        order="updated_at.desc",
        limit=200,
    )


async def _load_meta_operational_rows(client_id: str) -> List[Dict[str, Any]]:
    return await sb_select(
        "meta_connections",
        filters={"client_id": f"eq.{client_id}"},
        order="updated_at.desc",
        limit=200,
    )


def _pick_latest_operational(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Entre organic/paid, a mais recente por last_sync_at (ou updated_at)."""
    candidates = [row for row in rows if row]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda row: _safe_str(row.get("last_sync_at")) or _safe_str(row.get("updated_at")),
    )


def _canonical_status(
    *, auth_status: str, requires_reauth: bool, disconnected_at: Any, has_assets: bool
) -> str:
    if _safe_str(disconnected_at):
        return _STATUS_DISCONNECTED
    if requires_reauth:
        return _STATUS_PERMISSION_ERROR
    if auth_status == "token_expired":
        return _STATUS_TOKEN_EXPIRED
    if auth_status in {"not_configured", "disconnected"}:
        return _STATUS_DISCONNECTED
    if auth_status in {"connected", "updated", "importing", "stale", "connecting"} and not has_assets:
        return _STATUS_NEEDS_CONFIGURATION
    return _STATUS_CONNECTED


def _sync_status_for(last_sync_status: Any) -> Optional[str]:
    return _SYNC_STATUS_MAP.get(_safe_str(last_sync_status).lower(), None)


def _build_meta_entry(auth_row: Dict[str, Any], operational_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    metadata = _metadata(auth_row)
    organic = next(
        (row for row in operational_rows if _safe_str(row.get("platform")) == "instagram" and _safe_str(row.get("connection_type")) == "organic"),
        None,
    )
    paid = next(
        (row for row in operational_rows if _safe_str(row.get("platform")) == "meta_ads" and _safe_str(row.get("connection_type")) == "paid"),
        None,
    )
    latest = _pick_latest_operational([row for row in (paid, organic) if row])

    ad_account_id = _safe_str((paid or {}).get("ad_account_id")) or _safe_str(metadata.get("selected_ad_account_id"))
    ad_account_name = _safe_str((paid or {}).get("ad_account_name")) or _safe_str(metadata.get("selected_ad_account_name"))
    instagram_account_id = _safe_str((organic or {}).get("ig_user_id")) or _safe_str(metadata.get("selected_instagram_id"))
    instagram_account_name = _safe_str((organic or {}).get("username")) or _safe_str(metadata.get("selected_instagram_username"))
    facebook_page_id = _safe_str(metadata.get("selected_page_id"))
    facebook_page_name = _safe_str(metadata.get("selected_page_name"))
    business_id = _safe_str(metadata.get("selected_business_id"))
    business_name = _safe_str(metadata.get("selected_business_name"))

    has_assets = bool(business_id or ad_account_id or instagram_account_id or facebook_page_id)
    requires_reauth = bool(auth_row.get("last_error")) and _safe_str(auth_row.get("status")) == "reauth_required"
    last_sync_status = _safe_str((latest or {}).get("last_sync_status"))

    return {
        "provider": "meta",
        "connection_id": _safe_str(auth_row.get("id")),
        "status": _canonical_status(
            auth_status=_safe_str(auth_row.get("status")),
            requires_reauth=requires_reauth,
            disconnected_at=auth_row.get("disconnected_at"),
            has_assets=has_assets,
        ),
        "authorization_status": "invalid" if requires_reauth else "valid",
        "sync_status": _sync_status_for(last_sync_status),
        "account": {
            "id": _safe_str(auth_row.get("account_id")) or None,
            "name": _safe_str(auth_row.get("account_name")) or None,
        },
        "assets": {
            "business_id": business_id or None,
            "business_name": business_name or None,
            "ad_account_id": ad_account_id or None,
            "ad_account_name": ad_account_name or None,
            "instagram_account_id": instagram_account_id or None,
            "instagram_account_name": instagram_account_name or None,
            "facebook_page_id": facebook_page_id or None,
            "facebook_page_name": facebook_page_name or None,
        },
        "last_sync_at": _safe_str((latest or {}).get("last_sync_at")) or None,
        "last_successful_sync_at": (
            _safe_str((latest or {}).get("last_sync_at")) if last_sync_status == "success" else None
        ),
        "last_error": _safe_str((latest or {}).get("last_error")) or _safe_str(auth_row.get("last_error")) or None,
        "updated_at": _safe_str(auth_row.get("updated_at")) or None,
    }


def _build_ga4_entry(auth_row: Dict[str, Any]) -> Dict[str, Any]:
    metadata = _metadata(auth_row)
    property_id = _safe_str(metadata.get("ga4_property_id"))
    property_name = _safe_str(metadata.get("ga4_property_name"))
    has_assets = bool(property_id)
    requires_reauth = _safe_str(auth_row.get("status")) == "reauth_required"

    return {
        "provider": "ga4",
        "connection_id": _safe_str(auth_row.get("id")),
        "status": _canonical_status(
            auth_status=_safe_str(auth_row.get("status")),
            requires_reauth=requires_reauth,
            disconnected_at=auth_row.get("disconnected_at"),
            has_assets=has_assets,
        ),
        "authorization_status": "invalid" if requires_reauth else "valid",
        "sync_status": None,
        "account": {
            "id": _safe_str(metadata.get("ga4_account_id")) or None,
            "name": _safe_str(auth_row.get("account_name")) or None,
        },
        "assets": {
            "property_id": property_id or None,
            "property_name": property_name or None,
            "stream_id": _safe_str(metadata.get("ga4_stream_id")) or None,
            "stream_name": _safe_str(metadata.get("ga4_stream_name")) or None,
        },
        "last_sync_at": _safe_str(auth_row.get("last_sync_at")) or None,
        "last_successful_sync_at": _safe_str(auth_row.get("last_sync_at")) or None if not auth_row.get("last_error") else None,
        "last_error": _safe_str(auth_row.get("last_error")) or None,
        "updated_at": _safe_str(auth_row.get("updated_at")) or None,
    }


def _build_google_ads_entry(auth_row: Dict[str, Any]) -> Dict[str, Any]:
    metadata = _metadata(auth_row)
    customer_id = _safe_str(metadata.get("google_ads_customer_id"))
    has_assets = bool(customer_id)
    requires_reauth = _safe_str(auth_row.get("status")) == "reauth_required"

    return {
        "provider": "google_ads",
        "connection_id": _safe_str(auth_row.get("id")),
        "status": _canonical_status(
            auth_status=_safe_str(auth_row.get("status")),
            requires_reauth=requires_reauth,
            disconnected_at=auth_row.get("disconnected_at"),
            has_assets=has_assets,
        ),
        "authorization_status": "invalid" if requires_reauth else "valid",
        "sync_status": None,
        "account": {
            "id": customer_id or None,
            # Nome da conta Google Ads selecionada (lido via GAQL na listagem).
            # account_name da linha é o e-mail Google da autorização, não a
            # conta de mídia — por isso não é usado aqui. Nenhum nome é inventado.
            "name": _safe_str(metadata.get("google_ads_customer_name")) or None,
        },
        "assets": {
            "customer_id": customer_id or None,
            "customer_name": _safe_str(metadata.get("google_ads_customer_name")) or None,
            "login_customer_id": _safe_str(metadata.get("google_ads_login_customer_id")) or None,
        },
        "last_sync_at": _safe_str(auth_row.get("last_sync_at")) or None,
        "last_successful_sync_at": _safe_str(auth_row.get("last_sync_at")) or None if not auth_row.get("last_error") else None,
        "last_error": _safe_str(auth_row.get("last_error")) or None,
        "updated_at": _safe_str(auth_row.get("updated_at")) or None,
    }


def _build_shopify_entry(auth_row: Dict[str, Any]) -> Dict[str, Any]:
    metadata = _metadata(auth_row)
    domain = _safe_str(metadata.get("shop_domain")) or _safe_str(auth_row.get("external_key"))
    has_assets = bool(domain)
    requires_reauth = _safe_str(auth_row.get("status")) == "reauth_required"

    return {
        "provider": "shopify",
        "connection_id": _safe_str(auth_row.get("id")),
        "status": _canonical_status(
            auth_status=_safe_str(auth_row.get("status")),
            requires_reauth=requires_reauth,
            disconnected_at=auth_row.get("disconnected_at"),
            has_assets=has_assets,
        ),
        "authorization_status": "invalid" if requires_reauth else "valid",
        "sync_status": None,
        "account": {
            "domain": domain or None,
            "name": _safe_str(auth_row.get("account_name")) or None,
        },
        "assets": {
            "shop_domain": domain or None,
        },
        "last_sync_at": _safe_str(auth_row.get("last_sync_at")) or None,
        "last_successful_sync_at": _safe_str(auth_row.get("last_sync_at")) or None if not auth_row.get("last_error") else None,
        "last_error": _safe_str(auth_row.get("last_error")) or None,
        "updated_at": _safe_str(auth_row.get("updated_at")) or None,
    }


def _build_fbits_entry(auth_row: Dict[str, Any]) -> Dict[str, Any]:
    # Token por tenant; nenhuma informação da credencial sai daqui.
    status = _safe_str(auth_row.get("status"))
    requires_reauth = status == "reauth_required"
    last_error = _safe_str(auth_row.get("last_error")) or None
    return {
        "provider": "fbits",
        "connection_id": _safe_str(auth_row.get("id")),
        "status": _canonical_status(
            auth_status=status,
            requires_reauth=requires_reauth,
            disconnected_at=auth_row.get("disconnected_at"),
            has_assets=True,
        ),
        "authorization_status": "invalid" if requires_reauth else "valid",
        "sync_status": "sync_error" if status == "sync_error" else ("sync_success" if auth_row.get("last_sync_at") and not last_error else None),
        "account": {"name": _safe_str(auth_row.get("account_name")) or None},
        "assets": {},
        "last_sync_at": _safe_str(auth_row.get("last_sync_at")) or None,
        "last_successful_sync_at": (_safe_str(auth_row.get("last_sync_at")) or None) if not last_error else None,
        "last_error": last_error,
        "updated_at": _safe_str(auth_row.get("updated_at")) or None,
    }


_BUILDERS = {
    "ga4": _build_ga4_entry,
    "google_ads": _build_google_ads_entry,
    "shopify": _build_shopify_entry,
    "fbits": _build_fbits_entry,
}


@measured("data_integrations")
async def get_client_connections(client_id: str) -> Dict[str, Any]:
    """
    Contrato canônico consolidado por cliente. client_id já deve ter sido
    resolvido/validado pelo tenant service pelo chamador — este módulo não
    faz autorização, só composição de leitura.
    """
    cid = _safe_str(client_id)
    integration_rows = await _load_integration_rows(cid)
    meta_operational_rows = await _load_meta_operational_rows(cid)

    connections: List[Dict[str, Any]] = []
    for row in integration_rows:
        provider = _safe_str(row.get("provider")).lower()
        if provider == "meta":
            connections.append(_build_meta_entry(row, meta_operational_rows))
        elif provider in _BUILDERS:
            connections.append(_BUILDERS[provider](row))
        # 'instagram' e 'fbits' (se existirem como linhas de autorização
        # separadas) não têm builder canônico dedicado ainda — não incluídos
        # para não inventar um contrato não solicitado nesta fase.

    return {
        "client_id": cid,
        "connections": connections,
    }
