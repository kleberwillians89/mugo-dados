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
        "availability": "available",
        "resources": ["Anúncios", "Vídeos e seguidores"],
    },
    {
        "id": "pinterest",
        "name": "Pinterest",
        "category": "marketing",
        "availability": "available",
        "resources": ["Anúncios", "Pins e audiência"],
    },
    {
        "id": "linkedin",
        "name": "LinkedIn",
        "category": "marketing",
        "availability": "available",
        "resources": ["Anúncios", "Página da empresa"],
    },
    {
        "id": "clarity",
        "name": "Microsoft Clarity",
        "category": "analytics",
        "availability": "available",
        "resources": ["Comportamento no site", "Cliques de raiva", "Rolagem"],
    },
)


def public_integration_catalog() -> List[Dict[str, Any]]:
    # TikTok e Pinterest só aparecem como disponíveis quando o app da plataforma está configurado no servidor.
    from .channel_providers import configured
    out = []
    for provider in INTEGRATION_PROVIDERS:
        item = dict(provider)
        if item["id"] == "tiktok" and not (configured("tiktok_ads") or configured("tiktok")):
            item["availability"] = "configuration_unavailable"
        if item["id"] == "linkedin" and not configured("linkedin"):
            item["availability"] = "configuration_unavailable"
        if item["id"] == "pinterest" and not configured("pinterest"):
            item["availability"] = "configuration_unavailable"
        out.append(item)
    return out
