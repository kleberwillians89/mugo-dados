"""E-mail com cara de marca quando a Mugô IA cria: fotos da Biblioteca, logo e cor da marca.

- Fotos: a IA diz que foto cada espaço pede ("foto de produto legging", "lifestyle"). Cada espaço recebe a foto da
  Biblioteca (Produto, Fotos da marca ou Logo e identidade não) que melhor combina pelo título; sem foto, o espaço fica
  marcado no editor ("Foto: …") para a equipe colar o link.
- Logo e cor: se o Remetente do E-mail Marketing ainda não tem logo ou cor, usa a logo da Biblioteca (categoria Logo e
  identidade, PNG/JPG/WebP: e-mail não mostra SVG) e tira a cor principal dela. Nunca troca o que a equipe já definiu.
- Só usa arquivos da pasta desta empresa no Storage.
"""
from __future__ import annotations

import io
import re
import unicodedata
from typing import Any, Dict, List, Optional

import httpx

from .ig_supabase import sb_select

EMAIL_IMAGES = ("image/jpeg", "image/png", "image/webp", "image/gif")
PHOTO_CATEGORIES = ("produto", "foto")
MAX_LOGO_BYTES = 4 * 1024 * 1024


def _words(text: str) -> set:
    plain = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return {w for w in re.findall(r"[a-z0-9]{3,}", plain) if w not in {"foto", "fotos", "imagem", "com", "para", "dos", "das"}}


def pick_photos(wanted: List[str], photos: List[Dict[str, Any]]) -> List[Optional[str]]:
    """Uma foto (url) por espaço pedido, a que mais combina pelo título, sem repetir. Puro, para teste."""
    free = list(photos)
    out: List[Optional[str]] = []
    for desc in wanted:
        if not free:
            out.append(None)
            continue
        want = _words(desc)
        best = max(free, key=lambda p: (len(want & _words(str(p.get("title") or ""))), p.get("category") == "produto"))
        free.remove(best)
        out.append(str(best.get("url")))
    return out


async def library_photos(client_id: str) -> List[Dict[str, Any]]:
    from .studio_library import _own_file
    rows = await sb_select("studio_library", select="title,category,url,mime_type,created_at", order="created_at.desc", limit=60,
                           filters={"client_id": f"eq.{client_id}", "kind": "eq.arquivo"})
    return [r for r in rows if str(r.get("mime_type") or "").lower() in EMAIL_IMAGES
            and r.get("category") in PHOTO_CATEGORIES and _own_file(str(r.get("url") or ""), client_id)]


def dominant_color(raw: bytes) -> Optional[str]:
    """Cor principal de uma logo (ignora fundo branco/transparente). Puro, para teste."""
    from PIL import Image
    try:
        img = Image.open(io.BytesIO(raw)).convert("RGBA")
    except Exception:  # noqa: BLE001
        return None
    img.thumbnail((96, 96))
    counts: Dict[tuple, int] = {}
    data = img.tobytes()
    for i in range(0, len(data), 4):
        r, g, b, a = data[i], data[i + 1], data[i + 2], data[i + 3]
        if a < 128 or (r > 235 and g > 235 and b > 235):
            continue
        key = (r // 16 * 16, g // 16 * 16, b // 16 * 16)
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return None
    r, g, b = max(counts, key=counts.get)
    return f"#{min(r + 8, 255):02x}{min(g + 8, 255):02x}{min(b + 8, 255):02x}"


async def ensure_brand_look(client_id: str, *, user_id: Optional[str]) -> Dict[str, Any]:
    """Completa logo e cor do Remetente com a logo da Biblioteca, só onde está vazio. Nunca levanta."""
    from .email_marketing import get_settings, save_settings
    from .studio_library import _own_file
    try:
        settings = await get_settings(client_id)
        if settings.get("logo_url") and settings.get("brand_color"):
            return {}
        rows = await sb_select("studio_library", select="url,mime_type", order="created_at.desc", limit=20,
                               filters={"client_id": f"eq.{client_id}", "kind": "eq.arquivo", "category": "eq.logo"})
        logo = next((r for r in rows if str(r.get("mime_type") or "").lower() in EMAIL_IMAGES[:3]
                     and _own_file(str(r.get("url") or ""), client_id)), None)
        if not logo:
            return {}
        patch: Dict[str, Any] = {}
        if not settings.get("logo_url"):
            patch["logo_url"] = logo["url"]
        if not settings.get("brand_color"):
            async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
                resp = await client.get(logo["url"])
            color = dominant_color(resp.content) if resp.status_code < 400 and len(resp.content) <= MAX_LOGO_BYTES else None
            if color:
                patch["brand_color"] = color
        if patch:
            await save_settings(client_id, patch, user_id=user_id)
        return patch
    except Exception as exc:  # noqa: BLE001 — sem logo/cor o e-mail sai com o padrão; nada quebra
        print(f"[email_brand_look] client_id={client_id} error_type={type(exc).__name__}")
        return {}
