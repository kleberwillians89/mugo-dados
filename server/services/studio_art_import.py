"""Trazer a arte de um link (Google Drive ou Canva) para o Storage da empresa.

Assim o link vira arquivo de verdade: aparece na prévia do post, o cliente vê na aprovação e publica sozinho.
- Drive: link de ARQUIVO compartilhado como "qualquer pessoa com o link" (pasta não dá: não é um arquivo).
- Canva: link de visualização público (canva.link/… ou canva.com/design/…/view). O Canva só entrega a imagem de
  prévia do design — boa para aprovar; para publicar em qualidade máxima, baixe no Canva e envie o arquivo.

Segurança: só hosts do Google Drive e do Canva, redirecionamentos checados a cada salto, tamanho máximo,
tipo conferido pelos primeiros bytes (não pelo que o site diz). O arquivo sobe pelo mesmo link assinado do envio normal.
"""
from __future__ import annotations

import html
import io
import re
import tempfile
from typing import Optional, Tuple
from urllib.parse import urljoin, urlparse

import httpx

from .studio_art import upload_target
from .studio_calendar import StudioError

MAX_BYTES = 200 * 1024 * 1024
MAX_HTML = 3 * 1024 * 1024
DRIVE_HOSTS = ("drive.google.com", "docs.google.com", "drive.usercontent.google.com")
_DRIVE_ID = re.compile(r"(?:/file/d/|[?&]id=)([\w-]{10,})")
_OG_IMAGE = re.compile(r"""<meta[^>]+property=["']og:image(?::url)?["'][^>]+content=["']([^"']+)["']""", re.I)
_OG_IMAGE_REV = re.compile(r"""<meta[^>]+content=["']([^"']+)["'][^>]+property=["']og:image(?::url)?["']""", re.I)


# O Canva bloqueia leitores sem cara de navegador (403 do Cloudflare), mesmo com o design público.
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/131.0.0.0 Safari/537.36")
CANVA_OEMBED = "https://www.canva.com/_oembed"
_REDIRECTS = (301, 302, 303, 307, 308)


def _is_canva(h: str) -> bool:
    return h in ("canva.link", "canva.com", "canva.ai") or h.endswith(".canva.com") or h.endswith(".canva.ai")


def _host_ok(url: str) -> bool:
    p = urlparse(url)
    if p.scheme != "https" or not p.hostname:
        return False
    h = p.hostname.lower()
    return h in DRIVE_HOSTS or h.endswith(".googleusercontent.com") or _is_canva(h)


def _headers(url: str) -> dict:
    h = (urlparse(url).hostname or "").lower()
    return {"User-Agent": BROWSER_UA if _is_canva(h) else "Mozilla/5.0 (MugoDados)",
            "Accept": "text/html,application/json,image/*;q=0.9,*/*;q=0.8", "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"}


def kind_of(url: str) -> str:
    h = (urlparse(url).hostname or "").lower()
    if h in DRIVE_HOSTS:
        return "drive"
    if _is_canva(h):
        return "canva"
    return "outro"


def sniff(head: bytes) -> Optional[str]:
    """Tipo pelo conteúdo (não confia no cabeçalho do site)."""
    if head[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[4:8] == b"ftyp":
        return "video/quicktime" if head[8:10] == b"qt" else "video/mp4"
    return None


async def _get(client: httpx.AsyncClient, url: str) -> httpx.Response:
    """GET seguindo redirecionamentos só entre hosts permitidos (máx. 6 saltos). Devolve a resposta em streaming."""
    for _ in range(6):
        if not _host_ok(url):
            raise StudioError("ART_LINK_INVALID")
        req = client.build_request("GET", url, headers=_headers(url))
        resp = await client.send(req, stream=True)
        if resp.status_code in _REDIRECTS and resp.headers.get("location"):
            url = urljoin(url, resp.headers["location"])
            await resp.aclose()
            continue
        return resp
    raise StudioError("ART_LINK_UNREADABLE")


async def _download(client: httpx.AsyncClient, url: str) -> Tuple[tempfile.SpooledTemporaryFile, int, bytes]:
    resp = await _get(client, url)
    try:
        if resp.status_code >= 400:
            raise StudioError("ART_LINK_PRIVATE" if resp.status_code in (401, 403, 404) else "ART_LINK_UNREADABLE")
        buf = tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024)
        size = 0
        head = b""
        async for chunk in resp.aiter_bytes(1024 * 256):
            size += len(chunk)
            if size > MAX_BYTES:
                raise StudioError("ART_LINK_TOO_LARGE")
            if len(head) < 64:
                head += chunk[: 64 - len(head)]
            buf.write(chunk)
        buf.seek(0)
        return buf, size, head
    finally:
        await resp.aclose()


async def _canva_design_url(client: httpx.AsyncClient, url: str) -> str:
    """Link curto canva.link/… → link canva.com do design (segue só os redirecionamentos, sem baixar a página)."""
    for _ in range(6):
        if not _host_ok(url):
            raise StudioError("ART_LINK_INVALID")
        if (urlparse(url).hostname or "").lower() != "canva.link":
            return url
        resp = await client.send(client.build_request("GET", url, headers=_headers(url)), stream=True)
        await resp.aclose()
        if resp.status_code in _REDIRECTS and resp.headers.get("location"):
            url = urljoin(url, resp.headers["location"])
            continue
        raise StudioError("ART_LINK_PRIVATE" if resp.status_code in (401, 403, 404) else "ART_LINK_UNREADABLE")
    raise StudioError("ART_LINK_UNREADABLE")


async def _canva_oembed(client: httpx.AsyncClient, design_url: str) -> Optional[str]:
    """Imagem do design pelo oEmbed oficial do Canva (feito para leitura por servidor; não passa pelo bloqueio da página)."""
    try:
        resp = await client.get(CANVA_OEMBED, params={"url": design_url, "format": "json"}, headers=_headers(CANVA_OEMBED))
        if resp.status_code >= 400:
            return None
        thumb = str((resp.json() or {}).get("thumbnail_url") or "").strip()
    except (httpx.HTTPError, ValueError, AttributeError):
        return None
    return thumb if thumb and _host_ok(thumb) else None


async def _canva_image(client: httpx.AsyncClient, url: str) -> str:
    design = await _canva_design_url(client, url)
    thumb = await _canva_oembed(client, design)
    if thumb:
        return thumb
    resp = await _get(client, design)
    try:
        if resp.status_code >= 400:
            # 403 do Cloudflare = o Canva bloqueou a leitura automática (o design pode estar público).
            blocked = resp.status_code in (403, 429) and ("cloudflare" in resp.headers.get("server", "").lower()
                                                          or "cf-mitigated" in resp.headers)
            raise StudioError("ART_LINK_BLOCKED" if blocked else "ART_LINK_PRIVATE")
        body = b""
        async for chunk in resp.aiter_bytes(1024 * 64):
            body += chunk
            if len(body) > MAX_HTML:
                break
        final = str(resp.url)
    finally:
        await resp.aclose()
    text = body.decode("utf-8", errors="ignore")
    m = _OG_IMAGE.search(text) or _OG_IMAGE_REV.search(text)
    if not m:
        raise StudioError("ART_LINK_PRIVATE")
    image = urljoin(final, html.unescape(m.group(1)))
    if not _host_ok(image):
        raise StudioError("ART_LINK_UNREADABLE")
    return image


def _to_jpeg(buf, content_type: str) -> Tuple[io.BytesIO, int]:
    from PIL import Image
    with Image.open(buf) as im:
        im = im.convert("RGBA") if im.mode in ("P", "LA") else im
        if im.mode == "RGBA":
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.split()[3])
            im = bg
        else:
            im = im.convert("RGB")
        out = io.BytesIO()
        im.save(out, "JPEG", quality=92)
    size = out.tell()
    out.seek(0)
    return out, size


async def import_art(client_id: str, url: str, item_id: Optional[str] = None) -> dict:
    url = str(url or "").strip()
    kind = kind_of(url)
    if kind == "outro" or not _host_ok(url):
        raise StudioError("ART_LINK_INVALID")
    if kind == "drive" and "/folders/" in url:
        raise StudioError("ART_LINK_FOLDER")
    note = None
    async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=15)) as client:
        if kind == "drive":
            m = _DRIVE_ID.search(url)
            if not m:
                raise StudioError("ART_LINK_INVALID")
            source = f"https://drive.usercontent.google.com/download?id={m.group(1)}&export=download&confirm=t"
        else:
            source = await _canva_image(client, url)
            note = "Prévia do Canva (resolução de visualização). Para publicar em qualidade máxima, baixe no Canva e envie o arquivo."
        buf, size, head = await _download(client, source)
        try:
            ctype = sniff(head)
            if not ctype:
                raise StudioError("ART_LINK_PRIVATE" if head.lstrip()[:1] == b"<" else "ART_LINK_UNREADABLE")
            body, length = buf, size
            if ctype in ("image/png", "image/webp"):
                body, length = _to_jpeg(buf, ctype)
                ctype = "image/jpeg"
            target = await upload_target(client_id, item_id or "", ctype)
            async def chunks():
                while True:
                    part = body.read(1024 * 1024)
                    if not part:
                        break
                    yield part
            put = await client.put(target["upload_url"], content=chunks(),
                                   headers={"Content-Type": ctype, "x-upsert": "false", "Content-Length": str(length)})
            if put.status_code >= 400:
                raise StudioError("STORAGE_UPLOAD_FAILED")
        finally:
            buf.close()
    return {"public_url": target["public_url"], "content_type": ctype, "bytes": length, "source": kind, "note": note}
