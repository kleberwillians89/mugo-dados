"""Sinais da marca que a IA ainda não lia: o que os clientes perguntam no WhatsApp e o retorno que o próprio
cliente da Mugô deixa no uso (ajustes pedidos, comentários, reescritas, aprovações).

Tudo aqui é determinístico (sem IA) e nunca levanta: serve o pacote de inteligência (todos os prompts) e o
"Aprender com o uso" (brand_learning), que é quem chama a IA — só no clique.

Privacidade: texto com cara de telefone, e-mail, CPF/CNPJ sai inteiro (``clean_text``); nada de nome, número
ou conversa identificável vai para a IA. Sempre filtrado por ``client_id``.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .ig_supabase import sb_select

WHATSAPP_DAYS = 30
MAX_QUESTIONS = 12
_QUESTION_START = re.compile(
    r"^(quanto|quantos|quantas|qual|quais|como|tem|t[eê]m|voc[eê]s|onde|quando|aceita|aceitam|entrega|entregam|faz|fazem|"
    r"posso|consigo|existe|ainda|vende|vendem|funciona|serve|d[aá] pra|da para|qual o|qual a|pode)\b", re.IGNORECASE)
_GREETING = re.compile(r"^(oi+|ol[aá]|bom dia|boa tarde|boa noite|ok|obrigad[oa]|valeu|sim|n[aã]o|tudo bem)[!.?\s]*$", re.IGNORECASE)
_STOP = set("""a o e é de da do das dos em no na nos nas um uma uns umas para pra por com sem que qual quais quem como quando
onde porque se ao aos à às ou mais menos muito pouco já não sim isso isto esse essa este esta ele ela eu você vocês voces
nós me te lhe meu minha seu sua tem ter foi ser são está estão sobre oi olá ola bom boa dia tarde noite obrigado obrigada
quero queria gostaria saber pode posso vou vai ok tudo bem aqui ai aí lá mas então entao tá ta pois favor por""".split())


def _clean(value: Any, limit: int) -> str:
    from .studio_intelligence import clean_text
    return clean_text(value, limit)


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")


def is_question(text: str) -> bool:
    text = (text or "").strip()
    if len(text) < 8 or _GREETING.match(text):
        return False
    return "?" in text or bool(_QUESTION_START.match(text))


def summarize_whatsapp(rows: List[Dict[str, Any]], *, days: int = WHATSAPP_DAYS) -> Dict[str, Any]:
    """Mensagens recebidas → perguntas recentes (sem repetir) e assuntos mais citados. Sem dado de pessoa."""
    texts = [str(r.get("text") or "") for r in rows if str(r.get("text") or "").strip()]
    if not texts:
        return {}
    questions: List[str] = []
    seen: set = set()
    words: Counter = Counter()
    for raw in texts:
        text = _clean(raw, 220)
        if not text:
            continue
        for word in re.findall(r"[a-zà-ÿ]{4,}", text.lower()):
            if word not in _STOP:
                words[word] += 1
        if is_question(text):
            key = re.sub(r"[^a-z0-9 ]", "", _fold(text))[:80]
            if key and key not in seen:
                seen.add(key)
                questions.append(text)
    threads = {r.get("thread_id") for r in rows if r.get("thread_id")}
    out: Dict[str, Any] = {"dias": days, "mensagens_recebidas": len(texts), "conversas": len(threads)}
    if questions:
        out["perguntas_recentes"] = questions[:MAX_QUESTIONS]
    common = [w for w, n in words.most_common(10) if n >= 2]
    if common:
        out["assuntos_mais_citados"] = common[:8]
    return out


async def whatsapp_inbound(client_id: str, *, days: int = WHATSAPP_DAYS, limit: int = 400) -> List[Dict[str, Any]]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        return await sb_select("whatsapp_messages", select="text,thread_id,sent_at", order="sent_at.desc", limit=limit,
                               filters={"client_id": f"eq.{client_id}", "direction": "eq.in", "sent_at": f"gte.{since}",
                                        "text": "not.is.null"})
    except Exception as exc:  # noqa: BLE001 — WhatsApp não conectado ou tabela indisponível: segue sem
        print(f"[brand_signals] whatsapp client_id={client_id} status=unavailable error_type={exc.__class__.__name__}")
        return []


async def whatsapp_section(client_id: str) -> Dict[str, Any]:
    """Seção ``whatsapp`` do pacote de inteligência: o que os clientes perguntam (e como), sem quem perguntou."""
    return summarize_whatsapp(await whatsapp_inbound(client_id))


# ---------------------------------------------------------------- sinais de uso (para aprender)

LEARNING_PREFIX = "Aprendido com o uso"


async def last_learning_at(client_id: str) -> Optional[str]:
    """Quando a equipe confirmou aprendizados pela última vez (registro em brand_documents, sem tabela nova)."""
    try:
        rows = await sb_select("brand_documents", select="created_at", order="created_at.desc", limit=1,
                               filters={"client_id": f"eq.{client_id}", "name": f"like.{LEARNING_PREFIX}*"})
    except Exception:  # noqa: BLE001
        return None
    return str(rows[0]["created_at"]) if rows and rows[0].get("created_at") else None


async def _safe_select(table: str, **kwargs: Any) -> List[Dict[str, Any]]:
    try:
        return await sb_select(table, **kwargs)
    except Exception as exc:  # noqa: BLE001 — uma fonte fora não derruba as outras
        print(f"[brand_signals] fonte={table} status=unavailable error_type={exc.__class__.__name__}")
        return []


async def usage_signals(client_id: str, *, since: Optional[str] = None, days: int = 90) -> Dict[str, Any]:
    """Retorno do cliente desde o último aprendizado (ou ``days`` dias): o que a IA pode virar fato da marca."""
    from .studio_calendar import ITEMS_TABLE
    from .studio_comments import COMMENTS
    from .studio_team import EVENTS
    floor = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    start = max(since, floor) if since else floor
    adjusted = await _safe_select(ITEMS_TABLE, select="title,review_note,reviewed_at", limit=30, order="reviewed_at.desc",
                                  filters={"client_id": f"eq.{client_id}", "status": "eq.rejeitado", "reviewed_at": f"gte.{start}",
                                           "review_note": "not.is.null"})
    approved = await _safe_select(ITEMS_TABLE, select="title,pillar,hook,reviewed_by,reviewed_at", limit=20, order="reviewed_at.desc",
                                  filters={"client_id": f"eq.{client_id}", "status": "in.(aprovado,publicado)",
                                           "reviewed_at": f"gte.{start}", "reviewed_by": "like.cliente:*"})
    comments = await _safe_select(COMMENTS, select="body,created_at", limit=30, order="created_at.desc",
                                  filters={"client_id": f"eq.{client_id}", "author_side": "eq.cliente", "created_at": f"gte.{start}"})
    edits = await _safe_select(EVENTS, select="payload,created_at", limit=20, order="created_at.desc",
                               filters={"client_id": f"eq.{client_id}", "action": "eq.editado_pelo_cliente", "created_at": f"gte.{start}"})
    rewrites = []
    for row in edits:
        for field, change in ((row.get("payload") or {}).get("edits") or {}).items():
            if isinstance(change, dict) and _clean(change.get("depois"), 300):
                rewrites.append({"campo": field, "antes": _clean(change.get("antes"), 300), "depois": _clean(change.get("depois"), 300)})
    whatsapp = summarize_whatsapp(await whatsapp_inbound(client_id, days=min(days, 60)))
    return {
        "desde": start,
        "ajustes_pedidos": [{"pauta": _clean(r.get("title"), 160), "pedido": _clean(r.get("review_note"), 300)}
                            for r in adjusted if _clean(r.get("review_note"), 300)][:20],
        "comentarios_do_cliente": [c for c in (_clean(r.get("body"), 300) for r in comments) if c][:20],
        "textos_reescritos_pelo_cliente": rewrites[:12],
        "aprovados_pelo_cliente": [{"pauta": _clean(r.get("title"), 160), "pilar": _clean(r.get("pillar"), 80),
                                    "gancho": _clean(r.get("hook"), 200)} for r in approved][:12],
        "whatsapp": whatsapp,
        "criadores": await creator_signals(client_id, start),
        "respostas_da_equipe": await team_reply_signals(client_id, start),
        "resultados": await result_signals(client_id, start),
        "piloto_automatico": await _autopilot(client_id, start),
    }


async def _autopilot(client_id: str, start: str) -> Dict[str, Any]:
    try:
        from .autopilot_signals import signals
        return await signals(client_id, start)
    except Exception:  # noqa: BLE001 — sem esses sinais o aprendizado segue com os outros
        return {}


async def creator_signals(client_id: str, start: str) -> List[Dict[str, Any]]:
    """Criadores que fecharam ou não fecharam desde ``start``: perfil, porte, o que foi feito e o motivo."""
    kits = await _safe_select("creator_media_kits", select="creator_id,status,status_note,status_at,deals", limit=40,
                              order="status_at.desc", filters={"client_id": f"eq.{client_id}", "status": "in.(fechado,nao_fechou)",
                                                               "status_at": f"gte.{start}"})
    ids = [str(k["creator_id"]) for k in kits if k.get("creator_id")]
    creators = await _safe_select("creators", select="id,handle,followers,biography", limit=40,
                                  filters={"id": f"in.({','.join(ids)})"}) if ids else []
    by_id = {str(c["id"]): c for c in creators}
    out = []
    for kit in kits:
        c = by_id.get(str(kit.get("creator_id")))
        if not c:
            continue
        deal = next(iter(kit.get("deals") or []), {}) or {}
        out.append({"criador": f"@{c.get('handle')}", "seguidores": c.get("followers"), "bio": _clean(c.get("biography"), 140),
                    "resultado": "fechou" if kit.get("status") == "fechado" else "nao_fechou",
                    "entrega": _clean(deal.get("what"), 100), "valor": deal.get("amount"), "motivo": _clean(kit.get("status_note"), 200)})
    return out[:20]


async def team_reply_signals(client_id: str, start: str) -> Dict[str, Any]:
    """Como a equipe responde de verdade: respostas manuais no Instagram e no WhatsApp, e correções da sugestão da IA."""
    ig = await _safe_select("ig_engagement_actions", select="text,created_at", limit=20, order="created_at.desc",
                            filters={"client_id": f"eq.{client_id}", "kind": "eq.resposta_manual", "status": "eq.enviado",
                                     "created_at": f"gte.{start}"})
    # Comentário respondido a partir da sugestão da IA, com o texto mudado pela equipe (coluna da migração 000147).
    ig_fixed = await _safe_select("ig_engagement_actions", select="text,ai_original,created_at", limit=20, order="created_at.desc",
                                  filters={"client_id": f"eq.{client_id}", "status": "eq.enviado", "ai_original": "not.is.null",
                                           "created_at": f"gte.{start}"})
    # Direct do Instagram: o que a equipe escreveu à mão na caixa de entrada.
    dm = await _safe_select("ig_dm_messages", select="text,created_at", limit=20, order="created_at.desc",
                            filters={"client_id": f"eq.{client_id}", "direction": "eq.out", "by_app": "eq.false",
                                     "created_at": f"gte.{start}"})
    wa = await _safe_select("whatsapp_messages", select="text,payload,created_at", limit=40, order="created_at.desc",
                            filters={"client_id": f"eq.{client_id}", "direction": "eq.out", "by_ai": "eq.false",
                                     "type": "eq.text", "created_at": f"gte.{start}"})
    # Sugestão da IA aprovada com texto mudado sai como by_ai=true, com o original guardado no payload.
    fixed = await _safe_select("whatsapp_messages", select="text,payload,created_at", limit=20, order="created_at.desc",
                               filters={"client_id": f"eq.{client_id}", "direction": "eq.out", "payload->>ai_original": "not.is.null",
                                        "created_at": f"gte.{start}"})
    corrections = [{"canal": "comentario", "ia_sugeriu": _clean(r.get("ai_original"), 300), "equipe_enviou": _clean(r.get("text"), 300)}
                   for r in ig_fixed if _clean(r.get("ai_original"), 300) and _clean(r.get("text"), 300)]
    for row in fixed:
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        original, text = _clean(payload.get("ai_original"), 300), _clean(row.get("text"), 300)
        if original and text:
            corrections.append({"canal": "whatsapp", "ia_sugeriu": original, "equipe_enviou": text})
    manual = [t for t in (_clean(r.get("text"), 300) for r in wa) if t]
    return {"instagram": [t for t in (_clean(r.get("text"), 200) for r in ig) if t][:12],
            "direct": [t for t in (_clean(r.get("text"), 200) for r in dm) if t][:12],
            "whatsapp": manual[:12], "correcoes_da_ia": corrections[:16]}


async def result_signals(client_id: str, start: str) -> Dict[str, Any]:
    """Contexto de resultado (não conta como sinal novo): posts que mais alcançaram e metas encerradas no período."""
    out: Dict[str, Any] = {}
    try:
        from .studio_calendar import top_posts
        out["posts_que_mais_alcancaram"] = (await top_posts(client_id, days=60))[:5]
    except Exception:  # noqa: BLE001
        pass
    try:
        from .goals import list_goals
        today = datetime.now(timezone.utc).date()
        goals = (await list_goals(client_id, start[:10], today.isoformat())).get("goals") or []
        out["metas"] = [{"meta": _clean(g.get("label"), 100), "status": g.get("status"),
                         "progresso_pct": round(g["progress_percent"]) if isinstance(g.get("progress_percent"), (int, float)) else None}
                        for g in goals if g.get("status") in ("META_ATINGIDA", "ABAIXO_DO_RITMO", "ATENCAO")][:8]
    except Exception:  # noqa: BLE001
        pass
    return {k: v for k, v in out.items() if v}


def count_signals(signals: Dict[str, Any]) -> int:
    wa = signals.get("whatsapp") or {}
    team = signals.get("respostas_da_equipe") or {}
    from .autopilot_signals import count as autopilot_count
    return (autopilot_count(signals.get("piloto_automatico") or {}) + len(signals.get("criadores") or []) + len(team.get("instagram") or []) + len(team.get("whatsapp") or [])
            + len(team.get("correcoes_da_ia") or []) + len(team.get("direct") or []) + len(signals.get("ajustes_pedidos") or []) + len(signals.get("comentarios_do_cliente") or [])
            + len(signals.get("textos_reescritos_pelo_cliente") or []) + len(signals.get("aprovados_pelo_cliente") or [])
            + len(wa.get("perguntas_recentes") or []))
