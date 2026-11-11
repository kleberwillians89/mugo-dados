"""Planejamento e Evento (trazidos da iAgência, no layout do MUGOVERSO).

- Planejamento: o job estratégico. Objetivo e público → a IA (CSO) monta o plano curto: contexto, desafio, insight,
  estratégia, grande ideia, mensagens, canais, fases, KPIs e riscos. O copiloto conversa sobre o plano; "aplicar a
  conversa" refaz o plano levando o que foi combinado.
- Evento (Produção RTV e Eventos): vídeo, sessão de fotos, evento/ativação, podcast. A ideia e a data → a IA
  (diretor de produção) monta cronograma, equipe, orçamento por categoria, riscos e checklist. Lê também o radar do
  evento (clima e notícias da região, ``event_radar``) e os fornecedores da marca (``studio_suppliers``).

Os dois têm o mesmo quadro (Fila → Em andamento → Aprovação interna → Finalizado) e viram Briefing com um clique
para distribuir às telas e às pessoas. Tudo curto, para ler em um minuto.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from .ig_supabase import sb_delete, sb_insert, sb_select, sb_update
from .studio_calendar import SAO_PAULO, StudioError, language_rule, load_profile

TABLE = "studio_projects"
KINDS = ("planejamento", "evento")
STATUSES = ("fila", "em_andamento", "aprovacao_interna", "finalizado")
EVENT_FORMATS = ("Vídeo institucional", "Reels/TikTok", "Sessão de fotos", "Evento / Ativação", "Podcast")
BUDGET_CATEGORIES = ("equipe", "equipamento", "locacao", "logistica", "pos_producao", "outros")
CHAT_LIMIT = 20


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _t(value: Any, n: int) -> str:
    return " ".join(str(value or "").split())[:n]


def _list(value: Any, n: int, limit: int = 200) -> List[str]:
    return [x for x in (_t(v, limit) for v in (value or []) if isinstance(v, (str, int, float))) if x][:n]


def _qty(value: Any) -> int:
    try:
        return max(1, min(50, int(float(value or 1))))
    except (TypeError, ValueError):
        return 1


def _money(value: Any) -> float:
    from .studio_briefs import parse_brl
    if isinstance(value, (int, float)):
        return max(0.0, float(value))
    return max(0.0, parse_brl(value) or 0.0)


# ------------------------------------------------------------------ esquemas da IA

def _schema(kind: str) -> Dict[str, Any]:
    from .studio_llm import INT, STR, arr, obj
    if kind == "planejamento":
        return obj({"titulo": STR, "contexto": STR, "desafio": STR, "insight": STR, "estrategia": STR, "grande_ideia": STR,
                    "mensagens": arr(STR), "canais": arr(obj({"canal": STR, "papel": STR})),
                    "fases": arr(obj({"fase": STR, "quando": STR, "o_que": STR})),
                    "kpis": arr(obj({"kpi": STR, "meta": STR})), "riscos": arr(STR)})
    return obj({"titulo": STR, "resumo": STR,
                "cronograma": arr(obj({"data": STR, "fase": STR, "tarefa": STR})),
                "equipe": arr(obj({"funcao": STR, "quantidade": INT, "observacao": STR})),
                "orcamento": arr(obj({"categoria": {"type": "string", "enum": list(BUDGET_CATEGORIES)}, "item": STR, "valor": STR})),
                "riscos": arr(obj({"risco": STR, "impacto": {"type": "string", "enum": ["baixo", "medio", "alto"]}, "mitigacao": STR})),
                "checklist": arr(STR)})


def clean_plan(kind: str, data: Dict[str, Any]) -> Dict[str, Any]:
    if kind == "planejamento":
        return {
            "context": _t(data.get("contexto"), 500), "challenge": _t(data.get("desafio"), 300), "insight": _t(data.get("insight"), 300),
            "strategy": _t(data.get("estrategia"), 600), "big_idea": _t(data.get("grande_ideia"), 200),
            "messages": _list(data.get("mensagens"), 5, 200),
            "channels": [{"channel": _t(c.get("canal"), 60), "role": _t(c.get("papel"), 200)} for c in data.get("canais") or [] if _t(c.get("canal"), 60)][:6],
            "phases": [{"phase": _t(p.get("fase"), 60), "when": _t(p.get("quando"), 60), "what": _t(p.get("o_que"), 240)} for p in data.get("fases") or [] if _t(p.get("fase"), 60)][:6],
            "kpis": [{"kpi": _t(k.get("kpi"), 80), "target": _t(k.get("meta"), 120)} for k in data.get("kpis") or [] if _t(k.get("kpi"), 80)][:5],
            "risks": _list(data.get("riscos"), 4, 200),
        }
    budget = [{"category": b.get("categoria") if b.get("categoria") in BUDGET_CATEGORIES else "outros", "item": _t(b.get("item"), 120),
               "value": round(_money(b.get("valor")), 2)} for b in data.get("orcamento") or [] if _t(b.get("item"), 120)][:20]
    return {
        "summary": _t(data.get("resumo"), 400),
        "timeline": [{"date": _t(c.get("data"), 20), "phase": _t(c.get("fase"), 60), "task": _t(c.get("tarefa"), 200)} for c in data.get("cronograma") or [] if _t(c.get("tarefa"), 200)][:14],
        "staff": [{"role": _t(e.get("funcao"), 60), "qty": _qty(e.get("quantidade")), "note": _t(e.get("observacao"), 160)} for e in data.get("equipe") or [] if _t(e.get("funcao"), 60)][:12],
        "budget": budget, "budget_total": round(sum(b["value"] for b in budget), 2),
        "risks": [{"risk": _t(r.get("risco"), 160), "impact": r.get("impacto") if r.get("impacto") in ("baixo", "medio", "alto") else "medio",
                   "mitigation": _t(r.get("mitigacao"), 200)} for r in data.get("riscos") or [] if _t(r.get("risco"), 160)][:6],
        "checklist": _list(data.get("checklist"), 10, 160),
    }


def plan_text(project: Dict[str, Any]) -> str:
    """Plano em texto corrido (vai para o copiloto e para o Briefing)."""
    p, i = project.get("plan") or {}, project.get("inputs") or {}
    lines = [f"{'Planejamento' if project['kind'] == 'planejamento' else 'Produção'}: {project.get('title')}"]
    for key, label in (("objective", "Objetivo"), ("audience", "Público"), ("idea", "Ideia"), ("budget", "Verba"), ("location", "Local")):
        if i.get(key):
            lines.append(f"{label}: {i[key]}")
    if project.get("format"):
        lines.append(f"Formato: {project['format']}")
    if project.get("target_date"):
        lines.append(f"Data alvo: {project['target_date']}")
    if project["kind"] == "planejamento":
        for key, label in (("context", "Contexto"), ("challenge", "Desafio"), ("insight", "Insight"), ("strategy", "Estratégia"), ("big_idea", "Grande ideia")):
            if p.get(key):
                lines.append(f"{label}: {p[key]}")
        if p.get("messages"):
            lines.append("Mensagens: " + "; ".join(p["messages"]))
        if p.get("channels"):
            lines.append("Canais: " + "; ".join(f"{c['channel']} ({c['role']})" for c in p["channels"]))
        if p.get("phases"):
            lines.append("Fases: " + "; ".join(f"{x['phase']} {x['when']}: {x['what']}" for x in p["phases"]))
        if p.get("kpis"):
            lines.append("KPIs: " + "; ".join(f"{k['kpi']} = {k['target']}" for k in p["kpis"]))
    else:
        if p.get("summary"):
            lines.append(f"Resumo: {p['summary']}")
        if p.get("timeline"):
            lines.append("Cronograma: " + "; ".join(f"{t['date']} {t['phase']}: {t['task']}" for t in p["timeline"]))
        if p.get("staff"):
            lines.append("Equipe: " + "; ".join(f"{s['qty']}x {s['role']}" for s in p["staff"]))
        radar = project.get("radar") or {}
        for alert in (radar.get("alertas") or [])[:3]:
            lines.append(f"Clima ({alert.get('tipo')}): {alert.get('texto')}")
        if p.get("budget_total"):
            lines.append(f"Orçamento total: R$ {p['budget_total']:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    return "\n".join(lines)[:3800]


# ------------------------------------------------------------------ CRUD

def _clean_inputs(data: Dict[str, Any]) -> Dict[str, str]:
    return {k: _t(data.get(k), 600) for k in ("objective", "audience", "idea", "budget", "location", "notes") if _t(data.get(k), 600)}


async def list_projects(client_id: str, kind: str) -> List[Dict[str, Any]]:
    if kind not in KINDS:
        raise StudioError("PROJECT_KIND_INVALID", "Tipo inválido.")
    return await sb_select(TABLE, select="*", filters={"client_id": f"eq.{client_id}", "kind": f"eq.{kind}"}, order="updated_at.desc", limit=200)


async def get_project(client_id: str, project_id: str) -> Dict[str, Any]:
    rows = await sb_select(TABLE, select="*", filters={"client_id": f"eq.{client_id}", "id": f"eq.{project_id}"}, limit=1)
    if not rows:
        raise StudioError("PROJECT_NOT_FOUND", "Não encontrado.")
    return rows[0]


def _clean_fields(data: Dict[str, Any], kind: str) -> Dict[str, Any]:
    row: Dict[str, Any] = {}
    if "title" in data:
        title = _t(data.get("title"), 200)
        if not title:
            raise StudioError("PROJECT_TITLE_REQUIRED", "Dê um nome.")
        row["title"] = title
    if "status" in data:
        if data["status"] not in STATUSES:
            raise StudioError("PROJECT_STATUS_INVALID", "Etapa inválida.")
        row["status"] = data["status"]
    if "format" in data:
        row["format"] = _t(data.get("format"), 60) or None
    if "target_date" in data:
        value = data.get("target_date")
        try:
            row["target_date"] = date.fromisoformat(str(value)[:10]).isoformat() if value else None
        except ValueError:
            raise StudioError("PROJECT_DATE_INVALID", "Data inválida.") from None
    if "inputs" in data:
        row["inputs"] = _clean_inputs(data.get("inputs") or {})
    if "plan" in data and isinstance(data.get("plan"), dict):
        row["plan"] = _reclean(kind, data["plan"])
    return row


def _reclean(kind: str, plan: Dict[str, Any]) -> Dict[str, Any]:
    """Plano editado na tela (chaves em inglês): só recalcula o total do orçamento e corta tamanhos."""
    out = dict(plan)
    if kind == "evento":
        budget = [{"category": b.get("category") if b.get("category") in BUDGET_CATEGORIES else "outros", "item": _t(b.get("item"), 120),
                   "value": round(_money(b.get("value")), 2),
                   **({"supplier_link_id": _t(b.get("supplier_link_id"), 40)} if b.get("supplier_link_id") else {})}
                  for b in plan.get("budget") or [] if isinstance(b, dict) and _t(b.get("item"), 120)][:30]
        out["budget"], out["budget_total"] = budget, round(sum(b["value"] for b in budget), 2)
    if len(json.dumps(out, ensure_ascii=False, default=str)) > 60000:
        raise StudioError("PROJECT_TOO_LARGE", "O plano ficou grande demais.")
    return out


async def create_project(client_id: str, kind: str, data: Dict[str, Any], *, user_id: str) -> Dict[str, Any]:
    if kind not in KINDS:
        raise StudioError("PROJECT_KIND_INVALID", "Tipo inválido.")
    row = _clean_fields({"title": data.get("title"), **{k: data[k] for k in ("format", "target_date", "inputs") if k in data}}, kind)
    created = await sb_insert(TABLE, {"client_id": client_id, "kind": kind, "status": "fila", "created_by": user_id, **row})
    if not created:
        raise StudioError("PROJECT_SAVE_FAILED", "Não foi possível salvar.")
    return created


async def update_project(client_id: str, project_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    current = await get_project(client_id, project_id)
    patch = _clean_fields(data, current["kind"])
    patch["updated_at"] = _now()
    rows = await sb_update(TABLE, filters={"client_id": f"eq.{client_id}", "id": f"eq.{project_id}"}, patch=patch)
    return rows[0] if rows else {**current, **patch}


async def delete_project(client_id: str, project_id: str) -> None:
    await get_project(client_id, project_id)
    await sb_delete(TABLE, filters={"client_id": f"eq.{client_id}", "id": f"eq.{project_id}"}, returning="minimal")


# ------------------------------------------------------------------ IA

ROLE = {
    "planejamento": "Você é o CSO (diretor de estratégia) de uma agência. Planeja com base nos dados reais da marca, curto e acionável.",
    "evento": "Você é diretor de produção de uma agência (RTV, fotos e eventos). Planeja produção real, com prazos e custos plausíveis em reais.",
}


async def generate_plan(client_id: str, project_id: str, *, use_chat: bool = False, instruction: Optional[str] = None) -> Dict[str, Any]:
    from .studio_engines import throttle
    from .studio_intelligence import build_content_intelligence, to_prompt
    from .studio_llm import llm_json
    project = await get_project(client_id, project_id)
    kind, i = project["kind"], project.get("inputs") or {}
    if kind == "planejamento" and not (i.get("objective") or project.get("title")):
        raise StudioError("PROJECT_INPUT_REQUIRED", "Escreva o objetivo do planejamento.")
    if kind == "evento" and not (i.get("idea") or project.get("title")):
        raise StudioError("PROJECT_INPUT_REQUIRED", "Descreva a produção ou o evento.")
    throttle(client_id)
    profile = (await load_profile(client_id))["profile"]
    intel = await build_content_intelligence(client_id)
    today = datetime.now(SAO_PAULO).date().isoformat()
    chat = [m for m in project.get("chat") or [] if isinstance(m, dict)][-10:] if use_chat else []
    ask = (f"HOJE: {today}\nJOB: {project['title']}\n"
           + "".join(f"{label}: {i[key]}\n" for key, label in (("objective", "Objetivo"), ("audience", "Público"), ("idea", "Ideia"),
                                                                ("budget", "Verba disponível"), ("location", "Local"), ("notes", "Observações")) if i.get(key))
           + (f"Formato: {project['format']}\n" if project.get("format") else "")
           + (f"Data alvo: {project['target_date']}\n" if project.get("target_date") else "")
           + (f"\nPLANO ATUAL (melhore, não comece do zero):\n{plan_text(project)}\n" if project.get("plan") else "")
           + (f"\nCONVERSA COM A EQUIPE (leve em conta o que foi combinado):\n" + "\n".join(f"{m.get('role')}: {str(m.get('content'))[:600]}" for m in chat) + "\n" if chat else "")
           + (f"\nPEDIDO DA EQUIPE: {instruction.strip()[:600]}\n" if instruction and instruction.strip() else ""))
    if kind == "planejamento":
        ask += ("\nMonte o PLANEJAMENTO, curto e concreto: contexto (2 frases com dado da marca), desafio, insight (uma verdade do público), "
                "estratégia (como vamos ganhar), grande ideia (uma frase), até 5 mensagens, canais com o papel de cada um, até 6 fases com "
                "quando e o que, até 5 KPIs com meta numérica, até 4 riscos.\n")
    else:
        from .event_radar import radar_text, refresh as refresh_radar
        from .studio_suppliers import suppliers_text
        if not project.get("radar") and i.get("location"):
            try:  # primeira vez com local: puxa clima e notícias antes de planejar
                project = await refresh_radar(client_id, project_id)
            except Exception as exc:  # noqa: BLE001 — sem radar, o plano sai sem clima
                print(f"[studio][projects] radar_failed error_type={type(exc).__name__}")
        radar = radar_text(project.get("radar") or {})
        suppliers = await suppliers_text(client_id, project_id)
        if radar:
            ask += (f"\nCLIMA E NOTÍCIAS DA REGIÃO (use nos riscos, no checklist e no plano B; clima típico é tendência, não previsão):\n{radar}\n")
        if suppliers:
            ask += ("\nFORNECEDORES DA MARCA (prefira estes antes de sugerir contratar outro; quem já está no evento entra com o valor "
                    f"fechado no orçamento e o nome no item):\n{suppliers}\n")
        ask += ("\nMonte o PLANO DE PRODUÇÃO: resumo (2 frases); cronograma de pré-produção, produção e pós com datas (AAAA-MM-DD, "
                "contando para trás da data alvo; sem data alvo, use D-30, D-7…); equipe com função, quantidade e observação; orçamento "
                "por item com categoria e valor em reais (estimativa de mercado em São Paulo, número); riscos com impacto e mitigação; "
                "checklist do dia.\n")
    ask += ("Sem travessão. Não invente dado da marca que não esteja nos DADOS.\n"
            f"\nDADOS DA MARCA:\n{to_prompt(intel)}\n\n{language_rule(profile)}")
    data = await llm_json(client_id=client_id, instructions=ROLE[kind], prompt=ask, schema_name=f"studio_{kind}",
                          schema=_schema(kind), temperature=0.5)
    plan = clean_plan(kind, data)
    if kind == "evento":
        # Linhas lançadas a partir dos fornecedores do evento continuam no orçamento quando o plano é refeito.
        kept = [b for b in (project.get("plan") or {}).get("budget") or [] if isinstance(b, dict) and b.get("supplier_link_id")]
        if kept:
            plan["budget"] = [*kept, *plan["budget"]][:30]
            plan["budget_total"] = round(sum(float(b.get("value") or 0) for b in plan["budget"]), 2)
    if kind == "planejamento" and not plan["strategy"]:
        raise StudioError("AI_INVALID_OUTPUT")
    if kind == "evento" and not plan["timeline"]:
        raise StudioError("AI_INVALID_OUTPUT")
    patch: Dict[str, Any] = {"plan": plan, "updated_at": _now()}
    if project["status"] == "fila":
        patch["status"] = "em_andamento"
    rows = await sb_update(TABLE, filters={"client_id": f"eq.{client_id}", "id": f"eq.{project_id}"}, patch=patch)
    return rows[0] if rows else {**project, **patch}


async def chat(client_id: str, project_id: str, message: str, *, author: str) -> Dict[str, Any]:
    """Copiloto (CSO no planejamento, produtor no evento): conversa sobre o plano, com o contexto da marca."""
    from .studio_engines import throttle
    from .studio_intelligence import build_content_intelligence, to_prompt
    from .studio_llm import STR, llm_json, obj
    project = await get_project(client_id, project_id)
    text = message.strip()[:1500]
    if not text:
        raise StudioError("PROJECT_INPUT_REQUIRED", "Escreva a mensagem.")
    throttle(client_id)
    intel = await build_content_intelligence(client_id)
    history = [m for m in project.get("chat") or [] if isinstance(m, dict)][-8:]
    from .event_radar import radar_text
    radar = radar_text(project.get("radar") or {}) if project["kind"] == "evento" else ""
    prompt = (f"PLANO:\n{plan_text(project)}\n" + (f"\nCLIMA E NOTÍCIAS DA REGIÃO:\n{radar}\n" if radar else "") + "\nCONVERSA:\n" + "\n".join(f"{m.get('role')}: {str(m.get('content'))[:600]}" for m in history)
              + f"\nequipe: {text}\n\nResponda em até 6 linhas, direto, com sugestão prática. Sem travessão.\n"
              f"\nDADOS DA MARCA:\n{to_prompt(intel, limit=6000)}")
    data = await llm_json(client_id=client_id, instructions=ROLE[project["kind"]], prompt=prompt, schema_name="studio_project_chat",
                          schema=obj({"resposta": STR}), temperature=0.6, guidance=False, max_output_tokens=600)
    answer = _t(data.get("resposta"), 1500) or "Não consegui responder agora."
    now = _now()
    messages = [*history, {"role": "equipe", "author": author[:80], "content": text, "at": now},
                {"role": "copiloto", "content": answer, "at": now}][-CHAT_LIMIT:]
    rows = await sb_update(TABLE, filters={"client_id": f"eq.{client_id}", "id": f"eq.{project_id}"}, patch={"chat": messages, "updated_at": now})
    return rows[0] if rows else {**project, "chat": messages}


async def to_brief(client_id: str, project_id: str, *, user_id: str, author: str) -> Dict[str, Any]:
    """Vira Briefing (já aprovado pela equipe) para distribuir às telas e às pessoas."""
    from .studio_briefs import create_brief
    project = await get_project(client_id, project_id)
    if not project.get("plan"):
        raise StudioError("PROJECT_INPUT_REQUIRED", "Gere o plano antes de mandar para o Briefing.")
    brief = await create_brief(client_id, request=plan_text(project), links=[], user_id=user_id, author=author, team=True)
    await sb_update(TABLE, filters={"client_id": f"eq.{client_id}", "id": f"eq.{project_id}"},
                    patch={"brief_id": brief.get("id"), "updated_at": _now()})
    return brief
