"""Briefing: a porta de entrada de qualquer pedido.

A pessoa (equipe ou cliente) digita o pedido. A IA lê o pedido com o contexto do cliente (perfil da marca, o que
vendeu, metas, calendário, campanhas, aprendizados de aprovações) e devolve um briefing CURTO: objetivo, mensagem,
público, prazo, entregáveis, o que não fazer e a meta que prova o resultado. Sugere para onde vai (Social Media,
Mídia On, Clipping, Redação, Criadores) e quem faz o quê.

A equipe confere e distribui com um clique por destino e cria a tarefa de cada pessoa (só com a parte dela).
Pedido aberto pelo cliente fica "aguardando equipe" até a Mugô aprovar. O cliente vê a versão curta e o andamento,
nunca o interno.
"""
from __future__ import annotations

import html
import json
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from .ig_supabase import sb_insert, sb_select, sb_update
from .studio_calendar import SAO_PAULO, StudioError, language_rule, load_profile

TABLE = "studio_briefs"
DESTINATIONS: Dict[str, str] = {"social_media": "Social Media", "midia_on": "Mídia On", "clipping": "Clipping",
                                "redacao": "Redação", "criadores": "Criadores"}
STATUSES = ("aguardando_equipe", "pronto", "distribuido", "arquivado")
CLIENT_FIELDS = ("id", "status", "request", "created_at", "created_side", "created_by_name")


def _forget(client_id: str) -> None:
    from .studio_intelligence import invalidate
    invalidate(client_id)



def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _items(value: Any, n: int, limit: int = 160) -> List[str]:
    return [t for t in (_text(v, limit) for v in (value or []) if isinstance(v, (str, int, float))) if t][:n]


def parse_brl(value: Any) -> Optional[float]:
    """'R$ 3.000', '3000', '3.000,50', '3 mil' → número (formato brasileiro)."""
    import re
    text = str(value or "").lower()
    mil = 1000 if re.search(r"\bmil\b", text) else 1
    raw = "".join(ch for ch in text if ch.isdigit() or ch in ",.")
    if not raw:
        return None
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", raw):
        raw = raw.replace(".", "")
    try:
        return float(raw) * mil
    except ValueError:
        return None


# ------------------------------------------------------------------ IA

def _schema() -> Dict[str, Any]:
    from .media_strategy import OBJECTIVES
    from .studio_briefing_send import ROLES
    from .studio_llm import STR, arr, obj
    return obj({
        "titulo": STR, "resumo": STR, "objetivo": STR, "mensagem": STR, "publico": STR, "prazo": STR,
        "entregaveis": arr(STR), "nao_fazer": arr(STR), "meta": STR, "versao_cliente": STR,
        "destinos": arr(obj({"destino": {"type": "string", "enum": list(DESTINATIONS)}, "por_que": STR})),
        "funcoes": arr(obj({"funcao": {"type": "string", "enum": list(ROLES)}, "o_que_fazer": STR})),
        "midia_objetivo": {"type": "string", "enum": [*OBJECTIVES, "nenhum"]}, "midia_verba": STR,
        "clipping_termos": arr(STR), "criadores_tipo": {"type": "string", "enum": ["influencer", "ugc", "nenhum"]},
    })


def clean_brief(data: Dict[str, Any]) -> Dict[str, Any]:
    """Tamanhos fixos: o briefing é para ser lido em 30 segundos."""
    from .media_strategy import OBJECTIVES
    from .studio_briefing_send import ROLES
    deadline = _text(data.get("prazo"), 10)
    try:
        deadline = date.fromisoformat(deadline).isoformat()
    except ValueError:
        deadline = ""
    budget = parse_brl(data.get("midia_verba"))
    destinations = []
    for d in data.get("destinos") or []:
        key = (d or {}).get("destino")
        if key in DESTINATIONS and key not in [x["key"] for x in destinations]:
            destinations.append({"key": key, "why": _text(d.get("por_que"), 200)})
    roles = []
    for r in data.get("funcoes") or []:
        key = (r or {}).get("funcao")
        if key in ROLES and key not in [x["role"] for x in roles]:
            roles.append({"role": key, "what": _text(r.get("o_que_fazer"), 240)})
    objective = data.get("midia_objetivo") if data.get("midia_objetivo") in OBJECTIVES else None
    creators = data.get("criadores_tipo") if data.get("criadores_tipo") in ("influencer", "ugc") else None
    return {
        "title": _text(data.get("titulo"), 120) or "Briefing", "summary": _text(data.get("resumo"), 400),
        "objective": _text(data.get("objetivo"), 300), "key_message": _text(data.get("mensagem"), 300),
        "audience": _text(data.get("publico"), 300), "deadline": deadline or None,
        "deliverables": _items(data.get("entregaveis"), 6), "avoid": _items(data.get("nao_fazer"), 4),
        "goal": _text(data.get("meta"), 240), "client_summary": _text(data.get("versao_cliente"), 400),
        "destinations": destinations[:5], "roles": roles[:9],
        "media": {"objective": objective, "budget": budget if budget and 0 < budget < 100_000_000 else None},
        "clipping_terms": _items(data.get("clipping_termos"), 6, 60), "creators_type": creators,
    }


async def generate_brief(client_id: str, request: str, links: List[str], *, instruction: Optional[str] = None) -> Dict[str, Any]:
    from .studio_engines import throttle
    from .studio_intelligence import build_content_intelligence, to_prompt
    from .studio_llm import llm_json
    throttle(client_id)
    profile = (await load_profile(client_id))["profile"]
    intel = await build_content_intelligence(client_id)
    today = datetime.now(SAO_PAULO).date().isoformat()
    prompt = (
        f"HOJE: {today}\nPEDIDO (digitado por quem pediu):\n{request.strip()[:4000]}\n"
        + (f"\nLINKS ENVIADOS:\n" + "\n".join(f"- {u}" for u in links[:10]) + "\n" if links else "")
        + (f"\nAJUSTE PEDIDO PELA EQUIPE NESTE BRIEFING: {instruction.strip()[:600]}\n" if instruction and instruction.strip() else "")
        + "\nMonte o BRIEFING para a agência executar. Seja SUCINTO e concreto, sem frase genérica:\n"
          "- titulo: até 8 palavras.\n- resumo: 1 ou 2 frases do que vamos fazer.\n- objetivo: 1 frase, o resultado para o negócio.\n"
          "- mensagem: a única ideia que o público deve guardar.\n- publico: para quem é, 1 frase.\n"
          "- prazo: data AAAA-MM-DD se o pedido indicar (ou a data comercial óbvia); senão vazio.\n"
          "- entregaveis: até 6, curtos (ex.: '4 Reels', 'campanha Meta de vendas', 'landing page').\n"
          "- nao_fazer: até 4 cuidados (tom, promessa, assunto proibido da marca).\n"
          "- meta: como vamos provar o resultado para o cliente, mensurável (ex.: '120 pedidos de decant em 30 dias').\n"
          "- versao_cliente: até 3 linhas, para o CLIENTE ler: o que vamos fazer, para quando e como medimos. Sem jargão.\n"
          "- destinos: só os que fazem sentido (social_media = conteúdo orgânico do mês; midia_on = anúncios pagos; "
          "clipping = monitorar notícias/termos; redacao = textos longos, roteiros, e-mails, páginas; criadores = influenciadores/UGC), "
          "cada um com 'por_que' em 1 frase.\n"
          "- funcoes: quem precisa trabalhar e o que faz, 1 frase cada.\n"
          "- midia_objetivo e midia_verba: se houver mídia paga (verba em reais só se o pedido disser; senão vazio).\n"
          "- clipping_termos: termos para monitorar, se fizer sentido.\n- criadores_tipo: influencer, ugc ou nenhum.\n"
          "Sem travessão. Não invente oferta, preço, número ou prazo que não esteja no pedido ou nos DADOS.\n"
        + f"\nDADOS DA MARCA:\n{to_prompt(intel)}\n\n{language_rule(profile)}"
    )
    data = await llm_json(client_id=client_id, prompt=prompt, schema_name="studio_brief", schema=_schema(), temperature=0.4,
                          instructions="Você é o atendimento sênior de uma agência: transforma o pedido do cliente em briefing claro, curto e executável.")
    brief = clean_brief(data)
    if not (brief["summary"] or brief["objective"]):
        raise StudioError("AI_INVALID_OUTPUT")
    return brief


# ------------------------------------------------------------------ CRUD

def client_view(row: Dict[str, Any], progress: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
    """O que o cliente vê: o pedido dele, a versão curta, prazo, meta e o andamento. Nada interno."""
    b = row.get("brief") or {}
    out = {k: row.get(k) for k in CLIENT_FIELDS}
    out["brief"] = {k: b.get(k) for k in ("title", "client_summary", "deadline", "goal")}
    out["progress"] = progress or {"done": 0, "total": 0}
    return out


async def _progress(client_id: str, rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    ids = sorted({str(t.get("task_id")) for r in rows for t in r.get("tasks") or [] if t.get("task_id")})
    status: Dict[str, str] = {}
    if ids:
        try:
            for t in await sb_select("studio_tasks", select="id,status",
                                     filters={"client_id": f"eq.{client_id}", "id": f"in.({','.join(ids)})"}, limit=500):
                status[str(t["id"])] = str(t.get("status"))
        except Exception:  # noqa: BLE001 — sem andamento, a lista abre igual
            pass
    out = {}
    for r in rows:
        tasks = [str(t.get("task_id")) for t in r.get("tasks") or [] if t.get("task_id")]
        out[str(r["id"])] = {"done": sum(1 for t in tasks if status.get(t) == "completed"), "total": len(tasks)}
    return out


async def list_briefs(client_id: str, *, team: bool) -> List[Dict[str, Any]]:
    rows = await sb_select(TABLE, select="*", filters={"client_id": f"eq.{client_id}", "status": "neq.arquivado"},
                           order="created_at.desc", limit=60)
    progress = await _progress(client_id, rows)
    if team:
        return [{**r, "progress": progress.get(str(r["id"]))} for r in rows]
    return [client_view(r, progress.get(str(r["id"]))) for r in rows]


async def get_brief(client_id: str, brief_id: str, *, team: bool) -> Dict[str, Any]:
    rows = await sb_select(TABLE, select="*", filters={"client_id": f"eq.{client_id}", "id": f"eq.{brief_id}"}, limit=1)
    if not rows:
        raise StudioError("BRIEF_NOT_FOUND", "Briefing não encontrado.")
    progress = (await _progress(client_id, rows)).get(str(rows[0]["id"]))
    return {**rows[0], "progress": progress} if team else client_view(rows[0], progress)


async def create_brief(client_id: str, *, request: str, links: List[str], user_id: str, author: str, team: bool) -> Dict[str, Any]:
    _forget(client_id)  # o pacote da IA relê na próxima geração
    clean_links = [u.strip()[:500] for u in links if isinstance(u, str) and u.strip().startswith("https://")][:10]
    brief = await generate_brief(client_id, request, clean_links)
    row = await sb_insert(TABLE, {"client_id": client_id, "request": request.strip()[:4000], "links": clean_links, "brief": brief,
                                  "status": "pronto" if team else "aguardando_equipe", "created_by": user_id,
                                  "created_by_name": (author or "")[:120] or None, "created_side": "mugo" if team else "cliente",
                                  **({"approved_by": user_id, "approved_at": _now()} if team else {})})
    if not row:
        raise StudioError("BRIEF_SAVE_FAILED", "Não foi possível salvar o briefing.")
    if not team:
        # A equipe fica sabendo na hora (Conversa da marca + WhatsApp do time, como as aprovações).
        try:
            from .studio_team import notify_team
            await notify_team(client_id, {"id": None, "title": f"Briefing: {brief['title']}"}, "comentario",
                              actor_name=author or "Cliente", comment=request.strip()[:600])
        except Exception as exc:  # noqa: BLE001
            print(f"[studio][briefs] notify_failed client_id={client_id} {type(exc).__name__}")
    return {**row, "progress": {"done": 0, "total": 0}} if team else client_view(row)


EDITABLE = ("title", "summary", "objective", "key_message", "audience", "deadline", "goal", "client_summary")


async def update_brief(client_id: str, brief_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    _forget(client_id)  # o pacote da IA relê na próxima geração
    current = await get_brief(client_id, brief_id, team=True)
    brief = dict(current.get("brief") or {})
    for key in EDITABLE:
        if key in patch:
            brief[key] = _text(patch[key], 400) or None
    for key, n in (("deliverables", 6), ("avoid", 4)):
        if key in patch:
            brief[key] = _items(patch[key], n)
    update: Dict[str, Any] = {"brief": brief, "updated_at": _now()}
    if patch.get("status") in ("arquivado", "pronto"):
        update["status"] = patch["status"]
    rows = await sb_update(TABLE, filters={"client_id": f"eq.{client_id}", "id": f"eq.{brief_id}"}, patch=update)
    return {**(rows[0] if rows else {**current, **update}), "progress": current.get("progress")}


async def regenerate(client_id: str, brief_id: str, instruction: Optional[str]) -> Dict[str, Any]:
    current = await get_brief(client_id, brief_id, team=True)
    brief = await generate_brief(client_id, current["request"], current.get("links") or [], instruction=instruction)
    rows = await sb_update(TABLE, filters={"client_id": f"eq.{client_id}", "id": f"eq.{brief_id}"}, patch={"brief": brief, "updated_at": _now()})
    return {**(rows[0] if rows else current), "progress": current.get("progress")}


async def approve(client_id: str, brief_id: str, *, user_id: str) -> Dict[str, Any]:
    _forget(client_id)  # o pacote da IA relê na próxima geração
    current = await get_brief(client_id, brief_id, team=True)
    rows = await sb_update(TABLE, filters={"client_id": f"eq.{client_id}", "id": f"eq.{brief_id}"},
                           patch={"status": "pronto", "approved_by": user_id, "approved_at": _now(), "updated_at": _now()})
    return {**(rows[0] if rows else current), "progress": current.get("progress")}


# ------------------------------------------------------------------ distribuir

def brief_text(row: Dict[str, Any]) -> str:
    """Briefing em texto corrido (vai como foco da Matriz, briefing do Mídia On e dos Criadores)."""
    b = row.get("brief") or {}
    lines = [f"{b.get('title') or ''}: {b.get('summary') or ''}".strip(": ")]
    for key, label in (("objective", "Objetivo"), ("key_message", "Mensagem"), ("audience", "Público"), ("deadline", "Prazo"), ("goal", "Meta")):
        if b.get(key):
            lines.append(f"{label}: {b[key]}")
    if b.get("deliverables"):
        lines.append("Entregáveis: " + "; ".join(b["deliverables"]))
    if b.get("avoid"):
        lines.append("Não fazer: " + "; ".join(b["avoid"]))
    return "\n".join(lines)[:1200]


def _doc_html(row: Dict[str, Any]) -> str:
    b = row.get("brief") or {}
    esc = lambda v: html.escape(str(v or ""))  # noqa: E731
    parts = [f"<h2>{esc(b.get('title'))}</h2>", f"<p>{esc(b.get('summary'))}</p>"]
    for key, label in (("objective", "Objetivo"), ("key_message", "Mensagem"), ("audience", "Público"), ("deadline", "Prazo"), ("goal", "Meta")):
        if b.get(key):
            parts.append(f"<p><strong>{label}:</strong> {esc(b[key])}</p>")
    for key, label in (("deliverables", "Entregáveis"), ("avoid", "Não fazer")):
        if b.get(key):
            parts.append(f"<p><strong>{label}:</strong></p><ul>" + "".join(f"<li>{esc(x)}</li>" for x in b[key]) + "</ul>")
    parts.append(f"<p><strong>Pedido original:</strong> {esc(row.get('request'))}</p>")
    return "".join(parts)


def _month_for(b: Dict[str, Any]) -> str:
    today = datetime.now(SAO_PAULO).date()
    try:
        deadline = date.fromisoformat(str(b.get("deadline")))
        if deadline >= today.replace(day=1):
            return deadline.strftime("%Y-%m")
    except (TypeError, ValueError):
        pass
    return today.strftime("%Y-%m")


async def send_to(client_id: str, brief_id: str, destination: str, *, user_id: str) -> Dict[str, Any]:
    """Leva o briefing para a tela escolhida. Cada destino devolve o que criou (para abrir de lá)."""
    if destination not in DESTINATIONS:
        raise StudioError("DESTINATION_INVALID", "Destino inválido.")
    row = await get_brief(client_id, brief_id, team=True)
    if row.get("status") == "aguardando_equipe":
        raise StudioError("BRIEF_NOT_APPROVED", "Aprove o briefing antes de distribuir.")
    b = row.get("brief") or {}
    text = brief_text(row)
    result: Dict[str, Any]
    try:
        if destination == "social_media":
            from .studio_agents import start_run
            from .studio_matrix import weeks_for_deadline
            weeks = weeks_for_deadline(b.get("deadline"))
            run = await start_run(client_id, user_id=user_id, focus=text, weeks=weeks, brief_id=brief_id)
            period = f" para {weeks} semana{'s' if weeks > 1 else ''} (até o prazo)" if weeks else ""
            detail = ("Na fila da esteira: começa quando a anterior terminar." if run.get("status") == "na_fila"
                      else f"Esteira montando a Matriz{period}. Confira na Social Media e clique em Gerar conteúdo.")
            result = {"status": "feito", "detail": detail, "ref": {"agent_run_id": run.get("id")}}
        elif destination == "midia_on":
            from .media_plan import record_strategy
            from .media_strategy import build_strategy
            objective = (b.get("media") or {}).get("objective") or "vendas"
            budget = (b.get("media") or {}).get("budget")
            strategy = await build_strategy(client_id, month=_month_for(b), objective=objective, custom_budget=budget, briefing=text)
            saved = await record_strategy(client_id, strategy, objective=objective, margin=None, custom_budget=budget, user_id=user_id)
            result = {"status": "feito", "detail": f"Estratégia de mídia ({objective}) gerada para {_month_for(b)}. Abra o Mídia On para conferir.",
                      "ref": {"strategy_id": saved.get("id")}}
        elif destination == "clipping":
            from .studio_clipping import get_settings, save_settings
            terms = b.get("clipping_terms") or []
            if not terms:
                raise StudioError("BRIEF_NO_TERMS", "Este briefing não tem termos para monitorar.")
            settings = await get_settings(client_id)
            if not settings.get("brand_terms"):
                raise StudioError("CLIPPING_TERMS_REQUIRED", "Configure o Clipping da marca (termos da marca) antes de mandar termos.")
            keywords = list(dict.fromkeys([*(settings.get("keywords") or []), *terms]))
            await save_settings(client_id, {**settings, "keywords": keywords}, user_id=user_id)
            result = {"status": "feito", "detail": f"Monitorando também: {', '.join(terms)}.", "ref": {"terms": terms}}
        elif destination == "redacao":
            from .studio_documents import create_document
            doc = await create_document(client_id, {"title": f"Briefing: {b.get('title') or 'pedido'}", "kind": "livre",
                                                    "content_html": _doc_html(row)}, user_id=user_id)
            result = {"status": "feito", "detail": "Documento criado na Redação com o briefing.", "ref": {"document_id": doc.get("id")}}
        else:
            from . import creators
            kind = b.get("creators_type") or "influencer"
            shortlist = await sb_insert("creator_shortlists", {"client_id": client_id, "name": f"Briefing: {b.get('title') or 'pedido'}"[:120],
                                                               "campaign_type": kind, "notes": text[:2000], "created_by": user_id})
            found = await creators.suggest(client_id, kind, text[:1000], 6)
            handles = [str((c.get("creator") or {}).get("handle") or (c.get("creator") or {}).get("username") or "")
                       for c in found.get("suggestions") or []][:8]
            result = {"status": "feito", "detail": f"Lista criada em Criadores com {len([h for h in handles if h])} sugestões.",
                      "ref": {"shortlist_id": (shortlist or {}).get("id"), "handles": [h for h in handles if h]}}
    except StudioError as exc:
        result = {"status": "falhou", "detail": str(exc) if str(exc) != exc.code else "Não foi possível levar para esta tela agora."}
    except Exception as exc:  # noqa: BLE001
        print(f"[studio][briefs] destination={destination} failed={type(exc).__name__}")
        result = {"status": "falhou", "detail": "Não foi possível levar para esta tela agora. Tente de novo."}
    destinations = {**(row.get("destinations") or {}), destination: {**result, "at": _now()}}
    status = "distribuido" if result["status"] == "feito" else row.get("status")
    await sb_update(TABLE, filters={"client_id": f"eq.{client_id}", "id": f"eq.{brief_id}"},
                    patch={"destinations": destinations, "status": status, "updated_at": _now()})
    return {**row, "destinations": destinations, "status": status}


def task_text(row: Dict[str, Any], role: str, note: Optional[str]) -> str:
    """A parte da pessoa: o que ela faz (sugestão da IA para a função) + o essencial do briefing."""
    from .studio_briefing_send import ROLES
    b = row.get("brief") or {}
    what = next((r.get("what") for r in b.get("roles") or [] if r.get("role") == role), None)
    lines = [f"Briefing: {b.get('title') or ''}", b.get("summary") or ""]
    if what:
        lines.append(f"Sua parte ({ROLES[role]}): {what}")
    if note and note.strip():
        lines.append(f"Recado: {note.strip()[:600]}")
    for key, label in (("objective", "Objetivo"), ("key_message", "Mensagem"), ("audience", "Público"), ("deadline", "Prazo"), ("goal", "Meta")):
        if b.get(key) and not (role == "designer" and key == "goal"):
            lines.append(f"{label}: {b[key]}")
    if b.get("deliverables"):
        lines.append("Entregáveis: " + "; ".join(b["deliverables"]))
    if b.get("avoid"):
        lines.append("Não fazer: " + "; ".join(b["avoid"]))
    return "\n".join(x for x in lines if x)[:4000]


async def create_person_task(client_id: str, brief_id: str, *, role: str, user_id: str, assignee_user_id: Optional[str],
                             assignee_name: Optional[str], due_date: Optional[str], note: Optional[str]) -> Dict[str, Any]:
    from .studio_briefing_send import ROLES
    from .studio_tasks import create_task
    if role not in ROLES:
        raise StudioError("ROLE_INVALID", "Escolha a função.")
    row = await get_brief(client_id, brief_id, team=True)
    if row.get("status") == "aguardando_equipe":
        raise StudioError("BRIEF_NOT_APPROVED", "Aprove o briefing antes de distribuir.")
    b = row.get("brief") or {}
    who = (assignee_name or "").strip()[:80] or ROLES[role]
    due = due_date or b.get("deadline")
    if due:
        try:
            due = max(date.fromisoformat(str(due)), datetime.now(SAO_PAULO).date()).isoformat()
        except ValueError:
            due = None
    task = await create_task(client_id, {
        "title": f"{ROLES[role]}: {str(b.get('title') or 'briefing')[:150]}", "notes": task_text(row, role, note),
        "category": ROLES[role], "status": "pending", "priority": "medium", "due_date": due, "assignee_name": who,
        "assignee_user_id": assignee_user_id, "visible_to_client": role in ("cliente", "dono"), "needs_client_approval": False,
    }, user_id=user_id, client_view=False)
    tasks = [*(row.get("tasks") or []), {"task_id": task.get("id"), "role": role, "name": who, "user_id": assignee_user_id, "at": _now()}]
    await sb_update(TABLE, filters={"client_id": f"eq.{client_id}", "id": f"eq.{brief_id}"},
                    patch={"tasks": tasks, "status": "distribuido", "updated_at": _now()})
    return {**row, "tasks": tasks, "status": "distribuido"}
