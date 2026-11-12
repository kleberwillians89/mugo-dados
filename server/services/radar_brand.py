"""Radar Cultural por marca: das tendências públicas do Brasil, só o que conversa com ESTA marca.

O feed do Google Trends é o mesmo para todo mundo; mostrar a lista crua deixava todas as marcas com o mesmo
radar. Aqui cada marca recebe a própria seleção, com o porquê e uma ideia de pauta:
- com IA: a IA lê o segmento, o público, os termos do Clipping e escolhe os assuntos ligados à marca;
- sem IA: casa os assuntos com os termos da marca (marca, temas, palavras-chave, concorrentes, segmento).
Nenhum assunto entra só por estar em alta. Sem ligação, a lista vem vazia e a tela diz isso."""
from __future__ import annotations

import hashlib
import re
import time
import unicodedata
from typing import Any, Dict, List, Tuple

CACHE_SECONDS = 6 * 3600
MAX_ITEMS = 8
_cache: Dict[Tuple[str, str], Tuple[float, Dict[str, Any]]] = {}

INSTRUCTIONS = (
    "Você é estrategista de conteúdo de uma agência no Brasil. Recebe os assuntos em alta no Brasil hoje e o perfil "
    "de UMA marca. Escolha só os assuntos que têm ligação real com a marca: categoria, público, momento de consumo, "
    "datas, cultura que o público dela vive. Ignore política, tragédia, crime e assuntos sem ligação. Melhor devolver "
    "poucos (ou nenhum) do que forçar. Para cada escolhido: why = uma frase de por que importa para esta marca; "
    "idea = uma ideia de pauta ou ação concreta e curta."
)


def _norm(text: Any) -> str:
    raw = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", raw)).strip()


def match_terms(trends: List[Dict[str, Any]], terms: List[str]) -> List[Dict[str, Any]]:
    words = {t for t in (_norm(x) for x in terms) if len(t) >= 4}
    out = []
    for item in trends:
        hay = f" {_norm(item.get('topic'))} {_norm(item.get('news_title'))} "
        hit = next((w for w in words if f" {w} " in hay), None)
        if hit:
            out.append({**item, "why": f"Cita “{hit}”, um dos termos da marca.", "idea": None})
    return out[:MAX_ITEMS]


async def brand_profile(client_id: str) -> Tuple[str, List[str]]:
    from .business_context import load_business_context
    from .studio_clipping import get_settings
    lines, terms = [], []
    try:
        ctx = (await load_business_context(client_id)).get("context") or {}
        lines += [f"{k}: {str(v)[:600]}" for k, v in ctx.items() if v and isinstance(v, str)]
        if ctx.get("segment"):
            terms += re.split(r"[,;/]| e ", str(ctx["segment"]))
    except Exception:  # noqa: BLE001
        pass
    try:
        s = await get_settings(client_id)
        for key, label in (("brand_terms", "Marca"), ("themes", "Temas"), ("keywords", "Palavras-chave"), ("competitor_terms", "Concorrentes")):
            if s.get(key):
                lines.append(f"{label}: {', '.join(s[key][:20])}")
                terms += list(s[key])
    except Exception:  # noqa: BLE001
        pass
    return "\n".join(lines), [t.strip() for t in terms if t and t.strip()]


async def brand_trends(client_id: str, trends: Dict[str, Any]) -> Dict[str, Any]:
    items = [i for i in (trends.get("items") or []) if isinstance(i, dict) and i.get("id")]
    if not items:
        return {"status": trends.get("status") or "unavailable", "items": [], "method": None, "public_count": 0}
    key = (client_id, hashlib.sha1("|".join(f"{i['id']}={i.get('topic')}" for i in items).encode()).hexdigest())
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    profile, terms = await brand_profile(client_id)
    result: Dict[str, Any]
    try:
        if not profile:
            raise RuntimeError("sem perfil da marca")
        from .studio_llm import STR, arr, obj, llm_json
        listing = "\n".join(f"{i['id']}: {i.get('topic')}" + (f" — {i['news_title']}" if i.get("news_title") else "") for i in items[:30])
        data = await llm_json(client_id=client_id, instructions=INSTRUCTIONS, prompt=f"MARCA:\n{profile}\n\nEM ALTA NO BRASIL HOJE:\n{listing}",
                              schema_name="radar_brand_trends", schema=obj({"picks": arr(obj({"id": STR, "why": STR, "idea": STR}))}),
                              temperature=0.2, timeout=45)
        by_id = {str(i["id"]): i for i in items}
        picked = []
        for p in data.get("picks") or []:
            trend = by_id.get(str(p.get("id")))
            if trend and all(trend["id"] != x["id"] for x in picked):
                picked.append({**trend, "why": str(p.get("why") or "")[:240], "idea": str(p.get("idea") or "")[:240] or None})
        result = {"status": "ok", "items": picked[:MAX_ITEMS], "method": "ia", "public_count": len(items)}
    except Exception as exc:  # noqa: BLE001 — sem IA: só o que casa com os termos da marca
        print(f"[radar][brand] client_id={client_id} ai=unavailable {getattr(exc, 'code', type(exc).__name__)}")
        result = {"status": "ok", "items": match_terms(items, terms), "method": "termos", "public_count": len(items)}
    _cache[key] = (time.monotonic(), result)
    return result
