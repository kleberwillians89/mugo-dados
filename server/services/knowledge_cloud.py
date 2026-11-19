"""Importar materiais do Google Drive e do Canva para o Conhecimento da marca (a IA do MUGOVERSO).

A pessoa cola um link e escolhe o que importar; cada arquivo segue o MESMO caminho do envio manual (o texto
ensina a IA, o original fica na Biblioteca, PDF escaneado é lido pela IA). Este módulo só lista e busca os arquivos.

- Drive: pasta (com subpastas, até 3 níveis), arquivo ou Google Docs/Apresentações/Planilhas, compartilhados como
  "qualquer pessoa com o link". Usa a API oficial do Drive com chave de API (GOOGLE_DRIVE_API_KEY, ou a do
  YouTube, se o Drive API estiver ativado no mesmo projeto do Google Cloud). Google Docs viram Word/PowerPoint/Excel.
- Canva: link público de visualização. O Canva só entrega a imagem de prévia do design (a primeira página): ela
  vira um PDF de uma página e a IA lê o texto da imagem. Para um design de várias páginas, exporte em PDF no Canva
  e coloque na pasta do Drive.

Nada é escrito no Drive nem no Canva. Só hosts do Google e do Canva, tamanho máximo, tipo conferido pelo conteúdo.
"""
from __future__ import annotations

import base64
import io
import os
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx

from .studio_calendar import StudioError

DRIVE_API = "https://www.googleapis.com/drive/v3"
MAX_BYTES = 10 * 1024 * 1024  # mesmo teto do envio manual
MAX_FILES = 100
MAX_DEPTH = 3
FOLDER_MIME = "application/vnd.google-apps.folder"
EXPORT = {
    "application/vnd.google-apps.document": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"),
    "application/vnd.google-apps.presentation": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", "pptx"),
    "application/vnd.google-apps.spreadsheet": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
}
READABLE = {
    "application/pdf": "pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx", "text/csv": "csv", "text/plain": "txt", "text/markdown": "md",
}
_FOLDER = re.compile(r"/folders/([\w-]{10,})")
_FILE = re.compile(r"(?:/file/d/|/document/d/|/presentation/d/|/spreadsheets/d/|[?&]id=)([\w-]{10,})")


def _key() -> str:
    key = (os.getenv("GOOGLE_DRIVE_API_KEY") or os.getenv("YOUTUBE_API_KEY") or "").strip()
    if not key:
        raise StudioError("DRIVE_NOT_CONFIGURED")
    return key


def parse_link(url: str) -> Tuple[str, str]:
    """('drive_folder' | 'drive_file' | 'canva', id ou link)."""
    text = str(url or "").strip()
    parsed = urlparse(text)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host:
        raise StudioError("CLOUD_LINK_INVALID")
    if host in ("drive.google.com", "docs.google.com"):
        folder = _FOLDER.search(parsed.path)
        if folder:
            return "drive_folder", folder.group(1)
        file = _FILE.search(text)
        if file:
            return "drive_file", file.group(1)
        raise StudioError("CLOUD_LINK_INVALID")
    if host == "canva.link" or host == "canva.com" or host.endswith(".canva.com"):
        return "canva", text
    raise StudioError("CLOUD_LINK_INVALID")


def classify(item: Dict[str, Any]) -> Dict[str, Any]:
    """Arquivo do Drive → o que a tela mostra (e se dá para ensinar a IA com ele)."""
    mime = str(item.get("mimeType") or "")
    name = str(item.get("name") or "arquivo")
    size = int(item.get("size") or 0) or None
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    supported, reason = True, None
    if mime in EXPORT:
        pass
    elif mime in READABLE or ext in ("pdf", "docx", "pptx", "xlsx", "csv", "txt", "md"):
        if size and size > MAX_BYTES:
            supported, reason = False, "Maior que 10 MB: divida o arquivo."
    elif mime.startswith("image/") or mime.startswith("video/") or mime.startswith("audio/"):
        supported, reason = False, "Imagem, vídeo ou áudio: não tem texto para a IA aprender."
    elif ext in ("ai", "psd", "indd", "fig", "sketch") or "illustrator" in mime or "photoshop" in mime:
        supported, reason = False, "Arquivo de design (.ai, .psd…): exporte em PDF para a IA ler."
    elif mime.startswith("application/vnd.google-apps."):
        supported, reason = False, "Este tipo do Google não tem texto para importar."
    else:
        supported, reason = False, "Formato que a IA não lê. Use PDF, Word, PowerPoint, Excel ou Google Docs."
    return {"id": str(item.get("id") or ""), "name": name, "mime": mime, "size": size, "path": item.get("_path") or "",
            "supported": supported, "reason": reason}


async def _drive_get(client: httpx.AsyncClient, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    resp = await client.get(f"{DRIVE_API}{path}", params={**params, "key": _key(), "supportsAllDrives": "true"})
    if resp.status_code in (403, 404):
        raise StudioError("DRIVE_PRIVATE")
    if resp.status_code >= 400:
        raise StudioError("DRIVE_UNAVAILABLE")
    return resp.json() or {}


async def list_link(url: str) -> Dict[str, Any]:
    kind, ref = parse_link(url)
    if kind == "canva":
        return {"source": "canva", "files": [{"id": ref, "name": "Design do Canva", "mime": "canva", "size": None, "path": "",
                                              "supported": True, "reason": None}], "truncated": False}
    async with httpx.AsyncClient(timeout=20) as client:
        if kind == "drive_file":
            item = await _drive_get(client, f"/files/{ref}", {"fields": "id,name,mimeType,size"})
            return {"source": "drive", "files": [classify(item)], "truncated": False}
        found: List[Dict[str, Any]] = []
        queue: List[Tuple[str, str, int]] = [(ref, "", 0)]
        truncated = False
        while queue and len(found) < MAX_FILES:
            folder, prefix, depth = queue.pop(0)
            token: Optional[str] = None
            for _ in range(10):
                params = {"q": f"'{folder}' in parents and trashed = false", "pageSize": 200, "orderBy": "folder,name",
                          "fields": "nextPageToken,files(id,name,mimeType,size)", "includeItemsFromAllDrives": "true"}
                if token:
                    params["pageToken"] = token
                body = await _drive_get(client, "/files", params)
                for item in body.get("files") or []:
                    if item.get("mimeType") == FOLDER_MIME:
                        if depth + 1 < MAX_DEPTH:
                            queue.append((str(item.get("id")), f"{prefix}{item.get('name')}/", depth + 1))
                        else:
                            truncated = True
                        continue
                    if len(found) >= MAX_FILES:
                        truncated = True
                        break
                    found.append(classify({**item, "_path": prefix}))
                token = body.get("nextPageToken")
                if not token:
                    break
        if queue:
            truncated = True
    found.sort(key=lambda f: (not f["supported"], f["path"], f["name"].lower()))
    return {"source": "drive", "files": found, "truncated": truncated}


def _with_ext(name: str, ext: str) -> str:
    base = re.sub(r"[\\/:*?\"<>|]+", " ", name).strip()[:150] or "arquivo"
    return base if base.lower().endswith(f".{ext}") else f"{base}.{ext}"


async def _download(client: httpx.AsyncClient, url: str, params: Dict[str, Any]) -> bytes:
    async with client.stream("GET", url, params=params) as resp:
        if resp.status_code in (403, 404):
            raise StudioError("DRIVE_PRIVATE")
        if resp.status_code >= 400:
            raise StudioError("DRIVE_UNAVAILABLE")
        data = bytearray()
        async for chunk in resp.aiter_bytes(256 * 1024):
            data.extend(chunk)
            if len(data) > MAX_BYTES:
                raise StudioError("DOC_TOO_LARGE")
    return bytes(data)


def image_to_pdf(raw: bytes) -> bytes:
    from PIL import Image
    with Image.open(io.BytesIO(raw)) as im:
        page = im.convert("RGB")
        out = io.BytesIO()
        page.save(out, format="PDF", resolution=150)
    return out.getvalue()


async def fetch_file(source: str, ref: str, name: str, mime: str) -> Dict[str, Any]:
    """Baixa um arquivo escolhido e devolve como o envio manual espera (nome com extensão + conteúdo)."""
    if source == "canva":
        from .studio_art_import import _canva_image, _get, _host_ok
        if parse_link(ref)[0] != "canva":
            raise StudioError("CLOUD_LINK_INVALID")
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            image_url = await _canva_image(client, ref)
            if not _host_ok(image_url):
                raise StudioError("ART_LINK_UNREADABLE")
            resp = await _get(client, image_url)
            try:
                data = bytearray()
                async for chunk in resp.aiter_bytes(256 * 1024):
                    data.extend(chunk)
                    if len(data) > MAX_BYTES:
                        raise StudioError("DOC_TOO_LARGE")
            finally:
                await resp.aclose()
        pdf = image_to_pdf(bytes(data))
        return {"file_name": _with_ext(name if name and name != "Design do Canva" else "Design do Canva", "pdf"),
                "mime": "application/pdf", "content_base64": base64.b64encode(pdf).decode(), "needs_ocr": True}
    if source != "drive" or not re.fullmatch(r"[\w-]{10,}", ref or ""):
        raise StudioError("CLOUD_LINK_INVALID")
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        if mime in EXPORT:
            target, ext = EXPORT[mime]
            raw = await _download(client, f"{DRIVE_API}/files/{ref}/export", {"mimeType": target, "key": _key()})
            file_name, out_mime = _with_ext(name, ext), target
        else:
            raw = await _download(client, f"{DRIVE_API}/files/{ref}", {"alt": "media", "key": _key(), "supportsAllDrives": "true"})
            ext = READABLE.get(mime) or (name.rsplit(".", 1)[-1].lower() if "." in name else "")
            if ext not in ("pdf", "docx", "pptx", "xlsx", "csv", "txt", "md"):
                raise StudioError("DOC_TYPE_INVALID")
            file_name, out_mime = _with_ext(name, ext), mime or "application/octet-stream"
    return {"file_name": file_name, "mime": out_mime, "content_base64": base64.b64encode(raw).decode(), "needs_ocr": False}
