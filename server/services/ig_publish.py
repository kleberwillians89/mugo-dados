"""Publicação no Instagram (Content Publishing API) dos posts aprovados com agendamento validado.

Fluxo: pauta aprovada pelo cliente → equipe clica "Agendar para dd/mm hh:mm" → no horário, o job
``ig-publish-due`` cria o contêiner (POST /{ig-user-id}/media) e publica (POST /{ig-user-id}/media_publish).

- Arte precisa ser um link público de arquivo: JPEG (imagem) ou MP4/MOV (Reels). Link de arquivo do Google
  Drive é convertido para download direto (o arquivo precisa estar "qualquer pessoa com o link"). Link do Canva
  não é arquivo: a pauta fica como "manual" com a orientação de exportar a arte.
- Carrossel: um link por linha (2 a 10), cada um vira um item; Stories: uma imagem ou vídeo (sem legenda).
  Arte enviada pelo modal já fica no Storage público em JPG/MP4.
- Sem ``IG_PUBLISH_ENABLED=true`` registra "simulado" e não chama a Meta (mesma lógica das outras automações).
- Cada pauta é travada antes de publicar (publish_status de vazio para "publicando"): nunca publica duas vezes.
"""
from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import httpx

from .ig_supabase import sb_select, sb_update
from .meta_config import META_GRAPH_BASE_URL
from .studio_calendar import ITEMS_TABLE, StudioError

PUBLISH_SCOPE = "instagram_content_publish"
MAX_PER_RUN = 20
VIDEO_FORMATS = {"reels", "video"}
CAROUSEL_FORMATS = {"carrossel", "carousel"}
STORY_FORMATS = {"stories", "story"}
VIDEO_EXT = (".mp4", ".mov")
_DRIVE = re.compile(r"^https://drive\.google\.com/(?:file/d/([\w-]{10,})|open\?id=([\w-]{10,})|uc\?(?:.*&)?id=([\w-]{10,}))")


def publish_enabled() -> bool:
    return (os.getenv("IG_PUBLISH_ENABLED") or "").strip().lower() == "true"


def _asset(url: str) -> Tuple[Optional[Dict[str, str]], Optional[str]]:
    """Um link → {"kind": image|video, "url": link direto}, ou o motivo para ficar manual."""
    url = url.strip()
    drive = _DRIVE.match(url)
    if drive:
        return {"kind": "drive", "url": f"https://drive.google.com/uc?export=download&id={next(g for g in drive.groups() if g)}"}, None
    if "canva.com" in url:
        return None, "Link do Canva não é arquivo: envie a arte pelo modal (JPG/MP4) ou cole o link do Drive."
    path = url.split("?", 1)[0].lower()
    if path.endswith(VIDEO_EXT):
        return {"kind": "video", "url": url}, None
    if path.endswith((".jpg", ".jpeg")):
        return {"kind": "image", "url": url}, None
    return None, "Arte precisa ser JPG (imagem) ou MP4/MOV (vídeo): envie pelo modal ou cole o link do Drive."


def _media_fields(asset: Dict[str, str], fmt_is_video: bool) -> Dict[str, str]:
    video = asset["kind"] == "video" or (asset["kind"] == "drive" and fmt_is_video)
    return {"video_url": asset["url"]} if video else {"image_url": asset["url"]}


def media_for(item: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Plano de publicação ({"type", "fields", "children"}) ou o motivo para ficar manual."""
    fmt = str(item.get("format") or "").lower()
    links = [l for l in re.split(r"\s+", str(item.get("art_url") or "")) if l.strip()]
    if not links:
        return None, "Sem arte na pauta."
    assets = []
    for link in links:
        asset, problem = _asset(link)
        if problem:
            return None, problem
        assets.append(asset)
    caption = str(item.get("caption_draft") or "").strip()[:2200]
    if fmt in CAROUSEL_FORMATS:
        if not 2 <= len(assets) <= 10:
            return None, "Carrossel precisa de 2 a 10 artes (um link por linha, na ordem dos slides)."
        children = [{**_media_fields(a, False), **({"media_type": "VIDEO"} if "video_url" in _media_fields(a, False) else {}),
                     "is_carousel_item": "true"} for a in assets]
        return {"type": "carousel", "fields": {"media_type": "CAROUSEL", "caption": caption}, "children": children}, None
    if fmt in STORY_FORMATS:
        return {"type": "story", "fields": {"media_type": "STORIES", **_media_fields(assets[0], False)}, "children": []}, None
    if fmt in VIDEO_FORMATS:
        if assets[0]["kind"] == "image":
            return None, "Reels precisa de vídeo MP4/MOV (envie pelo modal ou cole o link do Drive)."
        return {"type": "reels", "fields": {"media_type": "REELS", "video_url": assets[0]["url"], "caption": caption}, "children": []}, None
    if assets[0]["kind"] == "video":
        return None, "Post de imagem com vídeo: mude o formato para Reels."
    return {"type": "image", "fields": {"image_url": assets[0]["url"], "caption": caption}, "children": []}, None


async def _graph(method: str, path: str, *, token: str, data: Optional[Dict[str, Any]] = None,
                 params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.request(method, f"{META_GRAPH_BASE_URL}{path}", params={**(params or {}), "access_token": token}, data=data)
    if response.status_code >= 400:
        try:
            error = (response.json() or {}).get("error") or {}
        except ValueError:
            error = {}
        raise StudioError("IG_PUBLISH_FAILED", str(error.get("message") or f"HTTP {response.status_code}")[:280])
    return response.json() if response.content else {}


async def _wait_ready(creds: Dict[str, Any], creation_id: str, *, wait_seconds: float, max_checks: int) -> None:
    for _ in range(max_checks):
        status = (await _graph("GET", f"/{creation_id}", token=creds["token"], params={"fields": "status_code"})).get("status_code")
        if status in (None, "FINISHED"):
            return
        if status == "ERROR":
            raise StudioError("IG_PUBLISH_FAILED", "A Meta não conseguiu processar a mídia (confira o arquivo e o formato).")
        await asyncio.sleep(wait_seconds)
    raise StudioError("IG_PUBLISH_FAILED", "A mídia ainda está processando na Meta; tente de novo em alguns minutos.")


async def _container(creds: Dict[str, Any], fields: Dict[str, str]) -> str:
    created = await _graph("POST", f"/{creds['ig_user_id']}/media", token=creds["token"], data=fields)
    creation_id = str(created.get("id") or "")
    if not creation_id:
        raise StudioError("IG_PUBLISH_FAILED", "A Meta não devolveu o contêiner da mídia.")
    return creation_id


async def publish(creds: Dict[str, Any], plan: Dict[str, Any], *, wait_seconds: float = 5, max_checks: int = 24) -> Dict[str, Any]:
    fields = dict(plan["fields"])
    if plan["type"] == "carousel":
        child_ids = []
        for child in plan["children"]:  # cada slide vira um contêiner; vídeo precisa terminar de processar
            child_id = await _container(creds, child)
            if child.get("media_type") == "VIDEO":
                await _wait_ready(creds, child_id, wait_seconds=wait_seconds, max_checks=max_checks)
            child_ids.append(child_id)
        fields["children"] = ",".join(child_ids)
    creation_id = await _container(creds, fields)
    if plan["type"] in ("reels", "carousel") or "video_url" in fields:
        await _wait_ready(creds, creation_id, wait_seconds=wait_seconds, max_checks=max_checks)
    out = await _graph("POST", f"/{creds['ig_user_id']}/media_publish", token=creds["token"], data={"creation_id": creation_id})
    media_id = str(out.get("id") or "")
    permalink = None
    try:
        permalink = (await _graph("GET", f"/{media_id}", token=creds["token"], params={"fields": "permalink"})).get("permalink")
    except StudioError:
        pass
    return {"media_id": media_id, "permalink": permalink}


async def _set(item: Dict[str, Any], patch: Dict[str, Any], *, expect: Optional[str] = None) -> bool:
    filters = {"id": f"eq.{item['id']}", "client_id": f"eq.{item['client_id']}"}
    filters["publish_status"] = f"eq.{expect}" if expect else "is.null"
    return bool(await sb_update(ITEMS_TABLE, filters=filters, patch=patch))


async def publish_item(item: Dict[str, Any], *, creds_cache: Dict[str, Any]) -> str:
    container, manual = media_for(item)
    if manual:
        await _set(item, {"publish_status": "manual", "publish_error": manual[:300]})
        return "manual"
    if not await _set(item, {"publish_status": "publicando", "publish_error": None}):
        return "ocupado"  # outra execução travou esta pauta
    try:
        if not publish_enabled():
            await _set(item, {"publish_status": "simulado"}, expect="publicando")
            return "simulado"
        client_id = item["client_id"]
        if client_id not in creds_cache:
            from .ig_engagement import credentials
            creds_cache[client_id] = await credentials(client_id)
        creds = creds_cache[client_id]
        if creds["scopes"] and PUBLISH_SCOPE not in creds["scopes"]:
            raise StudioError("IG_PUBLISH_FAILED", "A conexão do Instagram desta marca não tem a permissão de publicar. Reconecte em Integrações.")
        out = await publish(creds, container)
        await _set(item, {"publish_status": "publicado", "status": "publicado", "published_at": datetime.now(timezone.utc).isoformat(),
                          "published_media_id": out["media_id"], "published_permalink": out.get("permalink")}, expect="publicando")
        return "publicado"
    except StudioError as exc:
        await _set(item, {"publish_status": "falhou", "publish_error": (str(exc) if str(exc) != exc.code else exc.code)[:300]}, expect="publicando")
        return "falhou"


async def publish_due(*, now: Optional[datetime] = None) -> Dict[str, int]:
    now = now or datetime.now(timezone.utc)
    items = await sb_select(ITEMS_TABLE, select="id,client_id,format,art_url,caption_draft,scheduled_at,status,schedule_confirmed_at,publish_status",
                            order="scheduled_at.asc", limit=MAX_PER_RUN,
                            filters={"status": "eq.aprovado", "schedule_confirmed_at": "not.is.null", "publish_status": "is.null",
                                     "scheduled_at": f"lte.{now.isoformat()}"})
    counts: Dict[str, int] = {"due": len(items)}
    cache: Dict[str, Any] = {}
    for item in items:
        try:
            result = await publish_item(item, creds_cache=cache)
        except StudioError as exc:  # sem Instagram conectado etc.: uma marca não para as outras
            await _set(item, {"publish_status": "falhou", "publish_error": exc.code}, expect="publicando")
            result = "falhou"
        counts[result] = counts.get(result, 0) + 1
        phrase = {"publicado": "publicou no Instagram", "falhou": "não conseguiu publicar", "manual": "deixou para publicar à mão",
                  "simulado": "simulou a publicação (publicação automática desligada)"}.get(result)
        if phrase:
            from .studio_history import record
            await record(item["client_id"], item["id"], phrase, actor_name="Publicação automática", side="sistema")
    return counts


async def retry(client_id: str, item_id: str) -> Dict[str, Any]:
    """Equipe corrigiu o link da arte: libera a pauta para o próximo ciclo."""
    rows = await sb_update(ITEMS_TABLE, filters={"id": f"eq.{item_id}", "client_id": f"eq.{client_id}", "publish_status": "in.(falhou,manual)"},
                           patch={"publish_status": None, "publish_error": None})
    if not rows:
        raise StudioError("ITEM_NOT_FOUND")
    return rows[0]
