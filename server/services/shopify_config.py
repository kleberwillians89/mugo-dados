from __future__ import annotations

import os
import re


DEFAULT_SHOPIFY_ADMIN_API_VERSION = "2026-07"
_VERSION_PATTERN = re.compile(r"^\d{4}-(01|04|07|10)$")


def resolve_shopify_admin_api_version() -> str:
    value = (os.getenv("SHOPIFY_ADMIN_API_VERSION") or "").strip()
    if not value:
        return DEFAULT_SHOPIFY_ADMIN_API_VERSION
    if not _VERSION_PATTERN.fullmatch(value):
        raise RuntimeError(
            "SHOPIFY_ADMIN_API_VERSION inválida. Use o formato AAAA-MM."
        )
    return value


SHOPIFY_ADMIN_API_VERSION = resolve_shopify_admin_api_version()


def shopify_admin_url(shop_domain: str, resource: str) -> str:
    normalized_resource = str(resource or "").strip().lstrip("/")
    return (
        f"https://{shop_domain}/admin/api/"
        f"{SHOPIFY_ADMIN_API_VERSION}/{normalized_resource}"
    )
