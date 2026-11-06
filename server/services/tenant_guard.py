"""Auditoria anti-vazamento entre clientes: nenhum texto gerado pela IA para uma marca pode citar outra.

Os termos de cada marca vêm do cadastro (nome da empresa, partes marcantes do nome, @ do Instagram).
Para a marca X, os proibidos são os termos de TODAS as outras, menos:
- os que também são da própria X (ex.: palavra em comum);
- os neutros (Mugô, a agência, aparece em qualquer marca; palavras genéricas como "tapas", "parfums").

Sem IA, sem custo: comparação por palavra inteira, sem acento e sem maiúscula.
Lista em cache por 10 minutos; se o banco falhar, a auditoria não derruba nada (devolve lista vazia).
"""
from __future__ import annotations

import re
import time
import unicodedata
from typing import Dict, Iterable, List, Set, Tuple

from .ig_supabase import sb_select

CACHE_SECONDS = 600
_CACHE: Tuple[float, Dict[str, Set[str]]] = (0.0, {})

# A Mugô aparece em textos de qualquer marca (equipe, assinatura): não é vazamento.
NEUTRAL = {"mugo", "mugô", "mugo agencia", "mugo agência", "mugo ag", "mugo.ag", "equipe mugo", "mugoverso"}
# Palavras genéricas que fazem parte de nomes de clientes mas são comuns em qualquer texto.
GENERIC = {
    "tapas", "brasilenas", "brasileñas", "brasileiras", "brasil", "investimentos", "investimento", "parfums", "perfumes",
    "perfomance", "performance", "agencia", "agência", "oficial", "store", "loja", "studio", "comunidade", "community",
    "run", "runners", "club", "clube", "grupo", "group", "brand", "marca", "shop", "online", "digital", "foods", "food",
    "cafe", "café", "beauty", "fitness", "moda", "casa", "home", "vinhos", "wines", "the",
}


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text or "").lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def terms_for(name: str, usernames: Iterable[str] = ()) -> Set[str]:
    """Termos que identificam uma marca."""
    out: Set[str] = set()
    full = re.sub(r"\s+", " ", norm(name)).strip()
    if len(full) >= 4:
        out.add(full)
    for word in re.findall(r"[a-z0-9][a-z0-9'&.-]*", full):
        word = word.strip(".-'")
        if len(word) >= 4 and word not in GENERIC and not word.isdigit():
            out.add(word)
    for user in usernames:
        u = norm(user).lstrip("@").strip()
        if len(u) >= 4:
            out.add(u)
    return out


async def _all_terms() -> Dict[str, Set[str]]:
    global _CACHE
    if time.time() - _CACHE[0] < CACHE_SECONDS and _CACHE[1]:
        return _CACHE[1]
    clients = await sb_select("clients", select="id,name", limit=500)
    try:
        conns = await sb_select("meta_connections", select="client_id,username", limit=2000,
                                filters={"platform": "eq.instagram", "connection_type": "eq.organic"})
    except Exception:  # noqa: BLE001
        conns = []
    users: Dict[str, List[str]] = {}
    for c in conns:
        if c.get("username"):
            users.setdefault(str(c.get("client_id")), []).append(str(c["username"]))
    terms = {str(c["id"]): terms_for(str(c.get("name") or ""), users.get(str(c["id"]), [])) for c in clients if c.get("id")}
    _CACHE = (time.time(), terms)
    return terms


def forbidden_for(client_id: str, all_terms: Dict[str, Set[str]]) -> List[str]:
    own = all_terms.get(client_id, set())
    out: Set[str] = set()
    for cid, terms in all_terms.items():
        if cid == client_id:
            continue
        out |= terms
    return sorted(t for t in out - own if t not in NEUTRAL and norm(t) not in NEUTRAL)


async def leak_terms(client_id: str) -> List[str]:
    """Termos que NÃO podem aparecer em textos desta marca. Nunca levanta."""
    try:
        return forbidden_for(client_id, await _all_terms())
    except Exception as exc:  # noqa: BLE001 — auditoria é complemento; sem cadastro, segue sem ela
        print(f"[tenant_guard] terms_unavailable client_id={client_id} error_type={exc.__class__.__name__}")
        return []


def find_leaks(text: str, terms: Iterable[str]) -> List[str]:
    """Quais termos de outras marcas aparecem no texto (palavra inteira, sem acento/maiúscula)."""
    low = norm(text)
    found = []
    for term in terms:
        if re.search(rf"(?<![a-z0-9_.]){re.escape(term)}(?![a-z0-9_])", low):
            found.append(term)
    return sorted(set(found))


async def leaks_in(client_id: str, text: str) -> List[str]:
    return find_leaks(text, await leak_terms(client_id))


def clear_cache() -> None:
    global _CACHE
    _CACHE = (0.0, {})
