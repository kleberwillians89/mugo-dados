"""Referências da marca: links e artes que o cliente gosta (Aprovação → Referências).

Cliente (inclusive leitor) e equipe Mugô adicionam. Só link https (Instagram, Pinterest, Behance, Drive...)
ou arte enviada pelo painel (Storage público da empresa). Referência do cliente avisa o time pelo mesmo
caminho dos comentários. Cada um apaga a própria; a equipe Mugô apaga qualquer uma da empresa.
"""
from __future__ import annotations

import os
import re
import uuid
from typing import Any, Dict, List, Optional

from .ig_supabase import _request, sb_insert, sb_select
from .studio_calendar import StudioError

TABLE = "studio_references"
MAX_NOTE = 500
IMAGE_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
_URL = re.compile(r"^https://[^\s<>\"']{4,2000}$")


def clean_url(value: Any) -> str:
    url = str(value or "").strip()
    if not _URL.match(url):
        raise StudioError("REFERENCE_URL_INVALID")
    return url


async def list_references(client_id: str, item_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Sem item_id: referências da marca (aba); com item_id: só as daquele post."""
    filters = {"client_id": f"eq.{client_id}", "item_id": f"eq.{item_id}" if item_id else "is.null"}
    select = "id,url,kind,note,author_side,author_id,created_at"
    try:
        return await sb_select(TABLE, select=select, order="created_at.desc", limit=200, filters=filters)
    except Exception:  # noqa: BLE001 — migração 000075 ainda não aplicada: a aba da marca segue funcionando
        if item_id:
            return []
        return await sb_select(TABLE, select=select, order="created_at.desc", limit=200, filters={"client_id": f"eq.{client_id}"})


async def add_reference(client_id: str, *, url: str, note: Optional[str], kind: str, agency: bool,
                        user_id: Optional[str], item: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if kind not in ("link", "arte"):
        raise StudioError("REFERENCE_URL_INVALID")
    url = clean_url(url)
    if kind == "arte" and f"/studio-refs/{re.sub(r'[^a-zA-Z0-9_-]', '', client_id)[:80]}/" not in url:
        raise StudioError("REFERENCE_URL_INVALID")  # arte só do Storage desta empresa
    text = re.sub(r"\s+", " ", str(note or "")).strip()[:MAX_NOTE] or None
    side = "mugo" if agency else "cliente"
    row = await sb_insert(TABLE, {"client_id": client_id, "url": url, "kind": kind, "note": text,
                                  "author_id": user_id, "author_side": side, **({"item_id": item["id"]} if item else {})})
    if not agency:
        from .studio_team import notify_team
        item = item or {"id": None, "title": "Referências da marca", "status": "referencia", "scheduled_at": None}
        try:
            await notify_team(client_id, item, "comentario", actor_name="O cliente pelo painel",
                              comment=f"Nova referência: {url}" + (f" — {text}" if text else ""))
        except Exception as exc:  # noqa: BLE001 — aviso ao time não impede salvar a referência
            print(f"[studio_references] notify_failed client_id={client_id} error_type={exc.__class__.__name__}")
    return row or {"url": url, "kind": kind, "note": text, "author_side": side}


async def delete_reference(client_id: str, reference_id: str, *, agency: bool, user_id: Optional[str]) -> None:
    filters = {"client_id": f"eq.{client_id}", "id": f"eq.{reference_id}"}
    if not agency:
        filters["author_id"] = f"eq.{user_id}"
    rows = await sb_select(TABLE, select="id", filters=filters, limit=1)
    if not rows:
        raise StudioError("REFERENCE_NOT_FOUND")
    await _request("DELETE", f"/{TABLE}", params=filters)


async def upload_target(client_id: str, content_type: str) -> Dict[str, str]:
    """Link assinado (2 h, 1 arquivo) para a arte de referência ir direto do navegador ao Storage."""
    import httpx
    ext = IMAGE_TYPES.get(str(content_type or "").lower())
    if not ext:
        raise StudioError("REFERENCE_TYPE_INVALID")
    bucket = (os.getenv("IG_MEDIA_BUCKET") or "ig-media").strip()
    path = f"studio-refs/{re.sub(r'[^a-zA-Z0-9_-]', '', client_id)[:80]}/{uuid.uuid4().hex}.{ext}"
    base = (os.getenv("SUPABASE_URL") or "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or ""
    if not base or not key:
        raise StudioError("STORAGE_NOT_CONFIGURED")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(f"{base}/storage/v1/object/upload/sign/{bucket}/{path}",
                                     headers={"Authorization": f"Bearer {key}", "apikey": key}, json={"expiresIn": 7200})
    signed = str((response.json() or {}).get("url") or "") if response.status_code < 400 else ""
    if not signed:
        raise StudioError("STORAGE_UPLOAD_FAILED")
    return {"upload_url": f"{base}/storage/v1{signed}" if signed.startswith("/") else signed,
            "public_url": f"{base}/storage/v1/object/public/{bucket}/{path}", "content_type": content_type}
