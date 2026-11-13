"""Pesquisa pública opcional no chat: consulta somente temas públicos predefinidos.

Perguntas, histórico, KPIs, documentos ou informações privadas nunca são
repassados à Brave. O modelo recebe resultados como dados não confiáveis.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from .external_research import get_provider

PATTERNS = {
    "concorrentes": r"concorrent|competidor|benchmark|outras marcas",
    "tendencias": r"tend[eê]nci|mercado|setor|novidade|lan[çc]amento",
    "conteudo": r"refer[eê]nci|conte[uú]do|campanha|criativ|comunica[çc][aã]o",
    "noticias": r"not[ií]cia|imprensa|mat[eé]ria|aconteceu|atualidade",
}
TRIGGER = re.compile(r"pesquis|internet|web|online|p[uú]blic|atual|recent|hoje|essa semana|últim|ultimo|novidade|tend[eê]nci|concorrent|benchmark|mercado|setor|not[ií]cia|refer[eê]ncia", re.I)


def category(question: str) -> str | None:
    """Somente classifica o assunto; texto da pergunta não sai para o buscador."""
    if not TRIGGER.search(question or ""):
        return None
    for key, pattern in PATTERNS.items():
        if re.search(pattern, question, re.I):
            return key
    return "tendencias"


def safe_sources(rows: Any) -> List[Dict[str, str]]:
    from urllib.parse import urlsplit
    out: List[Dict[str, str]] = []
    seen = set()
    for item in rows if isinstance(rows, list) else []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("source_url") or "")
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or url in seen:
            continue
        title = str(item.get("reason_relevant") or "").strip()[:180]
        observed = str(item.get("researched_at") or "").strip()[:35]
        if not title or not observed:
            continue
        seen.add(url)
        out.append({"title": title, "url": url, "researched_at": observed,
                    "snippet": str(item.get("public_signal") or "")[:240]})
        if len(out) >= 5:
            break
    return out


async def research(client_id: str, question: str) -> Dict[str, Any]:
    kind = category(question)
    if not kind:
        return {"status": "not_needed", "sources": []}
    provider = get_provider()
    if provider is None:
        return {"status": "not_configured", "sources": []}
    try:
        # Pesquisa com o nome público da marca e categorias fixas; nunca com a pergunta crua.
        if kind == "conteudo":
            results = await provider.find_content_references(client_id=client_id, query={})
        else:
            results = await provider.find_market_signals(client_id=client_id, query={})
        sources = safe_sources(results)
        return {"status": "ok" if sources else "no_results", "sources": sources}
    except Exception as exc:
        print(f"[mugo_ia][web] status=unavailable error_type={type(exc).__name__}")
        return {"status": "unavailable", "sources": []}
