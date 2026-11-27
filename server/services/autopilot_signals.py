"""Aprender com o piloto automático: o que acontece DEPOIS que a IA responde sozinha.

Com a resposta automática ligada, ninguém edita a resposta da IA antes de sair, então o "antes e depois" não existe.
O sinal vem do que acontece em seguida:

1. a equipe assumiu: a IA respondeu e logo depois alguém da equipe respondeu por cima (WhatsApp, Direct, comentários);
   o par "IA disse → equipe disse depois" é o sinal mais forte de resposta errada;
2. a IA pediu ajuda: os motivos dos handoffs (WhatsApp) e das conversas que ela deixou para revisão (Direct);
3. resultado da conversa no WhatsApp: fase que a própria ficha marcou (comprou, perdida) e as objeções;
4. amostra com 👍👎: respostas automáticas sorteadas para a equipe avaliar; o 👎 com motivo vira sinal
   (tabela ``ai_reply_reviews``, migração 000148).

Tudo é lido sem IA e nunca levanta: tabela ausente vira lista vazia.
"""
from __future__ import annotations

import random
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .ig_supabase import sb_insert, sb_select

REVIEWS = "ai_reply_reviews"
TAKEOVER_WINDOW = timedelta(hours=24)
SAMPLE_DAYS = 7
SAMPLE_SIZE = 5
CHANNELS = ("whatsapp", "direct", "comentario")
CHANNEL_LABEL = {"whatsapp": "WhatsApp", "direct": "Direct", "comentario": "Comentário"}


def _clean(value: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _ts(value: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


async def _safe(table: str, **kwargs: Any) -> List[Dict[str, Any]]:
    try:
        return await sb_select(table, **kwargs) or []
    except Exception as exc:  # noqa: BLE001
        print(f"[autopilot_signals] read_failed table={table} error_type={type(exc).__name__}")
        return []


def takeovers_in(rows: List[Dict[str, Any]], *, key: str, is_ai, is_team) -> List[Dict[str, str]]:
    """Pares "cliente perguntou → IA respondeu → equipe respondeu por cima" numa lista de mensagens. Puro, para teste.

    ``rows`` em ordem cronológica; ``key`` separa as conversas; ``is_ai``/``is_team`` classificam a mensagem de saída."""
    by_thread: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        by_thread.setdefault(str(row.get(key)), []).append(row)
    out = []
    for msgs in by_thread.values():
        last_in: Optional[Dict[str, Any]] = None
        last_ai: Optional[Dict[str, Any]] = None
        answered: Optional[Dict[str, Any]] = None  # a mensagem do cliente que a IA respondeu
        for msg in msgs:
            if msg.get("direction") == "in":
                last_in = msg
                continue
            if is_ai(msg):
                last_ai, answered = msg, last_in
                continue
            if is_team(msg) and last_ai:
                gap = (_ts(msg.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc)) - \
                      (_ts(last_ai.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc))
                if gap <= TAKEOVER_WINDOW and _clean(msg.get("text"), 300):
                    out.append({"cliente": _clean((answered or {}).get("text"), 200), "ia_disse": _clean(last_ai.get("text"), 300),
                                "equipe_disse_depois": _clean(msg.get("text"), 300)})
                last_ai = None
    return out


async def takeovers(client_id: str, start: str) -> List[Dict[str, str]]:
    wa = await _safe("whatsapp_messages", select="thread_id,direction,by_ai,text,created_at", order="created_at.asc", limit=800,
                     filters={"client_id": f"eq.{client_id}", "created_at": f"gte.{start}"})
    dm = await _safe("ig_dm_messages", select="sender_id,direction,by_app,text,created_at", order="created_at.asc", limit=800,
                     filters={"client_id": f"eq.{client_id}", "created_at": f"gte.{start}"})
    out = [{"canal": "whatsapp", **p} for p in takeovers_in(wa, key="thread_id", is_ai=lambda m: bool(m.get("by_ai")),
                                                              is_team=lambda m: m.get("by_ai") is False)]
    out += [{"canal": "direct", **p} for p in takeovers_in(dm, key="sender_id", is_ai=lambda m: bool(m.get("by_app")),
                                                             is_team=lambda m: m.get("by_app") is False)]
    # Comentários: a IA respondeu sozinha e a equipe respondeu de novo no mesmo comentário.
    acts = await _safe("ig_engagement_actions", select="comment_id,kind,status,text,created_at", order="created_at.asc", limit=400,
                       filters={"client_id": f"eq.{client_id}", "status": "eq.enviado", "created_at": f"gte.{start}",
                                "kind": "in.(resposta_ia,resposta_manual)"})
    rows = [{**a, "direction": "out"} for a in acts]
    out += [{"canal": "comentario", **p} for p in takeovers_in(rows, key="comment_id", is_ai=lambda m: m.get("kind") == "resposta_ia",
                                                                 is_team=lambda m: m.get("kind") == "resposta_manual")]
    return out[:15]


async def handoffs(client_id: str, start: str) -> List[str]:
    """Por que a IA parou e passou para a equipe (sem nomes nem telefones)."""
    threads = await _safe("whatsapp_threads", select="ai_handoff_reason,ai_updated_at", limit=200, order="ai_updated_at.desc",
                          filters={"client_id": f"eq.{client_id}", "ai_handoff_reason": "not.is.null", "ai_updated_at": f"gte.{start}"})
    dms = await _safe("ig_dm_messages", select="error,created_at", limit=200, order="created_at.desc",
                      filters={"client_id": f"eq.{client_id}", "direction": "eq.in", "status": "eq.revisao", "created_at": f"gte.{start}"})
    reasons = [_clean(t.get("ai_handoff_reason"), 160) for t in threads] + [_clean(d.get("error"), 160) for d in dms]
    reasons = [r for r in reasons if r and r.lower() not in ("pausada pela equipe", "equipe")]
    counts: Dict[str, int] = {}
    for r in reasons:
        counts[r] = counts.get(r, 0) + 1
    return [f"{r} ({n}x)" if n > 1 else r for r, n in sorted(counts.items(), key=lambda kv: -kv[1])][:15]


async def outcomes(client_id: str, start: str) -> Dict[str, Any]:
    """Resultado das conversas do WhatsApp no período, pela ficha que a IA mantém (fase e objeções)."""
    rows = await _safe("whatsapp_threads", select="ai_stage,ai_objections,ai_updated_at", limit=500,
                       filters={"client_id": f"eq.{client_id}", "ai_updated_at": f"gte.{start}", "ai_stage": "not.is.null"})
    stages: Dict[str, int] = {}
    objections: Dict[str, int] = {}
    for r in rows:
        stage = str(r.get("ai_stage") or "")
        stages[stage] = stages.get(stage, 0) + 1
        if stage in ("perdida", "negociando"):
            for o in r.get("ai_objections") or []:
                text = _clean(o, 80).lower()
                if text:
                    objections[text] = objections.get(text, 0) + 1
    if not stages:
        return {}
    return {"fases": stages, "objecoes_mais_comuns": [k for k, _ in sorted(objections.items(), key=lambda kv: -kv[1])][:8]}


async def review_signals(client_id: str, start: str) -> List[Dict[str, str]]:
    rows = await _safe(REVIEWS, select="channel,customer_text,ai_text,rating,reason,created_at", limit=40, order="created_at.desc",
                       filters={"client_id": f"eq.{client_id}", "created_at": f"gte.{start}"})
    return [{"canal": r.get("channel"), "nota": "👍" if r.get("rating") == "up" else "👎", "cliente": _clean(r.get("customer_text"), 200),
             "ia_disse": _clean(r.get("ai_text"), 300), "motivo": _clean(r.get("reason"), 200)} for r in rows][:20]


async def signals(client_id: str, start: str) -> Dict[str, Any]:
    out = {"equipe_assumiu": await takeovers(client_id, start), "ia_pediu_ajuda": await handoffs(client_id, start),
           "avaliacoes_da_equipe": await review_signals(client_id, start), "resultado_das_conversas": await outcomes(client_id, start)}
    return {k: v for k, v in out.items() if v}


def count(section: Dict[str, Any]) -> int:
    """O que conta como sinal novo: assumidas, pedidos de ajuda e avaliações (o resultado é contexto)."""
    section = section or {}
    return len(section.get("equipe_assumiu") or []) + len(section.get("ia_pediu_ajuda") or []) + len(section.get("avaliacoes_da_equipe") or [])


# ------------------------------------------------------------------ amostra semanal com 👍👎

async def _reviewed_refs(client_id: str) -> set:
    rows = await _safe(REVIEWS, select="ref_id", limit=500, order="created_at.desc", filters={"client_id": f"eq.{client_id}"})
    return {str(r.get("ref_id")) for r in rows}


async def sample(client_id: str, *, size: int = SAMPLE_SIZE, seed: Optional[int] = None) -> List[Dict[str, Any]]:
    """Respostas que a IA mandou sozinha nos últimos dias, ainda sem avaliação, com a mensagem que ela respondeu."""
    since = (datetime.now(timezone.utc) - timedelta(days=SAMPLE_DAYS)).isoformat()
    done = await _reviewed_refs(client_id)
    pool: List[Dict[str, Any]] = []
    wa = await _safe("whatsapp_messages", select="id,thread_id,direction,by_ai,type,text,created_at", order="created_at.asc", limit=600,
                     filters={"client_id": f"eq.{client_id}", "created_at": f"gte.{since}"})
    dm = await _safe("ig_dm_messages", select="id,sender_id,direction,by_app,text,created_at", order="created_at.asc", limit=600,
                     filters={"client_id": f"eq.{client_id}", "created_at": f"gte.{since}"})
    for channel, rows, key, is_ai in (("whatsapp", wa, "thread_id", lambda m: bool(m.get("by_ai")) and m.get("type", "text") == "text"),
                                      ("direct", dm, "sender_id", lambda m: bool(m.get("by_app")))):
        last_in: Dict[str, str] = {}
        for m in rows:
            k = str(m.get(key))
            if m.get("direction") == "in":
                last_in[k] = _clean(m.get("text"), 300)
            elif is_ai(m) and _clean(m.get("text"), 10) and str(m.get("id")) not in done and last_in.get(k):
                pool.append({"channel": channel, "ref_id": str(m["id"]), "customer_text": last_in[k], "ai_text": _clean(m.get("text"), 600)})
    acts = await _safe("ig_engagement_actions", select="id,comment_id,text,created_at", limit=200, order="created_at.desc",
                       filters={"client_id": f"eq.{client_id}", "kind": "eq.resposta_ia", "status": "eq.enviado", "created_at": f"gte.{since}"})
    acts = [a for a in acts if str(a.get("id")) not in done]
    if acts:
        ids = ",".join(dict.fromkeys(str(a["comment_id"]) for a in acts))
        comments = {str(c["comment_id"]): c for c in await _safe("ig_comments", select="comment_id,text", limit=200,
                                                                  filters={"client_id": f"eq.{client_id}", "comment_id": f"in.({ids})"})}
        for a in acts:
            text = _clean((comments.get(str(a["comment_id"])) or {}).get("text"), 300)
            if text:
                pool.append({"channel": "comentario", "ref_id": str(a["id"]), "customer_text": text, "ai_text": _clean(a.get("text"), 600)})
    rng = random.Random(seed)
    rng.shuffle(pool)
    # Equilibra os canais: um de cada antes de repetir.
    picked, seen = [], set()
    for item in pool:
        if item["channel"] not in seen:
            picked.append(item)
            seen.add(item["channel"])
    picked += [i for i in pool if i not in picked]
    return [{**i, "channel_label": CHANNEL_LABEL[i["channel"]]} for i in picked[:size]]


async def rate(client_id: str, *, channel: str, ref_id: str, customer_text: str, ai_text: str, rating: str,
               reason: Optional[str], user_id: str) -> None:
    if channel not in CHANNELS or rating not in ("up", "down"):
        raise ValueError("Avaliação inválida.")
    await sb_insert(REVIEWS, {"client_id": client_id, "channel": channel, "ref_id": str(ref_id)[:80],
                              "customer_text": _clean(customer_text, 600) or None, "ai_text": _clean(ai_text, 1000),
                              "rating": rating, "reason": _clean(reason, 300) or None, "reviewed_by": user_id},
                    returning="minimal")
