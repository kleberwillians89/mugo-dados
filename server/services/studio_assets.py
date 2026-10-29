"""Mugô Studio — Biblioteca de mídia e arte anexada à pauta.

O arquivo NUNCA passa pelo Render (512 MB de RAM, corta requisição longa):

1. ``request_upload``: valida papel (na rota), tipo e tamanho, grava a linha
   "pendente" e devolve uma URL assinada de upload para
   ``{client_id}/{uuid}.{ext}`` no bucket privado.
2. O navegador envia o arquivo direto ao Storage nessa URL.
3. ``confirm_upload``: o backend lê o objeto real (existe, tamanho, tipo e a
   assinatura dos primeiros bytes) e só então marca "pronto". Arquivo que não
   bate com o declarado é apagado.

Leitura só por URL assinada de curta duração. Pendentes com mais de 24 h são
apagados por ``cleanup_pending`` (job studio-assets-cleanup no GitHub Actions).
O bucket também aplica teto de tamanho e tipos permitidos (migration 052).
"""
from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import parse_qs, quote, urlparse

import httpx

from .ig_supabase import sb_delete, sb_insert, sb_insert_many, sb_select, sb_update
from .studio_calendar import ITEMS_TABLE, StudioError

ASSETS_TABLE = "studio_assets"
LINKS_TABLE = "studio_calendar_item_assets"

MB = 1024 * 1024
# mime → (tipo, extensão). A mesma lista está no bucket (allowed_mime_types).
MIME_TYPES: Dict[str, tuple[str, str]] = {
    "image/jpeg": ("imagem", "jpg"),
    "image/png": ("imagem", "png"),
    "image/webp": ("imagem", "webp"),
    "video/mp4": ("video", "mp4"),
    "video/quicktime": ("video", "mov"),
    "application/pdf": ("pdf", "pdf"),
}
SIZE_LIMITS = {"imagem": 15 * MB, "video": 200 * MB, "pdf": 30 * MB}
THUMB_MIME = "image/jpeg"
THUMB_MAX_BYTES = 2 * MB
SIGNED_URL_SECONDS = 3600
PENDING_TTL_HOURS = 24
MAX_PENDING_PER_HOUR = 60
MAX_ITEM_ASSETS = 20  # limite de slides de um carrossel do Instagram
ATTACHABLE_KINDS = ("imagem", "video")
LIST_LIMIT = 300

# Campos que o painel da equipe recebe; a página pública recebe menos.
TEAM_FIELDS = ("id", "kind", "mime_type", "size_bytes", "name", "folder", "tags", "width", "height",
               "duration_seconds", "created_at", "updated_at")
PUBLIC_FIELDS = ("id", "kind", "mime_type", "width", "height", "duration_seconds")


def _bucket() -> str:
    return (os.getenv("STUDIO_ASSETS_BUCKET") or "studio-assets").strip()


def _storage_base() -> str:
    url = (os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
    key = (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not url.startswith(("http://", "https://")) or len(key) < 20:
        raise StudioError("STORAGE_NOT_CONFIGURED")
    return f"{url}/storage/v1"


def _storage_headers(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    key = (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    return {"apikey": key, "Authorization": f"Bearer {key}", **(extra or {})}


def _object_url(path: str) -> str:
    return quote(path, safe="/")


# --------------------------------------------------------------------------
# Storage (REST). Funções pequenas para os testes trocarem por mocks.
# --------------------------------------------------------------------------

async def storage_sign_upload(path: str) -> Dict[str, str]:
    """URL assinada de upload (válida por 2 h no Supabase), sem sobrescrever."""
    base = _storage_base()
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(f"{base}/object/upload/sign/{_bucket()}/{_object_url(path)}",
                              headers=_storage_headers({"x-upsert": "false"}))
    if r.status_code >= 400:
        raise StudioError("STORAGE_ERROR")
    relative = str((r.json() or {}).get("url") or "")
    token = (parse_qs(urlparse(relative).query).get("token") or [""])[0]
    if not token:
        raise StudioError("STORAGE_ERROR")
    return {"path": path, "token": token, "signed_url": f"{base}{relative}"}


async def storage_object_info(path: str) -> Optional[Dict[str, Any]]:
    """Tamanho e tipo gravados pelo Storage; None se o objeto não existe."""
    folder, _, name = path.rpartition("/")
    base = _storage_base()
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(f"{base}/object/list/{_bucket()}", headers=_storage_headers(),
                              json={"prefix": folder, "search": name, "limit": 10})
    if r.status_code >= 400:
        raise StudioError("STORAGE_ERROR")
    for entry in r.json() or []:
        if entry.get("name") == name and entry.get("id"):
            meta = entry.get("metadata") or {}
            return {"size": int(meta.get("size") or meta.get("contentLength") or 0),
                    "mimetype": str(meta.get("mimetype") or "").lower()}
    return None


async def storage_read_head(path: str, length: int = 32) -> bytes:
    """Primeiros bytes do objeto, para conferir a assinatura do formato."""
    base = _storage_base()
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(f"{base}/object/{_bucket()}/{_object_url(path)}",
                             headers=_storage_headers({"Range": f"bytes=0-{length - 1}"}))
    if r.status_code >= 400:
        raise StudioError("STORAGE_ERROR")
    return r.content[:length]


async def storage_sign_urls(paths: List[str], expires_in: int = SIGNED_URL_SECONDS) -> Dict[str, str]:
    """URLs assinadas de leitura, em uma chamada. Caminho sem URL fica de fora."""
    wanted = sorted({p for p in paths if p})
    if not wanted:
        return {}
    base = _storage_base()
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(f"{base}/object/sign/{_bucket()}", headers=_storage_headers(),
                              json={"expiresIn": expires_in, "paths": wanted})
    if r.status_code >= 400:
        raise StudioError("STORAGE_ERROR")
    out: Dict[str, str] = {}
    for entry in r.json() or []:
        signed = entry.get("signedURL") or entry.get("signedUrl")
        if entry.get("path") and signed and not entry.get("error"):
            out[str(entry["path"])] = f"{base}{signed}"
    return out


async def storage_remove(paths: Iterable[str]) -> None:
    wanted = sorted({p for p in paths if p})
    if not wanted:
        return
    base = _storage_base()
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.request("DELETE", f"{base}/object/{_bucket()}", headers=_storage_headers(),
                                 json={"prefixes": wanted})
    if r.status_code >= 400:
        raise StudioError("STORAGE_ERROR")


# --------------------------------------------------------------------------
# Validação
# --------------------------------------------------------------------------

def clean_name(raw: Any) -> str:
    name = re.sub(r"[\x00-\x1f]", "", str(raw or "")).replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"\s+", " ", name).strip()[:160]
    if not name:
        raise StudioError("NAME_INVALID")
    return name


def clean_folder(raw: Any) -> Optional[str]:
    folder = re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f/\\]", " ", str(raw or ""))).strip()[:80]
    return folder or None


def clean_tags(raw: Any) -> List[str]:
    values = re.split(r"[,\n]", raw) if isinstance(raw, str) else (raw or [])
    out: List[str] = []
    for value in values:
        tag = re.sub(r"\s+", " ", re.sub(r'["\\{}]', "", str(value or ""))).strip().lstrip("#").lower()[:40]
        if tag and tag not in out:
            out.append(tag)
        if len(out) >= 20:
            break
    return out


def classify(mime_type: str, size_bytes: int) -> tuple[str, str]:
    """(tipo, extensão) ou erro. O tamanho declarado é conferido de novo no confirm."""
    mime = (mime_type or "").lower().strip()
    if mime not in MIME_TYPES:
        raise StudioError("TYPE_NOT_ALLOWED")
    kind, ext = MIME_TYPES[mime]
    if not isinstance(size_bytes, int) or size_bytes <= 0:
        raise StudioError("SIZE_INVALID")
    if size_bytes > SIZE_LIMITS[kind]:
        raise StudioError("FILE_TOO_LARGE")
    return kind, ext


def signature_matches(mime_type: str, head: bytes) -> bool:
    """Confere os primeiros bytes contra o tipo declarado (não confia na extensão)."""
    if mime_type == "image/jpeg":
        return head[:3] == b"\xff\xd8\xff"
    if mime_type == "image/png":
        return head[:8] == b"\x89PNG\r\n\x1a\n"
    if mime_type == "image/webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    if mime_type == "application/pdf":
        return head[:5] == b"%PDF-"
    if mime_type in ("video/mp4", "video/quicktime"):
        # ISO BMFF/QuickTime: caixa "ftyp" (ou átomos antigos do .mov) logo após o tamanho.
        return head[4:8] in (b"ftyp", b"moov", b"mdat", b"wide", b"free", b"skip", b"pnot")
    return False


def _parse_ts(value: Any) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


# --------------------------------------------------------------------------
# Upload em duas etapas
# --------------------------------------------------------------------------

async def request_upload(client_id: str, *, file_name: str, mime_type: str, size_bytes: int,
                         folder: Optional[str], tags: Any, with_thumb: bool, user_id: str) -> Dict[str, Any]:
    kind, ext = classify(mime_type, size_bytes)
    name = clean_name(file_name)
    since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    recent = await sb_select(ASSETS_TABLE, select="id", limit=MAX_PENDING_PER_HOUR + 1,
                             filters={"client_id": f"eq.{client_id}", "status": "eq.pendente", "created_at": f"gte.{since}"})
    if len(recent) >= MAX_PENDING_PER_HOUR:
        raise StudioError("TOO_MANY_PENDING")

    asset_id = str(uuid.uuid4())
    path = f"{client_id}/{asset_id}.{ext}"
    thumb_path = f"{client_id}/{asset_id}.thumb.jpg" if with_thumb and kind in ATTACHABLE_KINDS else None
    row = await sb_insert(ASSETS_TABLE, {
        "id": asset_id, "client_id": client_id, "storage_path": path, "thumb_path": thumb_path,
        "kind": kind, "mime_type": mime_type.lower().strip(), "size_bytes": size_bytes, "name": name,
        "folder": clean_folder(folder), "tags": clean_tags(tags), "status": "pendente", "created_by": user_id,
    })
    if not row:
        raise StudioError("CREATE_FAILED")
    try:
        upload = await storage_sign_upload(path)
        thumb = await storage_sign_upload(thumb_path) if thumb_path else None
    except StudioError:
        await sb_delete(ASSETS_TABLE, filters={"client_id": f"eq.{client_id}", "id": f"eq.{asset_id}"})
        raise
    return {"asset": {k: row.get(k) for k in TEAM_FIELDS}, "upload": upload, "thumb_upload": thumb,
            "max_bytes": SIZE_LIMITS[kind]}


async def _load_asset(client_id: str, asset_id: str) -> Dict[str, Any]:
    rows = await sb_select(ASSETS_TABLE, select="*", filters={"client_id": f"eq.{client_id}", "id": f"eq.{asset_id}"}, limit=1)
    if not rows:
        raise StudioError("ASSET_NOT_FOUND")
    return rows[0]


async def _discard(client_id: str, row: Dict[str, Any]) -> None:
    try:
        await storage_remove([row.get("storage_path"), row.get("thumb_path")])
    finally:
        await sb_delete(ASSETS_TABLE, filters={"client_id": f"eq.{client_id}", "id": f"eq.{row['id']}"})


async def confirm_upload(client_id: str, asset_id: str, *, width: Optional[int], height: Optional[int],
                         duration_seconds: Optional[float]) -> Dict[str, Any]:
    row = await _load_asset(client_id, asset_id)
    if row.get("status") == "pronto":
        return (await sign_assets([row]))[0]
    path = str(row["storage_path"])
    if not path.startswith(f"{client_id}/"):  # defesa extra: caminho sempre dentro da pasta da empresa
        raise StudioError("ASSET_NOT_FOUND")
    info = await storage_object_info(path)
    if not info:
        raise StudioError("ASSET_NOT_UPLOADED")
    kind, mime = row["kind"], row["mime_type"]
    if info["size"] <= 0 or info["size"] > SIZE_LIMITS[kind]:
        await _discard(client_id, row)
        raise StudioError("FILE_TOO_LARGE")
    if info["mimetype"] != mime or not signature_matches(mime, await storage_read_head(path)):
        await _discard(client_id, row)
        raise StudioError("TYPE_MISMATCH")

    thumb_path = row.get("thumb_path")
    if thumb_path:
        thumb = await storage_object_info(str(thumb_path))
        if not thumb or thumb["mimetype"] != THUMB_MIME or thumb["size"] > THUMB_MAX_BYTES:
            if thumb:
                await storage_remove([str(thumb_path)])
            thumb_path = None

    patch: Dict[str, Any] = {"status": "pronto", "size_bytes": info["size"], "thumb_path": thumb_path,
                             "confirmed_at": datetime.now(timezone.utc).isoformat()}
    if width and height and 0 < width <= 20000 and 0 < height <= 20000:
        patch.update(width=int(width), height=int(height))
    if duration_seconds is not None and kind == "video" and 0 <= duration_seconds < 1_000_000:
        patch["duration_seconds"] = round(float(duration_seconds), 2)
    rows = await sb_update(ASSETS_TABLE, filters={"client_id": f"eq.{client_id}", "id": f"eq.{asset_id}"}, patch=patch)
    if not rows:
        raise StudioError("ASSET_NOT_FOUND")
    return (await sign_assets(rows))[0]


# --------------------------------------------------------------------------
# Biblioteca
# --------------------------------------------------------------------------

async def sign_assets(rows: List[Dict[str, Any]], *, public: bool = False) -> List[Dict[str, Any]]:
    urls = await storage_sign_urls([p for r in rows for p in (r.get("storage_path"), r.get("thumb_path"))])
    fields = PUBLIC_FIELDS if public else TEAM_FIELDS
    out = []
    for row in rows:
        url = urls.get(str(row.get("storage_path")))
        thumb = urls.get(str(row.get("thumb_path"))) if row.get("thumb_path") else None
        out.append({**{k: row.get(k) for k in fields}, "url": url,
                    "thumb_url": thumb or (url if row.get("kind") == "imagem" else None)})
    return out


async def list_assets(client_id: str, *, folder: Optional[str] = None, tag: Optional[str] = None,
                      kind: Optional[str] = None, q: Optional[str] = None) -> Dict[str, Any]:
    filters: Dict[str, str] = {"client_id": f"eq.{client_id}", "status": "eq.pronto"}
    if folder:
        filters["folder"] = f"eq.{clean_folder(folder)}"
    if tag and (tags := clean_tags([tag])):
        filters["tags"] = f'cs.{{"{tags[0]}"}}'
    if kind:
        if kind not in SIZE_LIMITS:
            raise StudioError("KIND_INVALID")
        filters["kind"] = f"eq.{kind}"
    if q and (term := re.sub(r"[%*,()]", " ", q).strip()[:80]):
        filters["name"] = f"ilike.*{term}*"
    rows = await sb_select(ASSETS_TABLE, select="*", filters=filters, order="created_at.desc", limit=LIST_LIMIT)
    facets = await sb_select(ASSETS_TABLE, select="folder,tags", limit=2000,
                             filters={"client_id": f"eq.{client_id}", "status": "eq.pronto"})
    usage: Dict[str, int] = {}
    if rows:
        ids = ",".join(str(r["id"]) for r in rows)
        for link in await sb_select(LINKS_TABLE, select="asset_id", limit=5000,
                                    filters={"client_id": f"eq.{client_id}", "asset_id": f"in.({ids})"}):
            usage[str(link["asset_id"])] = usage.get(str(link["asset_id"]), 0) + 1
    assets = await sign_assets(rows)
    for asset in assets:
        asset["used_in"] = usage.get(str(asset["id"]), 0)
    return {
        "assets": assets,
        "folders": sorted({str(f["folder"]) for f in facets if f.get("folder")}, key=str.lower),
        "tags": sorted({str(t) for f in facets for t in (f.get("tags") or [])}),
        "limits": {k: v for k, v in SIZE_LIMITS.items()},
        "url_expires_in": SIGNED_URL_SECONDS,
    }


async def update_asset(client_id: str, asset_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    clean: Dict[str, Any] = {}
    if "name" in patch and patch["name"] is not None:
        clean["name"] = clean_name(patch["name"])
    if "folder" in patch:
        clean["folder"] = clean_folder(patch["folder"])
    if "tags" in patch and patch["tags"] is not None:
        clean["tags"] = clean_tags(patch["tags"])
    if not clean:
        raise StudioError("EMPTY_PATCH")
    rows = await sb_update(ASSETS_TABLE, patch=clean,
                           filters={"client_id": f"eq.{client_id}", "id": f"eq.{asset_id}", "status": "eq.pronto"})
    if not rows:
        raise StudioError("ASSET_NOT_FOUND")
    return (await sign_assets(rows))[0]


async def delete_asset(client_id: str, asset_id: str) -> None:
    """Apaga o arquivo do Storage e a linha (os anexos das pautas caem junto)."""
    row = await _load_asset(client_id, asset_id)
    await storage_remove([row.get("storage_path"), row.get("thumb_path")])
    await sb_delete(ASSETS_TABLE, filters={"client_id": f"eq.{client_id}", "id": f"eq.{asset_id}"})


# --------------------------------------------------------------------------
# Arte na pauta
# --------------------------------------------------------------------------

async def item_assets(client_id: str, item_ids: List[str], *, public: bool = False) -> Dict[str, List[Dict[str, Any]]]:
    """{item_id: [mídias na ordem dos slides]} com URLs assinadas, em 3 consultas."""
    ids = sorted({str(i) for i in item_ids if i})
    if not ids:
        return {}
    links = await sb_select(LINKS_TABLE, select="item_id,asset_id,position", order="position.asc", limit=MAX_ITEM_ASSETS * len(ids),
                            filters={"client_id": f"eq.{client_id}", "item_id": f"in.({','.join(ids)})"})
    if not links:
        return {}
    asset_ids = sorted({str(link["asset_id"]) for link in links})
    rows = await sb_select(ASSETS_TABLE, select="*", limit=len(asset_ids),
                           filters={"client_id": f"eq.{client_id}", "status": "eq.pronto", "id": f"in.({','.join(asset_ids)})"})
    signed = {str(a["id"]): a for a in await sign_assets(rows, public=public)}
    out: Dict[str, List[Dict[str, Any]]] = {}
    for link in links:
        asset = signed.get(str(link["asset_id"]))
        if asset:
            out.setdefault(str(link["item_id"]), []).append(asset)
    return out


async def attach_assets(client_id: str, items: List[Dict[str, Any]], *, public: bool = False) -> List[Dict[str, Any]]:
    """Inclui ``assets`` em cada pauta. Falha do Storage não derruba o calendário."""
    try:
        by_item = await item_assets(client_id, [str(i.get("id")) for i in items], public=public)
    except StudioError:
        by_item = {}
    return [{**item, "assets": by_item.get(str(item.get("id")), [])} for item in items]


async def set_item_assets(client_id: str, item_id: str, asset_ids: List[str]) -> List[Dict[str, Any]]:
    """Troca as mídias da pauta pela lista recebida, nessa ordem (slide 1, 2, ...)."""
    wanted = [str(a) for a in asset_ids]
    if len(wanted) != len(set(wanted)):
        raise StudioError("ASSETS_DUPLICATED")
    if len(wanted) > MAX_ITEM_ASSETS:
        raise StudioError("TOO_MANY_ASSETS")
    items = await sb_select(ITEMS_TABLE, select="id", filters={"client_id": f"eq.{client_id}", "id": f"eq.{item_id}"}, limit=1)
    if not items:
        raise StudioError("ITEM_NOT_FOUND")
    if wanted:
        rows = await sb_select(ASSETS_TABLE, select="id,kind", limit=len(wanted),
                               filters={"client_id": f"eq.{client_id}", "status": "eq.pronto", "id": f"in.({','.join(wanted)})"})
        found = {str(r["id"]): r for r in rows}
        if set(found) != set(wanted):
            raise StudioError("ASSETS_INVALID")
        if any(found[a]["kind"] not in ATTACHABLE_KINDS for a in wanted):
            raise StudioError("ASSET_KIND_INVALID")
    await sb_delete(LINKS_TABLE, filters={"client_id": f"eq.{client_id}", "item_id": f"eq.{item_id}"})
    if wanted:
        await sb_insert_many(LINKS_TABLE, [{"item_id": item_id, "asset_id": a, "client_id": client_id, "position": pos}
                                           for pos, a in enumerate(wanted)])
    return (await item_assets(client_id, [item_id])).get(item_id, [])


# --------------------------------------------------------------------------
# Job: limpa uploads que nunca foram confirmados
# --------------------------------------------------------------------------

async def cleanup_pending(*, older_than_hours: int = PENDING_TTL_HOURS, limit: int = 500) -> Dict[str, Any]:
    # Nunca menos de 1 h: não apaga upload que ainda está em andamento.
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max(1, older_than_hours))).isoformat()
    rows = await sb_select(ASSETS_TABLE, select="id,storage_path,thumb_path", limit=limit,
                           filters={"status": "eq.pendente", "created_at": f"lt.{cutoff}"}, order="created_at.asc")
    if not rows:
        return {"ok": True, "removed": 0}
    # Upload que nunca chegou não tem objeto; o Storage ignora caminho inexistente.
    await storage_remove([p for r in rows for p in (r.get("storage_path"), r.get("thumb_path"))])
    ids = ",".join(str(r["id"]) for r in rows)
    await sb_delete(ASSETS_TABLE, filters={"status": "eq.pendente", "id": f"in.({ids})"})
    return {"ok": True, "removed": len(rows)}
