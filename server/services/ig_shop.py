"""Produtos da loja do Instagram (Instagram Shopping) marcados nos posts do Calendário.

Fluxo (Instagram API com login do Facebook):
1. ``GET /{ig-user-id}?fields=shopping_product_tag_eligibility`` — a conta tem loja aprovada para marcar produtos?
2. ``GET /{ig-user-id}/available_catalogs`` — catálogo(s) da loja.
3. ``GET /{ig-user-id}/catalog_product_search?catalog_id=…&q=…`` — produtos que podem ser marcados (nome ou SKU).
4. Na publicação, ``product_tags`` vai no contêiner: imagem com x/y; Reels e vídeo só o produto; carrossel por slide.

Precisa das permissões ``instagram_shopping_tag_products`` e ``catalog_management`` na conexão do Instagram, conta
Comercial (não Criador) e loja aprovada no Commerce Manager. Stories não aceitam marcação. Só produto com revisão
aprovada aparece no post (a Meta não devolve erro: a marcação fica escondida).
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

import httpx

from .meta_config import META_GRAPH_BASE_URL
from .studio_calendar import StudioError

TAG_SCOPE = "instagram_shopping_tag_products"
CATALOG_SCOPE = "catalog_management"
MAX_TAGS = 30          # Reels aceita 30; imagem e carrossel, 20
MAX_FEED_TAGS = 20
MAX_PER_SLIDE = 5
NO_TAG_FORMATS = {"stories", "story"}


# ------------------------------------------------------------------ limpeza do que vem da tela

def _coord(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.5
    if math.isnan(number):
        return 0.5
    return round(min(1.0, max(0.01, number)), 3)


def clean_product_tags(value: Any) -> List[Dict[str, Any]]:
    """Marcações válidas: produto numérico, slide 0–9, x/y entre 0.01 e 1; sem repetir produto no mesmo slide,
    no máximo 5 por slide e 30 no post."""
    out: List[Dict[str, Any]] = []
    per_slide: Dict[int, int] = {}
    for raw in (value or [])[:60]:
        if not isinstance(raw, dict):
            continue
        product_id = str(raw.get("product_id") or "").strip()
        if not product_id.isdigit() or len(product_id) > 30:
            continue
        try:
            slide = max(0, min(9, int(raw.get("slide") or 0)))
        except (TypeError, ValueError):
            slide = 0
        if any(t["product_id"] == product_id and t["slide"] == slide for t in out) or per_slide.get(slide, 0) >= MAX_PER_SLIDE:
            continue
        image = str(raw.get("image_url") or "").strip()
        out.append({"product_id": product_id, "name": str(raw.get("name") or "").strip()[:120] or None,
                    "image_url": image[:1000] if image.startswith("https://") else None,
                    "slide": slide, "x": _coord(raw.get("x")), "y": _coord(raw.get("y"))})
        per_slide[slide] = per_slide.get(slide, 0) + 1
        if len(out) >= MAX_TAGS:
            break
    return out


# ------------------------------------------------------------------ marcação no contêiner de publicação

def tags_for_container(tags: List[Dict[str, Any]], *, image: bool, slide: Optional[int] = None,
                       limit: int = MAX_FEED_TAGS) -> List[Dict[str, Any]]:
    """Formato da Meta: imagem leva x/y; vídeo e Reels só o produto. ``slide`` filtra o slide do carrossel."""
    chosen = [t for t in tags if slide is None or int(t.get("slide") or 0) == slide]
    seen: set = set()
    out: List[Dict[str, Any]] = []
    for tag in chosen:
        if tag["product_id"] in seen:
            continue
        seen.add(tag["product_id"])
        out.append({"product_id": tag["product_id"], "x": tag["x"], "y": tag["y"]} if image else {"product_id": tag["product_id"]})
    return out[:limit]


def has_tags(plan: Dict[str, Any]) -> bool:
    return "product_tags" in plan["fields"] or any("product_tags" in child for child in plan.get("children") or [])


def strip_tags(plan: Dict[str, Any]) -> Dict[str, Any]:
    """Mesmo plano sem marcação de produto (publica mesmo se a Meta recusar as marcações)."""
    return {**plan, "fields": {k: v for k, v in plan["fields"].items() if k != "product_tags"},
            "children": [{k: v for k, v in child.items() if k != "product_tags"} for child in plan.get("children") or []]}


# ------------------------------------------------------------------ loja e catálogo

def _friendly(error: Dict[str, Any], status: int) -> StudioError:
    code = error.get("code")
    message = str(error.get("message") or f"HTTP {status}")
    if code in (10, 200) or "permission" in message.lower():
        return StudioError("SHOP_PERMISSION", "A conexão do Instagram desta marca ainda não tem a permissão de marcar produtos. "
                                               "Reconecte o Instagram em Integrações depois que a Meta liberar a permissão no app.")
    if code == 100 and "catalog" in message.lower():
        return StudioError("SHOP_CATALOG", "Catálogo da loja não encontrado para esta conta do Instagram.")
    return StudioError("SHOP_FAILED", message[:280])


async def _get(path: str, *, token: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(f"{META_GRAPH_BASE_URL}{path}", params={**(params or {}), "access_token": token})
    if response.status_code >= 400:
        try:
            error = (response.json() or {}).get("error") or {}
        except ValueError:
            error = {}
        raise _friendly(error, response.status_code)
    return response.json() if response.content else {}


async def shop_status(client_id: str) -> Dict[str, Any]:
    """Se a marca pode marcar produtos e quais catálogos tem. Nunca levanta por causa da Meta: devolve a explicação."""
    from .ig_engagement import credentials
    try:
        creds = await credentials(client_id)
    except StudioError:
        return {"ready": False, "eligible": False, "catalogs": [], "missing_scopes": [],
                "message": "Conecte o Instagram da marca (login do Facebook) em Integrações para marcar produtos."}
    missing = [s for s in (TAG_SCOPE, CATALOG_SCOPE) if creds["scopes"] and s not in creds["scopes"]]
    out: Dict[str, Any] = {"ready": False, "eligible": None, "catalogs": [], "missing_scopes": missing, "message": None}
    try:
        info = await _get(f"/{creds['ig_user_id']}", token=creds["token"], params={"fields": "shopping_product_tag_eligibility"})
        out["eligible"] = bool(info.get("shopping_product_tag_eligibility"))
        if out["eligible"]:
            data = await _get(f"/{creds['ig_user_id']}/available_catalogs", token=creds["token"],
                              params={"fields": "catalog_id,catalog_name,shop_name,product_count"})
            out["catalogs"] = [{"id": str(c.get("catalog_id") or ""), "name": c.get("catalog_name"), "shop_name": c.get("shop_name"),
                                "product_count": c.get("product_count")} for c in data.get("data") or [] if c.get("catalog_id")]
    except StudioError as exc:
        out["message"] = str(exc) if str(exc) != exc.code else "Não foi possível consultar a loja agora."
        return out
    if not out["eligible"]:
        out["message"] = ("Esta conta do Instagram não está liberada para marcar produtos: precisa ser conta Comercial com a "
                          "loja aprovada no Commerce Manager da Meta (Instagram Shopping).")
    elif not out["catalogs"]:
        out["message"] = "A loja não tem catálogo disponível para marcar produtos."
    else:
        out["ready"] = True
    return out


async def search_products(client_id: str, query: str, catalog_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Produtos da loja que podem ser marcados (nome ou SKU), com foto. Sem catálogo informado, usa o primeiro."""
    from .ig_engagement import credentials
    creds = await credentials(client_id)
    if not catalog_id:
        data = await _get(f"/{creds['ig_user_id']}/available_catalogs", token=creds["token"], params={"fields": "catalog_id"})
        catalog_id = next((str(c["catalog_id"]) for c in data.get("data") or [] if c.get("catalog_id")), None)
        if not catalog_id:
            raise StudioError("SHOP_CATALOG", "A loja não tem catálogo disponível para marcar produtos.")
    params: Dict[str, Any] = {"catalog_id": catalog_id}
    if (query or "").strip():
        params["q"] = query.strip()[:100]
    data = await _get(f"/{creds['ig_user_id']}/catalog_product_search", token=creds["token"], params=params)
    out: List[Dict[str, Any]] = []
    for row in (data.get("data") or [])[:50]:
        product_id = str(row.get("product_id") or "")
        if not product_id:
            continue
        out.append({"product_id": product_id, "name": str(row.get("product_name") or "")[:120], "image_url": row.get("image_url"),
                    "sku": row.get("retailer_id"), "review_status": row.get("review_status") or None,
                    "variants": [{"product_id": str(v.get("product_id")), "name": v.get("variant_name")}
                                 for v in row.get("product_variants") or [] if v.get("product_id")][:20]})
    return out
