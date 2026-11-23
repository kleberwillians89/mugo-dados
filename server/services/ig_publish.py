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
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

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
CONVERT_EXT = (".png", ".webp", ".gif", ".heic", ".heif")
JPEG_MAX_BYTES = 30 * 1024 * 1024
_DRIVE = re.compile(r"^https://drive\.google\.com/(?:file/d/([\w-]{10,})|open\?id=([\w-]{10,})|uc\?(?:.*&)?id=([\w-]{10,}))")


def publish_enabled() -> bool:
    return (os.getenv("IG_PUBLISH_ENABLED") or "").strip().lower() == "true"


def _asset(url: str) -> Tuple[Optional[Dict[str, str]], Optional[str]]:
    """Um link → {"kind": image|video, "url": link direto}, ou o motivo para ficar manual."""
    url = url.strip()
    drive = _DRIVE.match(url)
    if drive:
        return {"kind": "drive", "url": f"https://drive.google.com/uc?export=download&id={next(g for g in drive.groups() if g)}"}, None
    if "canva.com" in url or "canva.link" in url:
        return None, "Link do Canva não é arquivo: na pauta, clique em Trazer arte (ou envie o JPG/MP4)."
    path = url.split("?", 1)[0].lower()
    if path.endswith(VIDEO_EXT):
        return {"kind": "video", "url": url}, None
    if path.endswith((".jpg", ".jpeg")):
        return {"kind": "image", "url": url}, None
    if path.endswith(CONVERT_EXT):
        # O Instagram só aceita JPG: PNG/WebP/HEIC viram JPG na hora de publicar (ensure_jpeg).
        return {"kind": "image", "url": url, "convert": "1"}, None
    return None, "Arte precisa ser imagem (JPG, PNG, WebP) ou vídeo (MP4/MOV): envie pelo modal ou cole o link do Drive."


def _media_fields(asset: Dict[str, str], fmt_is_video: bool) -> Dict[str, str]:
    video = asset["kind"] == "video" or (asset["kind"] == "drive" and fmt_is_video)
    return {"video_url": asset["url"]} if video else {"image_url": asset["url"]}


def media_for(item: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Plano de publicação ({"type", "fields", "children"}) ou o motivo para ficar manual.
    Colaboradores (até 3 @) vão no contêiner principal de imagem, Reels e carrossel; Stories não aceitam."""
    plan, problem = _media_plan(item)
    if plan and plan["type"] == "story":
        manual_sticker = story_manual_instruction(item)
        if manual_sticker:
            return None, manual_sticker
    if plan and plan["type"] != "reels":
        music_problem = _music_outside_reels(item, plan["type"])
        if music_problem:
            return None, music_problem
    collaborators = clean_collaborators(item.get("collaborators"))
    if plan and collaborators and plan["type"] != "story":
        plan["fields"]["collaborators"] = json.dumps(collaborators)
    if plan and plan["type"] != "story" and item.get("product_tags"):
        _apply_product_tags(plan, item["product_tags"])
    if plan and plan["type"] == "reels" and item.get("reels_options"):
        from .ig_reels import apply_reels_options
        warning = apply_reels_options(plan, item["reels_options"])
        if warning:
            plan["warning"] = warning
    return plan, problem


def story_manual_instruction(item: Dict[str, Any]) -> Optional[str]:
    """Stories com sticker nativo só podem ser finalizados no aplicativo do Instagram."""
    if str(item.get("channel") or "instagram") != "instagram" or str(item.get("format") or "").lower() not in STORY_FORMATS:
        return None
    opts = item.get("reels_options")
    if not isinstance(opts, dict):
        return None
    sticker = opts.get("story_sticker")
    labels = {"poll": "enquete", "question": "caixa de perguntas", "quiz": "quiz",
              "emoji_slider": "controle de emoji", "link": "link clicável",
              "countdown": "contagem regressiva", "music": "música"}
    if sticker not in labels:
        return None
    instruction = str(opts.get("story_instruction") or "").strip()[:180]
    return (f"Story interativo ({labels[sticker]}): publique manualmente pelo Instagram e adicione o sticker nativo. "
            + (f"Instrução: {instruction}. " if instruction else "")
            + "Depois marque como publicado no Mugô Verso.")


def _music_outside_reels(item: Dict[str, Any], kind: str) -> Optional[str]:
    """A API da Meta só aceita música no Reels. Em Stories, imagem ou carrossel com música escolhida, o post não sai
    sozinho sem ela: fica para a equipe publicar à mão no app do Instagram, com a música anotada."""
    from .ig_reels import clean_music
    raw = item.get("reels_options")
    music = clean_music(raw.get("music")) if isinstance(raw, dict) else None
    if not music:
        return None
    label = {"story": "Stories", "image": "post de imagem", "carousel": "carrossel"}.get(kind, kind)
    name = " · ".join(x for x in (music.get("title"), music.get("artist")) if x) or f"áudio {music['audio_id']}"
    return (f"Música em {label} não vai pela API da Meta (só no Reels). Publique à mão no app do Instagram "
            f"com a música “{name}” e marque como publicado.")


def _apply_product_tags(plan: Dict[str, Any], raw: Any) -> None:
    """Produtos da loja no contêiner: imagem com x/y, Reels só o produto, carrossel slide a slide (5 por slide, 20 no total)."""
    from .ig_shop import MAX_TAGS, clean_product_tags, tags_for_container
    tags = clean_product_tags(raw)
    if not tags:
        return
    if plan["type"] == "image":
        found = tags_for_container(tags, image=True, slide=0)
    elif plan["type"] == "reels":
        found = tags_for_container(tags, image=False, limit=MAX_TAGS)
    else:
        found = []
        left = 20
        for index, child in enumerate(plan["children"]):
            mine = tags_for_container(tags, image="image_url" in child, slide=index, limit=min(5, left))
            if mine:
                child["product_tags"] = json.dumps(mine)
                left -= len(mine)
        return
    if found:
        plan["fields"]["product_tags"] = json.dumps(found)


def clean_collaborators(value: Any) -> List[str]:
    """@ do Instagram: sem @, minúsculo, letras/números/ponto/sublinhado, até 30 caracteres; no máximo 3, sem repetir."""
    out: List[str] = []
    for raw in (value or [])[:10]:
        user = str(raw or "").strip().lstrip("@").lower()
        if re.fullmatch(r"[a-z0-9._]{1,30}", user) and user not in out:
            out.append(user)
    return out[:3]


def _media_plan(item: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
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


def _to_jpeg(data: bytes) -> bytes:
    """Imagem → JPG que o Instagram aceita (RGB, fundo branco na transparência, até 1440 px de largura)."""
    from io import BytesIO
    from PIL import Image, ImageOps
    try:
        import pillow_heif  # type: ignore
        pillow_heif.register_heif_opener()
    except Exception:  # noqa: BLE001 - HEIC é opcional
        pass
    try:
        image = ImageOps.exif_transpose(Image.open(BytesIO(data)))
    except Exception as exc:  # noqa: BLE001
        raise StudioError("IG_PUBLISH_FAILED", "Não consegui abrir a imagem para converter em JPG. Envie a arte de novo.") from exc
    if image.mode in ("RGBA", "LA", "P"):
        image = image.convert("RGBA")
        flat = Image.new("RGB", image.size, (255, 255, 255))
        flat.paste(image, mask=image.split()[-1])
        image = flat
    else:
        image = image.convert("RGB")
    if image.width > 1440:
        image = image.resize((1440, round(image.height * 1440 / image.width)), Image.LANCZOS)
    out = BytesIO()
    image.save(out, "JPEG", quality=92, optimize=True)
    return out.getvalue()


async def ensure_jpeg(plan: Dict[str, Any], client_id: str) -> int:
    """Troca no plano as imagens que não são JPG por uma cópia JPG pública (Storage do MUGOVERSO). Devolve quantas trocou."""
    import hashlib
    from .ig_supabase import sb_upload_public
    targets = [(plan["fields"], "image_url"), (plan["fields"], "cover_url"), *((c, "image_url") for c in plan.get("children", []))]
    changed = 0
    for target, key in targets:
        url = target.get(key)
        if not url or "drive.google.com" in url or url.split("?", 1)[0].lower().endswith((".jpg", ".jpeg")):
            continue
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            got = await client.get(url)
        if got.status_code >= 400 or not got.content:
            raise StudioError("IG_PUBLISH_FAILED", "Não consegui baixar a arte para converter em JPG. Confira se o link está público.")
        if len(got.content) > JPEG_MAX_BYTES:
            raise StudioError("IG_PUBLISH_FAILED", "Imagem maior que 30 MB: envie uma versão menor.")
        jpeg = _to_jpeg(got.content)
        safe = re.sub(r"[^a-zA-Z0-9_-]", "", client_id)[:80]
        target[key] = await sb_upload_public(f"ig-publish/{safe}/{hashlib.sha1(url.encode()).hexdigest()[:20]}.jpg", jpeg, "image/jpeg")
        changed += 1
    return changed


async def _set(item: Dict[str, Any], patch: Dict[str, Any], *, expect: Optional[str] = None) -> bool:
    filters = {"id": f"eq.{item['id']}", "client_id": f"eq.{item['client_id']}"}
    filters["publish_status"] = f"eq.{expect}" if expect else "is.null"
    return bool(await sb_update(ITEMS_TABLE, filters=filters, patch=patch))


async def publish_item(item: Dict[str, Any], *, creds_cache: Dict[str, Any]) -> str:
    from .studio_calendar import AUTO_PUBLISH_CHANNELS, CHANNEL_LABELS
    channel = str(item.get("channel") or "instagram")
    if channel not in AUTO_PUBLISH_CHANNELS:
        # Outras plataformas não publicam sozinhas: na hora do post, fica avisado para publicar à mão.
        label = CHANNEL_LABELS.get(channel, channel)
        await _set(item, {"publish_status": "manual",
                          "publish_error": f"{label} não publica sozinho pelo Mugoverso. Publique à mão e marque como publicado."})
        return "manual"
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
        converted = await ensure_jpeg(container, client_id)
        if container["type"] == "reels":
            # Diagnóstico: quais opções foram no contêiner (nomes dos campos, sem token nem links).
            print(f"[ig_publish] reels item={item['id']} fields={sorted(container['fields'])} "
                  f"options={sorted((item.get('reels_options') or {}).keys()) if isinstance(item.get('reels_options'), dict) else 'sem_coluna'}")
        from .ig_shop import TAG_SCOPE, has_tags, strip_tags
        untagged = None
        if has_tags(container) and creds["scopes"] and TAG_SCOPE not in creds["scopes"]:
            container, untagged = strip_tags(container), "a conexão ainda não tem a permissão de marcar produtos"
        try:
            out = await publish(creds, container)
        except StudioError as exc:
            if not has_tags(container):
                raise
            # A Meta recusou com as marcações (loja não aprovada, produto inválido…): o post sai sem elas.
            out = await publish(creds, strip_tags(container))
            untagged = f"a Meta recusou as marcações ({(str(exc) if str(exc) != exc.code else exc.code)[:120]})"
        from .studio_history import record
        if untagged:
            await record(item["client_id"], item["id"], f"publicou sem marcar os produtos da loja: {untagged}",
                         actor_name="Publicação automática", side="sistema")
        if converted:
            await record(item["client_id"], item["id"], f"converteu {converted} imagem(ns) para JPG (o Instagram só aceita JPG)",
                         actor_name="Publicação automática", side="sistema")
        from .ig_reels import describe
        sent = describe(container, item.get("reels_options"))
        if sent:
            await record(item["client_id"], item["id"], sent, actor_name="Publicação automática", side="sistema")
        if container.get("warning"):
            await record(item["client_id"], item["id"], f"publicou o Reels, mas {container['warning']}",
                         actor_name="Publicação automática", side="sistema")
        await _first_comment(creds, item, out.get("media_id"))
        await _set(item, {"publish_status": "publicado", "status": "publicado", "published_at": datetime.now(timezone.utc).isoformat(),
                          "published_media_id": out["media_id"], "published_permalink": out.get("permalink")}, expect="publicando")
        return "publicado"
    except StudioError as exc:
        await _set(item, {"publish_status": "falhou", "publish_error": (str(exc) if str(exc) != exc.code else exc.code)[:300]}, expect="publicando")
        return "falhou"


async def _first_comment(creds: Dict[str, Any], item: Dict[str, Any], media_id: Optional[str]) -> None:
    """Primeiro comentário do Reels, logo depois de publicar. Falhou? O post continua publicado e fica no histórico."""
    from .ig_reels import first_comment
    from .studio_history import record
    message = first_comment(item)
    if not message or not media_id:
        return
    try:
        await _graph("POST", f"/{media_id}/comments", token=creds["token"], data={"message": message})
        await record(item["client_id"], item["id"], "publicou o primeiro comentário", actor_name="Publicação automática", side="sistema")
    except StudioError as exc:
        reason = (str(exc) if str(exc) != exc.code else exc.code)[:120]
        await record(item["client_id"], item["id"], f"não conseguiu publicar o primeiro comentário ({reason})",
                     actor_name="Publicação automática", side="sistema")


async def publish_due(*, now: Optional[datetime] = None) -> Dict[str, int]:
    now = now or datetime.now(timezone.utc)
    base = "id,client_id,channel,format,art_url,caption_draft,scheduled_at,status,schedule_confirmed_at,publish_status"
    query = dict(order="scheduled_at.asc", limit=MAX_PER_RUN,
                 filters={"status": "eq.aprovado", "schedule_confirmed_at": "not.is.null", "publish_status": "is.null",
                          "scheduled_at": f"lte.{now.isoformat()}"})
    # Antes da migração 000131 (Reels), 000098 (produtos) ou 000080 (colaboradores): publica igual, sem a coluna nova.
    items = None
    for extra in (",collaborators,product_tags,reels_options", ",collaborators,product_tags", ",collaborators"):
        try:
            items = await sb_select(ITEMS_TABLE, select=f"{base}{extra}", **query)
            break
        except Exception:  # noqa: BLE001
            print(f"[ig_publish] select_sem_colunas extra={extra} (migração pendente: música/capa/produtos podem não ir)")
            continue
    if items is None:
        items = await sb_select(ITEMS_TABLE, select=base, **query)
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
