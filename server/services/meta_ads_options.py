"""Opções do criador de campanha puxadas da própria conta Meta do cliente (nada escrito à mão).

- identidade: Página do Facebook e conta do Instagram ligadas à empresa;
- pixels (conjuntos de dados) e quais eventos chegaram nos últimos dias;
- apps da conta (Promoção do app) e formulários instantâneos da Página (Cadastros);
- números de WhatsApp e moeda da conta;
- interesses: busca na lista oficial da Meta;
- prévia oficial do anúncio (generatepreviews), por posicionamento.

Tudo aqui é leitura. A única escrita é o envio da imagem para a biblioteca da conta (adimages),
o mesmo que a criação faz, porque a prévia oficial precisa do hash da imagem.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, List, Optional

from . import meta_ad_publisher as pub
from . import meta_structure as ms
from .ig_supabase import sb_update
from .studio_calendar import StudioError

# Prévias que o Gerenciador mostra, na mesma ordem (ad_format da API → nome na tela).
PREVIEW_FORMATS: Dict[str, str] = {
    "INSTAGRAM_STANDARD": "Feed do Instagram",
    "INSTAGRAM_STORY": "Stories do Instagram",
    "INSTAGRAM_REELS": "Reels do Instagram",
    "INSTAGRAM_EXPLORE_GRID_HOME": "Explorar do Instagram",
    "MOBILE_FEED_STANDARD": "Feed do Facebook (celular)",
    "DESKTOP_FEED_STANDARD": "Feed do Facebook (computador)",
    "FACEBOOK_STORY_MOBILE": "Stories do Facebook",
    "FACEBOOK_REELS_MOBILE": "Reels do Facebook",
    "MARKETPLACE_MOBILE": "Marketplace",
}


async def _safe(coro, default):
    try:
        return await coro
    except StudioError as exc:
        print(f"[meta_ads_options] optional_read_failed code={exc.code}")
        return default


async def _events_seen(pixel_id: str, token: str) -> List[str]:
    """Eventos padrão que o pixel recebeu nos últimos 7 dias (para marcar como no Gerenciador)."""
    since = int(time.time()) - 7 * 86400
    body = await pub._graph("GET", f"/{pixel_id}/stats", token=token, params={"aggregation": "event", "start_time": since})
    names = set()
    for bucket in body.get("data") or []:
        for item in bucket.get("data") or []:
            if int(item.get("count") or 0) > 0:
                names.add(str(item.get("value") or ""))
    return [key for key, name in ms.EVENT_PIXEL_NAMES.items() if name in names]


async def _apps(act: str, token: str) -> List[Dict[str, Any]]:
    body = await pub._graph("GET", f"/{act}/advertisable_applications", token=token,
                            params={"fields": "id,name,object_store_urls,icon_url", "limit": 25})
    out = []
    for app in body.get("data") or []:
        urls = app.get("object_store_urls") or {}
        stores = [{"store": k, "url": str(v)} for k, v in urls.items() if isinstance(v, str) and v.startswith("http")]
        out.append({"id": str(app.get("id")), "name": pub._text(app.get("name"), 120), "icon_url": app.get("icon_url") or "",
                    "stores": stores})
    return out


async def _lead_forms(page_id: str, token: str) -> List[Dict[str, Any]]:
    body = await pub._graph("GET", f"/{page_id}/leadgen_forms", token=token,
                            params={"fields": "id,name,status,locale", "limit": 50})
    return [{"id": str(f.get("id")), "name": pub._text(f.get("name"), 120), "status": str(f.get("status") or "")}
            for f in body.get("data") or [] if str(f.get("status") or "ACTIVE").upper() == "ACTIVE"]


async def _identity(page_id: str, ig_id: str, token: str) -> Dict[str, Any]:
    page = await _safe(pub._graph("GET", f"/{page_id}", token=token, params={"fields": "id,name,picture{url}"}), {})
    ig = await _safe(pub._graph("GET", f"/{ig_id}", token=token, params={"fields": "id,username,profile_picture_url"}), {}) if ig_id else {}
    return {"page": {"id": page_id, "name": pub._text(page.get("name"), 120),
                     "picture": ((page.get("picture") or {}).get("data") or {}).get("url") or ""},
            "instagram": {"id": ig_id, "username": pub._text(ig.get("username"), 60),
                          "picture": ig.get("profile_picture_url") or ""} if ig_id else None}


async def account_options(client_id: str) -> Dict[str, Any]:
    """Opções desta conta para os três níveis. O que a conta não tem volta vazio, e a tela não mostra."""
    ctx = await pub._context(client_id)
    token, act = ctx["token"], ctx["act"]
    account, pixels, apps, forms, identity, numbers = await asyncio.gather(
        _safe(pub._graph("GET", f"/{act}", token=token, params={"fields": "id,name,currency,timezone_name,account_status"}), {}),
        _safe(pub._pixels(act, token), []),
        _safe(_apps(act, token), []),
        _safe(_lead_forms(ctx["page_id"], token), []),
        _identity(ctx["page_id"], ctx["ig_id"], token),
        _safe(pub.ad_whatsapp_numbers(client_id), []),
    )
    usable = [p for p in pixels if not p.get("is_unavailable")]
    seen = await asyncio.gather(*[_safe(_events_seen(str(p["id"]), token), []) for p in usable[:5]])
    best = pub.best_pixel(pixels)
    return {
        "catalog": ms.catalog(),
        "account": {"id": act, "name": pub._text(account.get("name"), 120), "currency": account.get("currency") or "BRL",
                    "timezone": account.get("timezone_name") or ""},
        "identity": identity,
        "pixels": [{"id": str(p["id"]), "name": pub._text(p.get("name"), 120) or str(p["id"]),
                    "active": bool(p.get("last_fired_time")), "events_seen": events}
                   for p, events in zip(usable[:5], seen)],
        "recommended_pixel": str(best["id"]) if best else None,
        "apps": apps,
        "lead_forms": forms,
        "whatsapp_numbers": numbers,
        "preview_formats": [{"key": k, "label": v} for k, v in PREVIEW_FORMATS.items()],
    }


async def search_interests(client_id: str, query: str) -> List[Dict[str, Any]]:
    """Interesses da lista oficial da Meta (o mesmo campo "Segmentação detalhada" do Gerenciador)."""
    query = query.strip()[:80]
    if len(query) < 2:
        return []
    account = await pub._ad_account(client_id)
    body = await pub._graph("GET", "/search", token=account["token"],
                            params={"type": "adinterest", "q": query, "limit": 12, "locale": "pt_BR"})
    out = []
    for item in body.get("data") or []:
        if not item.get("id"):
            continue
        path = item.get("path") or []
        out.append({"id": str(item["id"]), "name": pub._text(item.get("name"), 120),
                    "path": " > ".join(str(x) for x in path[:-1])[:200] if isinstance(path, list) else "",
                    "size": pub.size_label(item.get("audience_size_lower_bound"), item.get("audience_size_upper_bound"))})
    return out


async def official_preview(client_id: str, draft_id: str, ad_format: str, ad_index: int = 0) -> Dict[str, Any]:
    """Prévia oficial da Meta (a mesma do Gerenciador) para o anúncio do rascunho, sem criar nada na campanha."""
    if ad_format not in PREVIEW_FORMATS:
        raise StudioError("AD_PREVIEW_FORMAT_INVALID")
    row = await pub._draft(client_id, draft_id)
    payload = pub.clean_payload(row.get("payload") or {})
    meta, ad = payload["meta"], payload["ad"]
    ctx = await pub._context(client_id)
    token, act = ctx["token"], ctx["act"]
    units = pub.ad_units(ad)
    if not 0 <= ad_index < len(units):
        raise StudioError("AD_PREVIEW_UNAVAILABLE", "Esse anúncio não existe mais no rascunho.")
    unit = units[ad_index]
    location = meta["conversion_location"]
    link = (pub.WHATSAPP_LINK if location == "MESSAGING" and meta["messaging_apps"] == ["WHATSAPP"]
            else (meta["app"] or {}).get("store_url") if location == "APP"
            else "https://fb.me/" if location == "ON_AD"
            else f"https://www.facebook.com/{ctx['page_id']}" if location in ("MESSAGING", "PHONE_CALL", "ON_PAGE", "INSTAGRAM_PROFILE")
            else ad["link"] or f"https://www.facebook.com/{ctx['page_id']}")
    button = pub.cta_for(meta, ad, link, page_id=ctx["page_id"])
    if ad_index == 0 and meta.get("use_existing_post") and ad.get("instagram_post_id"):
        creative: Dict[str, Any] = {"object_id": ctx["page_id"], "source_instagram_media_id": ad["instagram_post_id"]}
        if ctx["ig_id"]:
            creative["instagram_user_id"] = ctx["ig_id"]
    else:
        if unit["format"] == "carousel":
            if len(unit["cards"]) < 2:
                raise StudioError("AD_PREVIEW_UNAVAILABLE", "Escolha pelo menos 2 imagens para ver a prévia do carrossel.")
            children = []
            for card in unit["cards"]:
                child = {"link": card["link"] or link, "image_hash": await pub._image_hash(act, card["image_url"], token),
                         "name": card["headline"] or ad["headline"], "call_to_action": button}
                if card["description"]:
                    child["description"] = card["description"]
                children.append(child)
            story = {"link_data": {"link": link, "message": ad["primary_text"], "child_attachments": children,
                                   "multi_share_optimized": False, "multi_share_end_card": False, "call_to_action": button}}
        elif unit["media_type"] == "video":
            video_id = await _preview_video(client_id, draft_id, row, act, token, unit, payload["name"])
            cover = unit.get("image_url") or await pub._video_thumbnail(video_id, token, tries=1)
            if not cover:
                raise StudioError("AD_PREVIEW_PROCESSING", "A Meta ainda está gerando a capa do vídeo. Clique em Atualizar prévia em alguns segundos.")
            video: Dict[str, Any] = {"video_id": video_id, "message": ad["primary_text"],
                                     "title": unit.get("headline") or ad["headline"] or payload["name"], "call_to_action": button}
            if unit.get("image_url"):
                video["image_hash"] = await pub._image_hash(act, unit["image_url"], token)
            else:
                video["image_url"] = cover
            story = {"video_data": video}
        else:
            if not unit["image_url"]:
                raise StudioError("AD_PREVIEW_UNAVAILABLE", "Escolha a imagem do anúncio para ver a prévia.")
            data: Dict[str, Any] = {"link": link, "message": ad["primary_text"],
                                    "image_hash": await pub._image_hash(act, unit["image_url"], token), "call_to_action": button}
            if unit.get("headline") or ad["headline"]:
                data["name"] = unit.get("headline") or ad["headline"]
            if ad["description"]:
                data["description"] = ad["description"]
            story = {"link_data": data}
        spec = pub.without_empty_cta({"page_id": ctx["page_id"], **story})
        if ctx["ig_id"]:
            spec["instagram_user_id"] = ctx["ig_id"]
        creative = {"object_story_spec": spec}
    body = await pub._graph("GET", f"/{act}/generatepreviews", token=token,
                            params={"creative": json.dumps(creative), "ad_format": ad_format})
    first = (body.get("data") or [{}])[0]
    src = preview_src(str(first.get("body") or ""))
    if not src:
        raise StudioError("AD_PREVIEW_UNAVAILABLE", "A Meta não devolveu a prévia para este posicionamento.")
    return {"format": ad_format, "label": PREVIEW_FORMATS[ad_format], "src": src}


def preview_src(html: str) -> Optional[str]:
    """Extrai só o endereço do iframe da Meta (a tela monta o próprio iframe, sem HTML de fora)."""
    import re
    match = re.search(r'src="(https://[^"]+)"', html)
    if not match:
        return None
    src = match.group(1).replace("&amp;", "&")
    return src if re.match(r"https://(www\.|business\.)?facebook\.com/", src) else None


async def _preview_video(client_id: str, draft_id: str, row: Dict[str, Any], act: str, token: str,
                         unit: Dict[str, Any], name: str) -> str:
    """Envia o vídeo uma vez para a conta (como na criação) e guarda o id no rascunho: a criação pausada reaproveita,
    sem enviar de novo. Enquanto a Meta processa, avisa para tentar em alguns segundos."""
    ids = dict(row.get("meta_ids") or {})
    cache = dict(ids.get("preview_videos") or {})
    key = pub.unit_key(unit)
    video_id = cache.get(key)
    if not video_id:
        video_id = await pub._upload_video(act, unit, token, f"{name} · vídeo")
        cache[key] = video_id
        ids["preview_videos"] = cache
        await sb_update(pub.TABLE, filters={"client_id": f"eq.{client_id}", "id": f"eq.{draft_id}"},
                        patch={"meta_ids": ids}, returning="minimal")
    status = await pub._graph("GET", f"/{video_id}", token=token, params={"fields": "status"})
    state = str(((status.get("status") or {}).get("video_status")) or "ready").lower()
    if state == "error":
        raise StudioError("AD_PREVIEW_UNAVAILABLE", "A Meta não conseguiu processar este vídeo. Escolha outro arquivo.")
    if state != "ready":
        raise StudioError("AD_PREVIEW_PROCESSING", "Vídeo enviado. A Meta está processando: clique em Atualizar prévia em alguns segundos.")
    return str(video_id)
