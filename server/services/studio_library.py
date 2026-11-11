"""Biblioteca da marca (trazida da iAgência): arquivos e links por categoria.

- A equipe e o cliente enviam arquivos (direto do navegador para o Storage, com link assinado: o arquivo não passa
  pelo servidor) ou colam links (Drive, Canva, Figma, site).
- "Aprovados": a arte dos posts aprovados/publicados entra sozinha, lida do Calendário (não duplica aqui).
- Quem enviou (equipe ou cliente) fica marcado; o cliente só apaga o que ele mesmo enviou.
"""
from __future__ import annotations

import os
import re
import uuid
from typing import Any, Dict, List, Optional

import httpx

from .ig_supabase import sb_delete, sb_insert, sb_select
from .studio_calendar import ITEMS_TABLE, StudioError

TABLE = "studio_library"
CATEGORIES = {"produto": "Produto", "logo": "Logo", "referencia": "Referência", "foto": "Foto", "video": "Vídeo bruto",
              "documento": "Documento", "outro": "Outro"}
TYPES = {
    "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif", "image/svg+xml": "svg",
    "video/mp4": "mp4", "video/quicktime": "mov", "video/webm": "webm",
    "application/pdf": "pdf", "application/zip": "zip", "text/plain": "txt", "text/csv": "csv",
    "application/msword": "doc", "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.ms-powerpoint": "ppt", "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/vnd.ms-excel": "xls", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
}


def _bucket() -> str:
    return (os.getenv("IG_MEDIA_BUCKET") or "ig-media").strip()


def _storage() -> tuple[str, str]:
    base = (os.getenv("SUPABASE_URL") or "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or ""
    if not base or not key:
        raise StudioError("STORAGE_NOT_CONFIGURED")
    return base, key


async def upload_target(client_id: str, content_type: str) -> Dict[str, str]:
    """Link assinado (2 h) para o navegador enviar um arquivo para a pasta da empresa."""
    ext = TYPES.get(str(content_type or "").lower())
    if not ext:
        raise StudioError("LIBRARY_TYPE_INVALID", "Tipo de arquivo não aceito. Envie imagem, vídeo, PDF ou documento do Office.")
    base, key = _storage()
    safe = re.sub(r"[^a-zA-Z0-9_-]", "", client_id)[:80]
    path = f"studio-library/{safe}/{uuid.uuid4().hex}.{ext}"
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(f"{base}/storage/v1/object/upload/sign/{_bucket()}/{path}",
                                     headers={"Authorization": f"Bearer {key}", "apikey": key}, json={"expiresIn": 7200})
    if response.status_code >= 400:
        raise StudioError("STORAGE_UPLOAD_FAILED")
    signed = str((response.json() or {}).get("url") or "")
    if not signed:
        raise StudioError("STORAGE_UPLOAD_FAILED")
    return {"upload_url": f"{base}/storage/v1{signed}" if signed.startswith("/") else signed,
            "public_url": f"{base}/storage/v1/object/public/{_bucket()}/{path}", "content_type": content_type}


def _own_file(url: str, client_id: str) -> bool:
    """Arquivo enviado pela Biblioteca desta empresa (só esses podem ser registrados como 'arquivo')."""
    safe = re.sub(r"[^a-zA-Z0-9_-]", "", client_id)[:80]
    return f"/object/public/{_bucket()}/studio-library/{safe}/" in url


async def add_item(client_id: str, data: Dict[str, Any], *, user_id: str, author: str, side: str) -> Dict[str, Any]:
    url = str(data.get("url") or "").strip()
    if not url.startswith("https://") or len(url) > 1000:
        raise StudioError("LIBRARY_URL_INVALID", "Use um link completo, começando com https://")
    kind = "arquivo" if data.get("kind") == "arquivo" else "link"
    if kind == "arquivo" and not _own_file(url, client_id):
        raise StudioError("LIBRARY_URL_INVALID", "Arquivo fora da Biblioteca desta empresa.")
    category = data.get("category") if data.get("category") in CATEGORIES else "outro"
    title = " ".join(str(data.get("title") or "").split())[:200] or url.rsplit("/", 1)[-1][:200] or "Sem título"
    row = await sb_insert(TABLE, {
        "client_id": client_id, "kind": kind, "category": category, "title": title, "url": url,
        "mime_type": str(data.get("mime_type") or "")[:120] or None,
        "size_bytes": int(data["size_bytes"]) if str(data.get("size_bytes") or "").isdigit() else None,
        "note": " ".join(str(data.get("note") or "").split())[:500] or None,
        "side": side, "created_by": user_id, "created_by_name": (author or "")[:120] or None,
    })
    if not row:
        raise StudioError("LIBRARY_SAVE_FAILED", "Não foi possível salvar na Biblioteca.")
    return row


async def approved_posts(client_id: str, limit: int = 60) -> List[Dict[str, Any]]:
    """Arte dos posts aprovados e publicados (do Calendário), como itens da Biblioteca."""
    rows = await sb_select(ITEMS_TABLE, select="id,title,format,art_url,status,scheduled_at,published_permalink",
                           filters={"client_id": f"eq.{client_id}", "status": "in.(aprovado,publicado)", "art_url": "not.is.null"},
                           order="scheduled_at.desc", limit=limit)
    out: List[Dict[str, Any]] = []
    for r in rows:
        for i, url in enumerate(u for u in re.split(r"\s+", str(r.get("art_url") or "")) if u.startswith("https://")):
            out.append({"id": f"post-{r['id']}-{i}", "kind": "post", "category": "aprovado", "title": r.get("title") or "Post",
                        "url": url, "side": "mugo", "created_at": r.get("scheduled_at"), "item_id": r["id"], "status": r.get("status"),
                        "permalink": r.get("published_permalink"), "format": r.get("format")})
    return out


async def list_items(client_id: str, *, user_id: str, team: bool) -> List[Dict[str, Any]]:
    rows = await sb_select(TABLE, select="*", filters={"client_id": f"eq.{client_id}"}, order="created_at.desc", limit=500)
    return [{**r, "can_delete": team or str(r.get("created_by") or "") == user_id} for r in rows]


async def delete_item(client_id: str, item_id: str, *, user_id: str, team: bool) -> None:
    rows = await sb_select(TABLE, select="id,created_by", filters={"client_id": f"eq.{client_id}", "id": f"eq.{item_id}"}, limit=1)
    if not rows:
        raise StudioError("LIBRARY_NOT_FOUND", "Item não encontrado.")
    if not team and str(rows[0].get("created_by") or "") != user_id:
        raise StudioError("LIBRARY_FORBIDDEN", "Você só pode apagar o que você enviou.")
    await sb_delete(TABLE, filters={"client_id": f"eq.{client_id}", "id": f"eq.{item_id}"}, returning="minimal")
