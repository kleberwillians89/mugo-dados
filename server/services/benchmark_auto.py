"""Benchmarking que já abre com concorrentes: a IA monta a lista a partir do Clipping (concorrentes que a
imprensa já cita), do contexto do negócio e da memória da marca. A equipe só confere, tira ou acrescenta.

Nada de métrica inventada: a IA só nomeia quem disputa o mesmo cliente (nome, site e @). Números vêm depois,
da coleta pública (Instagram via Meta, preços pelo site, Ad Library por link)."""
from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

from .ig_supabase import sb_insert, sb_select

TABLE = "benchmark_competitors"
AUTO_COUNT = 5
RETRY_SECONDS = 6 * 3600  # sem IA ou sem resposta útil, tenta de novo em 6 h (não a cada abertura da tela)
_attempts: Dict[str, float] = {}

INSTRUCTIONS = (
    "Você é estrategista de marketing no Brasil. Liste os concorrentes diretos da marca: quem disputa o MESMO cliente, "
    "na mesma categoria e faixa de preço, vendendo no Brasil. Priorize os concorrentes já citados no Clipping. "
    "Só marcas reais que você conhece com segurança; na dúvida, deixe de fora. Site: só o domínio oficial com https. "
    "Instagram: só o @ oficial, sem inventar; se não souber, deixe vazio. Em why, uma frase curta de por que é concorrente."
)


def _schema() -> Dict[str, Any]:
    from .studio_llm import STR, arr, obj
    return obj({"competitors": arr(obj({"name": STR, "website": STR, "instagram_handle": STR, "why": STR}))})


def clean_site(value: Any) -> Optional[str]:
    raw = str(value or "").strip()
    if not raw:
        return None
    if not raw.startswith("http"):
        raw = "https://" + raw
    parts = urlsplit(raw.replace("http://", "https://", 1))
    host = (parts.hostname or "").lower()
    if not host or "." not in host or host in {"localhost"}:
        return None
    return f"https://{host}"


def clean_handle(value: Any) -> Optional[str]:
    handle = str(value or "").strip().lstrip("@").lower()
    handle = re.sub(r"^https?://(www\.)?instagram\.com/", "", handle).strip("/")
    return handle[:30] if re.fullmatch(r"[a-z0-9._]{2,30}", handle) else None


def clean_list(raw: List[Dict[str, Any]], *, own_names: List[str], limit: int) -> List[Dict[str, Any]]:
    seen = {n.strip().lower() for n in own_names if n}
    out: List[Dict[str, Any]] = []
    for item in raw or []:
        name = re.sub(r"\s+", " ", str((item or {}).get("name") or "")).strip()[:120]
        if len(name) < 2 or name.lower() in seen:
            continue
        seen.add(name.lower())
        out.append({"name": name, "website": clean_site(item.get("website")), "instagram_handle": clean_handle(item.get("instagram_handle")),
                    "why": re.sub(r"\s+", " ", str(item.get("why") or "")).strip()[:240]})
        if len(out) >= limit:
            break
    return out


async def _prompt(client_id: str) -> tuple[str, List[str]]:
    from .business_context import load_business_context_for_ai
    from .ig_supabase import sb_get_one
    from .studio_clipping import get_settings
    client = await sb_get_one("clients", f"id=eq.{client_id}") or {}
    name = str(client.get("name") or "")
    lines = [f"Marca: {name or 'sem nome'}"]
    try:
        ctx = await load_business_context_for_ai(client_id)
        lines += [f"{k}: {str(v)[:900]}" for k, v in (ctx.get("context") or {}).items() if v and isinstance(v, (str, int, float))]
    except Exception as exc:  # noqa: BLE001
        print(f"[benchmark][auto] client_id={client_id} context=unavailable {type(exc).__name__}")
    brand_terms: List[str] = []
    try:
        settings = await get_settings(client_id)
        brand_terms = list(settings.get("brand_terms") or [])
        if settings.get("competitor_terms"):
            lines.append("Concorrentes citados no Clipping: " + ", ".join(settings["competitor_terms"][:15]))
    except Exception as exc:  # noqa: BLE001
        print(f"[benchmark][auto] client_id={client_id} clipping=unavailable {type(exc).__name__}")
    try:
        mentions = await sb_select("studio_clippings", select="term", filters={"client_id": f"eq.{client_id}", "kind": "eq.concorrente"},
                                   order="published_at.desc", limit=60)
        terms = list(dict.fromkeys(str(m.get("term")) for m in mentions if m.get("term")))
        if terms:
            lines.append("Concorrentes que apareceram nas notícias: " + ", ".join(terms[:15]))
    except Exception:  # noqa: BLE001
        pass
    lines.append(f"Liste até {AUTO_COUNT + 3} concorrentes.")
    return "\n".join(lines), [name, *brand_terms]


async def suggest(client_id: str, *, limit: int = AUTO_COUNT) -> List[Dict[str, Any]]:
    from .studio_llm import llm_json
    prompt, own = await _prompt(client_id)
    data = await llm_json(client_id=client_id, instructions=INSTRUCTIONS, prompt=prompt, schema_name="benchmark_competitors_auto",
                          schema=_schema(), temperature=0.2, timeout=60)
    return clean_list(data.get("competitors") or [], own_names=own, limit=limit)


async def ensure_competitors(client_id: str, *, force: bool = False) -> Dict[str, Any]:
    """Sem concorrente ativo, a IA cadastra até 5 (respeitando o plano). Com concorrentes, não mexe."""
    active = await sb_select(TABLE, select="id,name,active", filters={"client_id": f"eq.{client_id}"}, limit=200)
    if any(r.get("active", True) for r in active) and not force:
        return {"status": "ja_tem", "added": []}
    last = _attempts.get(client_id)
    if not force and last and time.monotonic() - last < RETRY_SECONDS:
        return {"status": "aguardando", "added": []}
    _attempts[client_id] = time.monotonic()
    from . import saas
    left = await saas.remaining(client_id, "competitors")
    limit = AUTO_COUNT if left is None else max(0, min(AUTO_COUNT, left))
    if not limit:
        return {"status": "limite_do_plano", "added": []}
    try:
        found = await suggest(client_id, limit=limit + len(active))
    except Exception as exc:  # noqa: BLE001 — sem IA agora: a tela segue com o cadastro manual
        print(f"[benchmark][auto] client_id={client_id} suggest=failed {getattr(exc, 'code', type(exc).__name__)}")
        return {"status": "sem_ia", "added": []}
    taken = {str(r.get("name") or "").lower() for r in active}  # removido pela equipe não volta sozinho
    added: List[Dict[str, Any]] = []
    for comp in found:
        if comp["name"].lower() in taken:
            continue
        row = {"client_id": client_id, "name": comp["name"], "keywords": [comp["name"]]}
        if comp.get("website"):
            row["website"] = comp["website"]
        if comp.get("instagram_handle"):
            row["instagram_handle"] = comp["instagram_handle"]
        try:
            saved = await sb_insert(TABLE, row)
        except Exception as exc:  # noqa: BLE001
            print(f"[benchmark][auto] client_id={client_id} insert=failed {type(exc).__name__}")
            continue
        if saved:
            added.append({**saved, "why": comp.get("why")})
        if len(added) >= limit:
            break
    print(f"[benchmark][auto] client_id={client_id} added={len(added)}")
    return {"status": "feito" if added else "nada_novo", "added": added}
