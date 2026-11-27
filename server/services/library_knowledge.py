"""A IA lê a Biblioteca: todo documento enviado para a Biblioteca da marca vira Conhecimento da marca.

Antes, a Biblioteca só guardava o arquivo e a IA via o nome dele. Agora, PDF, Word, PowerPoint, planilha e texto
enviados à Biblioteca são lidos (o texto extraído vai para ``brand_documents``/``brand_chunks`` pelo mesmo
``brand_knowledge.learn`` do Contexto da Marca), sem ninguém precisar enviar duas vezes.

- Roda sozinho depois de cada envio para a Biblioteca e ao abrir o Contexto da Marca (``sync``).
- Não repete: um arquivo conta como lido se já existe documento do Conhecimento com o mesmo nome, ou se o próprio
  arquivo é o original guardado pelo Conhecimento (nota "Conhecimento da marca · doc:").
- Só baixa arquivos da pasta desta empresa no Storage (nunca um link qualquer).
- PDF sem texto (escaneado) é lido pelas páginas com IA, até o limite do OCR.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import httpx

from .ig_supabase import sb_select
from .studio_calendar import StudioError

ORIGINAL_NOTE_PREFIX = "Conhecimento da marca · doc:"   # mesmo prefixo de src/app/brandKnowledgeUpload.ts
DOC_TYPES = {
    "application/pdf": "pdf", "text/plain": "txt", "text/csv": "csv", "text/markdown": "md",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
}
CATEGORY_KIND = {"produto": "produto", "logo": "institucional", "documento": "institucional"}
BATCH = 4            # por rodada (cada documento é uma chamada de IA)
_RUNNING: set[str] = set()
_FAILED: set[str] = set()   # não insiste no mesmo arquivo ruim (nem paga OCR de novo) enquanto o servidor estiver no ar


def file_name(item: Dict[str, Any]) -> str:
    """Nome com a extensão certa (é ela que decide como extrair o texto)."""
    ext = DOC_TYPES.get(str(item.get("mime_type") or "").lower(), "")
    title = str(item.get("title") or "Documento").strip() or "Documento"
    return title if not ext or title.lower().endswith(f".{ext}") else f"{title}.{ext}"


def pending_items(library: List[Dict[str, Any]], known_names: set[str]) -> List[Dict[str, Any]]:
    """Documentos da Biblioteca que a IA ainda não leu. Puro, para teste."""
    from .brand_knowledge import _clean_name
    from .studio_library import POST_NOTES
    out = []
    for item in library:
        note = str(item.get("note") or "").strip()
        if item.get("kind") != "arquivo" or str(item.get("mime_type") or "").lower() not in DOC_TYPES:
            continue
        if note.startswith(ORIGINAL_NOTE_PREFIX) or note in POST_NOTES:
            continue
        if _clean_name(file_name(item)) in known_names or _clean_name(str(item.get("title") or "")) in known_names:
            continue
        out.append(item)
    return out


async def pending(client_id: str) -> List[Dict[str, Any]]:
    from .brand_knowledge import DOCUMENTS
    library = await sb_select("studio_library", select="id,kind,category,title,note,url,mime_type,size_bytes,created_at",
                              order="created_at.desc", limit=200, filters={"client_id": f"eq.{client_id}", "kind": "eq.arquivo"})
    docs = await sb_select(DOCUMENTS, select="name", limit=1000, filters={"client_id": f"eq.{client_id}"})
    return pending_items(library, {str(d.get("name") or "") for d in docs})


async def _download(client_id: str, url: str, limit: int) -> bytes:
    from .studio_library import _own_file
    if not _own_file(url, client_id):
        raise StudioError("LIBRARY_URL_INVALID")
    async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=15), follow_redirects=False) as client:
        async with client.stream("GET", url) as resp:
            if resp.status_code >= 400:
                raise StudioError("DOC_UNREADABLE")
            data = bytearray()
            async for chunk in resp.aiter_bytes(256 * 1024):
                data.extend(chunk)
                if len(data) > limit:
                    raise StudioError("DOC_TOO_LARGE")
    if not data:
        raise StudioError("DOC_EMPTY")
    return bytes(data)


async def _text(client_id: str, name: str, raw: bytes) -> str:
    from .brand_knowledge import extract_text
    try:
        return extract_text(name, raw)
    except StudioError as exc:
        if exc.code != "DOC_EMPTY" or not name.lower().endswith(".pdf"):
            raise
    from .brand_ocr import ocr_pdf   # PDF escaneado: a IA lê as páginas
    return (await ocr_pdf(client_id, raw))["text"]


REASONS = {"DOC_TOO_LARGE": "maior que 10 MB", "DOC_EMPTY": "sem texto para ler", "OCR_EMPTY": "páginas sem texto legível",
           "DOC_UNREADABLE": "arquivo protegido ou corrompido", "LIBRARY_URL_INVALID": "fora da pasta da empresa"}


async def learn_one(client_id: str, item: Dict[str, Any], *, user_id: Optional[str]) -> Dict[str, Any]:
    from .brand_knowledge import MAX_BYTES, learn
    name = file_name(item)
    if int(item.get("size_bytes") or 0) > MAX_BYTES:
        return {"name": name, "status": "pulado", "reason": REASONS["DOC_TOO_LARGE"]}
    try:
        raw = await _download(client_id, str(item.get("url") or ""), MAX_BYTES)
        text = await _text(client_id, name, raw)
        result = await learn(client_id, file_name=name, kind=CATEGORY_KIND.get(str(item.get("category") or ""), "outro"),
                             text=text, user_id=user_id)
    except StudioError as exc:
        _FAILED.add(str(item.get("id")))
        return {"name": name, "status": "pulado", "reason": REASONS.get(exc.code, exc.code)}
    except Exception as exc:  # noqa: BLE001 — um arquivo ruim não para os outros
        _FAILED.add(str(item.get("id")))
        print(f"[library_knowledge] client_id={client_id} item={item.get('id')} error_type={exc.__class__.__name__}")
        return {"name": name, "status": "pulado", "reason": "falha ao ler"}
    doc = result.get("document") or {}
    return {"name": name, "status": doc.get("status") or "aprendido", "document_id": doc.get("id")}


async def sync(client_id: str, *, user_id: Optional[str] = None, batch: int = BATCH) -> Dict[str, Any]:
    """Lê os documentos novos da Biblioteca (até ``batch`` por rodada). Uma rodada por empresa de cada vez."""
    if client_id in _RUNNING:
        return {"running": True, "read": [], "skipped": [], "left": None}
    _RUNNING.add(client_id)
    try:
        todo = [i for i in await pending(client_id) if str(i.get("id")) not in _FAILED]
        results = [await learn_one(client_id, item, user_id=user_id) for item in todo[:batch]]
    finally:
        _RUNNING.discard(client_id)
    return {"running": False, "read": [r for r in results if r["status"] != "pulado"],
            "skipped": [r for r in results if r["status"] == "pulado"], "left": max(0, len(todo) - batch)}


def schedule(client_id: str, *, user_id: Optional[str] = None) -> None:
    """Depois de um envio para a Biblioteca: lê em segundo plano, sem segurar a resposta. Nunca levanta."""
    async def run() -> None:
        try:
            await sync(client_id, user_id=user_id)
        except Exception as exc:  # noqa: BLE001
            print(f"[library_knowledge] schedule client_id={client_id} error_type={exc.__class__.__name__}")
    try:
        asyncio.get_running_loop().create_task(run())
    except RuntimeError:
        pass
