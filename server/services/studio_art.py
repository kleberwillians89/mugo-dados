"""Upload da arte pelo modal do post, direto do navegador para o Storage público (bucket IG_MEDIA_BUCKET).

O backend só gera um link assinado de upload (vale 2 h, um arquivo, caminho da própria empresa): o arquivo
não passa pelo servidor (vídeo de Reels é grande demais para o plano do Render). Imagem chega em JPEG
(o navegador converte), que é o único formato que a Meta aceita para publicar; vídeo em MP4/MOV.
"""
from __future__ import annotations

import os
import re
import uuid
from typing import Dict

import httpx

from .studio_calendar import StudioError

ALLOWED = {"image/jpeg": "jpg", "video/mp4": "mp4", "video/quicktime": "mov"}


def _bucket() -> str:
    return (os.getenv("IG_MEDIA_BUCKET") or "ig-media").strip()


async def upload_target(client_id: str, item_id: str, content_type: str) -> Dict[str, str]:
    ext = ALLOWED.get(str(content_type or "").lower())
    if not ext:
        raise StudioError("ART_TYPE_INVALID")
    safe_client = re.sub(r"[^a-zA-Z0-9_-]", "", client_id)[:80]
    safe_item = re.sub(r"[^a-fA-F0-9-]", "", item_id)[:40] or "nova"
    path = f"studio-art/{safe_client}/{safe_item}/{uuid.uuid4().hex}.{ext}"
    base = (os.getenv("SUPABASE_URL") or "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or ""
    if not base or not key:
        raise StudioError("STORAGE_NOT_CONFIGURED")
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
