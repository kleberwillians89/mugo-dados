from __future__ import annotations

import os
from typing import Optional


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _normalize_ga4_property_id(value: str) -> str:
    property_id = (value or "").strip()
    if property_id.startswith("properties/"):
        return property_id.split("/", 1)[1].strip()
    return property_id


def get_default_client_id() -> str:
    client_id = _env("DEFAULT_CLIENT_ID")
    if client_id:
        return client_id

    compat_client_id = _env("DEFAULT_CLIENT_ID")
    if compat_client_id:
        print("[single_tenant] compat=DEFAULT_CLIENT_ID used for default client resolution")
        return compat_client_id

    raise RuntimeError("DEFAULT_CLIENT_ID não configurado para o backend single-tenant.")


def get_default_shopify_domain() -> str:
    return _env("SHOPIFY_SHOP_DOMAIN").lower()


def get_default_ga4_property_id() -> str:
    for env_name in ("GA4_PROPERTY_ID", "GA4_PROPERTY_ID"):
        value = _env(env_name)
        if value:
            return _normalize_ga4_property_id(value)

    raise RuntimeError("GA4_PROPERTY_ID não configurado para o backend single-tenant.")


def get_client_client_id() -> str:
    client_id = _env("CLIENT_CLIENT_ID")
    if client_id:
        return client_id

    raise RuntimeError("CLIENT_CLIENT_ID não configurado para GA4.")


def get_client_ga4_property_id() -> str:
    value = _env("CLIENT_GA4_PROPERTY_ID")
    if value:
        return _normalize_ga4_property_id(value)

    raise RuntimeError("CLIENT_GA4_PROPERTY_ID não configurado para GA4.")


def get_client_meta_ad_account_id() -> str:
    ad_account_id = _env("CLIENT_META_AD_ACCOUNT_ID")
    if ad_account_id:
        return ad_account_id if ad_account_id.startswith("act_") else f"act_{ad_account_id}"

    raise RuntimeError("CLIENT_META_AD_ACCOUNT_ID não configurado para Meta Ads.")


def is_known_single_tenant_client_id(client_id: Optional[str]) -> bool:
    requested = (client_id or "").strip()
    return bool(requested and requested in get_known_single_tenant_client_ids())


def get_known_single_tenant_client_ids() -> tuple[str, ...]:
    ids: list[str] = []
    for env_name in ("DEFAULT_CLIENT_ID", "DEFAULT_CLIENT_ID", "CLIENT_CLIENT_ID"):
        value = _env(env_name)
        if value and value not in ids:
            ids.append(value)
    return tuple(ids)


def resolve_ga4_context_for_client(client_id: Optional[str] = None) -> tuple[str, str]:
    requested_client_id = (client_id or "").strip()

    client_client_id = _env("CLIENT_CLIENT_ID")
    if client_client_id and (not requested_client_id or requested_client_id == client_client_id):
        property_id = get_client_ga4_property_id()
        print(
            "[single_tenant][ga4] "
            f"requested_client_id={requested_client_id or '-'} resolved_client_id={client_client_id} "
            f"property_id={property_id} source=client"
        )
        return client_client_id, property_id

    default_client_id = _env("DEFAULT_CLIENT_ID") or _env("DEFAULT_CLIENT_ID")
    if default_client_id and requested_client_id == default_client_id:
        property_id = get_default_ga4_property_id()
        print(
            "[single_tenant][ga4] "
            f"requested_client_id={requested_client_id or '-'} resolved_client_id={default_client_id} "
            f"property_id={property_id} source=default"
        )
        return default_client_id, property_id

    raise RuntimeError(f"Cliente sem configuração GA4: {requested_client_id}")
