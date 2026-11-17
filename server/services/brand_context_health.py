"""Saúde do Contexto da Marca: o que falta ou está velho para a IA trabalhar bem com esta marca.

Só leitura e regras fixas (sem IA, sem custo). Cada item diz o problema, por que importa e onde resolver.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .ig_supabase import sb_select

STALE_DAYS = 180
LEARN_AFTER = 3   # sinais novos a partir dos quais vale buscar aprendizados


def _item(item_id: str, level: str, title: str, detail: str, action: Optional[Dict[str, str]] = None, weight: int = 1) -> Dict[str, Any]:
    return {"id": item_id, "level": level, "title": title, "detail": detail, "action": action, "weight": weight}


def _age_days(iso: Optional[str], now: datetime) -> Optional[int]:
    if not iso:
        return None
    try:
        when = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0, (now - when).days)


def evaluate(*, profile: Dict[str, Any], profile_saved: bool, business: Dict[str, Any], knowledge: str, knowledge_max: int,
             documents: List[Dict[str, Any]], competitors: int, new_signals: int, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Regras puras (testáveis). Devolve itens e um índice 0–100 de completude."""
    now = now or datetime.now(timezone.utc)
    items: List[Dict[str, Any]] = []
    identity = {"tab": "identidade"}
    docs_tab = {"tab": "documentos"}

    missing = [label for key, label in (("tone_of_voice", "tom de voz"), ("audience", "público"), ("personality", "personalidade"))
               if not str(profile.get(key) or "").strip()]
    if not profile_saved or missing or not profile.get("pillars"):
        parts = (["pilares"] if not profile.get("pillars") else []) + missing
        items.append(_item("perfil", "falta", "Perfil da marca incompleto",
                           f"Falta: {', '.join(parts) if parts else 'salvar o perfil'}. Sem isso a IA escreve genérico.", identity, 3))
    else:
        items.append(_item("perfil", "ok", "Perfil da marca preenchido", "Tom, público, personalidade e pilares definidos.", None, 3))
    total = sum(int(p.get("weight") or 0) for p in profile.get("pillars") or [])
    if profile.get("pillars") and total != 100:
        items.append(_item("pesos", "atencao", "Pesos dos pilares não fecham 100%",
                           f"Somam {total}%. O calendário distribui as pautas por esses pesos.", identity, 1))

    filled = sum(1 for v in business.values() if str(v or "").strip())
    if filled < 4:
        items.append(_item("negocio", "falta" if filled == 0 else "atencao", "Contexto estratégico incompleto",
                           f"{filled} de 8 campos preenchidos (segmento, produtos, público, posicionamento, diferenciais, objetivos…).",
                           identity, 2))
    else:
        items.append(_item("negocio", "ok", "Contexto estratégico preenchido", f"{filled} de 8 campos.", None, 2))

    sources = [d for d in documents if d.get("kind") != "conversa"]
    failed = [d for d in documents if d.get("status") == "falhou"]
    if not sources:
        items.append(_item("documentos", "falta", "Nenhum documento da marca",
                           "Envie o planejamento, o brand book ou a apresentação: é a principal fonte da IA.", docs_tab, 3))
    else:
        newest = min((a for a in (_age_days(d.get("created_at"), now) for d in sources) if a is not None), default=None)
        if newest is not None and newest > STALE_DAYS:
            items.append(_item("documentos", "atencao", "Material da marca desatualizado",
                               f"O documento mais recente tem {newest} dias. Envie o planejamento atual e importe o que mudou.", docs_tab, 3))
        else:
            items.append(_item("documentos", "ok", "Documentos da marca em dia", f"{len(sources)} documento(s) enviado(s).", None, 3))
    if failed:
        items.append(_item("falhas", "atencao", f"{len(failed)} documento(s) guardado(s) que a IA ainda não leu",
                           "Use “Tentar de novo” na lista de documentos.", docs_tab, 1))

    if not knowledge.strip():
        items.append(_item("memoria", "falta", "A memória da marca está vazia", "Ela vai em todos os prompts. Envie um documento ou ensine um texto.", docs_tab, 2))
    elif len(knowledge) >= knowledge_max * 0.9:
        items.append(_item("memoria", "atencao", "Memória da marca quase cheia",
                           "A IA resume o menos útil para caber o novo. Revise e corte o que não vale mais.", docs_tab, 1))
    else:
        items.append(_item("memoria", "ok", "Memória da marca ativa", f"{len(knowledge)} de {knowledge_max} caracteres.", None, 2))

    if competitors == 0:
        items.append(_item("concorrentes", "atencao", "Nenhum concorrente cadastrado",
                           "Sem concorrentes, a IA não compara nem monitora o mercado. Importe do planejamento ou cadastre no Benchmarking.",
                           {"route": "benchmark"}, 1))
    else:
        items.append(_item("concorrentes", "ok", "Concorrentes cadastrados", f"{competitors} concorrente(s).", None, 1))

    if new_signals >= LEARN_AFTER:
        items.append(_item("aprender", "atencao", f"{new_signals} sinais novos para a IA aprender",
                           "Ajustes, comentários, reescritas e perguntas do WhatsApp desde o último aprendizado.", docs_tab, 1))

    weights = {}
    for it in items:  # um peso por tema: o pior estado do tema conta
        rank = {"ok": 1.0, "atencao": 0.5, "falta": 0.0}[it["level"]]
        weights[it["id"]] = (min(rank, weights.get(it["id"], (1.0, 0))[0]), it["weight"])
    total_weight = sum(w for _, w in weights.values()) or 1
    score = round(sum(r * w for r, w in weights.values()) / total_weight * 100)
    order = {"falta": 0, "atencao": 1, "ok": 2}
    items.sort(key=lambda i: (order[i["level"]], -i["weight"]))
    return {"score": score, "items": [{k: v for k, v in i.items() if k != "weight"} for i in items]}


async def _competitor_count(client_id: str) -> int:
    names = set()
    try:
        rows = await sb_select("benchmark_competitors", select="name", limit=50, filters={"client_id": f"eq.{client_id}", "active": "is.true"})
        names |= {str(r.get("name") or "").lower() for r in rows if r.get("name")}
    except Exception:  # noqa: BLE001
        pass
    try:
        rows = await sb_select("studio_clipping_settings", select="competitor_terms", limit=1, filters={"client_id": f"eq.{client_id}"})
        names |= {str(t).lower() for t in ((rows[0].get("competitor_terms") if rows else None) or []) if t}
    except Exception:  # noqa: BLE001
        pass
    return len(names)


async def health(client_id: str) -> Dict[str, Any]:
    from .brand_knowledge import MAX_KNOWLEDGE, list_documents, load_knowledge
    from .brand_learning import status as learning_status
    from .business_context import load_business_context
    from .studio_calendar import load_profile
    profile = await load_profile(client_id)
    business = (await load_business_context(client_id)).get("context") or {}
    knowledge = (await load_knowledge(client_id))["knowledge"]
    documents = await list_documents(client_id)
    try:
        learning = await learning_status(client_id)
    except Exception:  # noqa: BLE001
        learning = {"new_signals": 0, "last_learning_at": None}
    result = evaluate(profile=profile["profile"], profile_saved=bool(profile.get("saved")), business=business, knowledge=knowledge,
                      knowledge_max=MAX_KNOWLEDGE, documents=documents, competitors=await _competitor_count(client_id),
                      new_signals=int(learning.get("new_signals") or 0))
    return {**result, "learning": learning}
