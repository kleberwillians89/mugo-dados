"""Publicação no Instagram (Content Publishing API) dos posts aprovados com agendamento validado.

Fluxo: pauta aprovada pelo cliente → equipe clica "Agendar para dd/mm hh:mm" → no horário, o job
``ig-publish-due`` cria o contêiner (POST /{ig-user-id}/media) e publica (POST /{ig-user-id}/media_publish).

- Arte precisa ser um link público de arquivo: JPEG (imagem) ou MP4/MOV (Reels). Link de arquivo do Google
  Drive é convertido para download direto (o arquivo precisa estar "qualquer pessoa com o link"). Link do Canva
  não é arquivo: a pauta fica como "manual" com a orientação de exportar a arte.
- Carrossel e Stories ficam manuais nesta versão (precisam de várias mídias / outro fluxo da Meta).
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
MANUAL_FORMATS = {"carrossel", "stories", "story"}
_DRIVE = re.compile(r"^https://drive\.google\.com/(?:file/d/([\w-]{10,})|open\?id=([\w-]{10,})|uc\?(?:.*&)?id=([\w-]{10,}))")


def publish_enabled() -> bool:
    return (os.getenv("IG_PUBLISH_ENABLED") or "").strip().lower() == "true"


def media_for(item: Dict[str, Any]) -> Tuple[Optional[Dict[str, str]], Optional[str]]:
    """(parâmetros do contêiner, motivo para ficar manual)."""
    fmt = str(item.get("format") or "").lower()
    if fmt in MANUAL_FORMATS:
        return None, f"Formato {fmt} é publicado manualmente nesta versão."
    url = str(item.get("art_url") or "").strip()
    if not url:
        return None, "Sem link da arte na pauta."
    drive = _DRIVE.match(url)
    if drive:
        url = f"https://drive.google.com/uc?export=download&id={next(g for g in drive.groups() if g)}"
    elif "canva.com" in url:
        return None, "Link do Canva não é arquivo: exporte em JPG/MP4 e cole o link do Drive ou do arquivo."
    else:
        path = url.split("?", 1)[0].lower()
        if fmt in VIDEO_FORMATS and not path.endswith((".mp4", ".mov")):
            return None, "Reels precisa de link direto de vídeo MP4/MOV (ou arquivo no Drive)."
        if fmt not in VIDEO_FORMATS and not path.endswith((".jpg", ".jpeg")):
            return None, "Imagem precisa de link direto JPG (a Meta só aceita JPEG) ou arquivo no Drive."
    caption = str(item.get("caption_draft") or "").strip()[:2200]
    if fmt in VIDEO_FORMATS:
        return {"media_type": "REELS", "video_url": url, "caption": caption}, None
    return {"image_url": url, "caption": caption}, None


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


async def publish(creds: Dict[str, Any], container: Dict[str, str], *, wait_seconds: float = 5, max_checks: int = 24) -> Dict[str, Any]:
    ig = creds["ig_user_id"]
    created = await _graph("POST", f"/{ig}/media", token=creds["token"], data=container)
    creation_id = str(created.get("id") or "")
    if not creation_id:
        raise StudioError("IG_PUBLISH_FAILED", "A Meta não devolveu o contêiner da mídia.")
    if container.get("media_type") == "REELS":  # vídeo processa antes de publicar
        for _ in range(max_checks):
            status = (await _graph("GET", f"/{creation_id}", token=creds["token"], params={"fields": "status_code"})).get("status_code")
            if status == "FINISHED":
                break
            if status == "ERROR":
                raise StudioError("IG_PUBLISH_FAILED", "A Meta não conseguiu processar o vídeo (confira o link e o formato).")
            await asyncio.sleep(wait_seconds)
        else:
            raise StudioError("IG_PUBLISH_FAILED", "O vídeo ainda está processando na Meta; tente de novo em alguns minutos.")
    out = await _graph("POST", f"/{ig}/media_publish", token=creds["token"], data={"creation_id": creation_id})
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
    return counts


async def retry(client_id: str, item_id: str) -> Dict[str, Any]:
    """Equipe corrigiu o link da arte: libera a pauta para o próximo ciclo."""
    rows = await sb_update(ITEMS_TABLE, filters={"id": f"eq.{item_id}", "client_id": f"eq.{client_id}", "publish_status": "in.(falhou,manual)"},
                           patch={"publish_status": None, "publish_error": None})
    if not rows:
        raise StudioError("ITEM_NOT_FOUND")
    return rows[0]
