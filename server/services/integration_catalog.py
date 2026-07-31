from __future__ import annotations

from typing import Any, Dict, List


INTEGRATION_PROVIDERS: tuple[Dict[str, Any], ...] = (
    {
        "id": "meta",
        "name": "Meta e Instagram",
        "category": "marketing",
        "availability": "available",
        "resources": ["Páginas", "Instagram profissional", "Meta Ads"],
    },
    {
        "id": "google",
        "name": "Google",
        "category": "analytics",
        "availability": "available",
        "resources": ["Google Analytics 4", "Google Ads"],
    },
    {
        "id": "shopify",
        "name": "Shopify",
        "category": "commerce",
        "availability": "available",
        "resources": ["Pedidos", "Clientes", "Produtos"],
    },
    {
        "id": "merchant_center",
        "name": "Merchant Center",
        "category": "commerce",
        "availability": "configuration_unavailable",
        "resources": ["Catálogo e produtos"],
    },
    {
        "id": "tiktok",
        "name": "TikTok",
        "category": "marketing",
        "availability": "platform_update_pending",
        "resources": ["Conteúdo e mídia"],
    },
    {
        "id": "pinterest",
        "name": "Pinterest",
        "category": "marketing",
        "availability": "platform_update_pending",
        "resources": ["Conteúdo e mídia"],
    },
)


def public_integration_catalog() -> List[Dict[str, Any]]:
    return [dict(provider) for provider in INTEGRATION_PROVIDERS]
