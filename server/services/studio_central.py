"""
Central da marca: o mês da marca numa página só, juntando o que cada módulo sabe.

Números da campanha (investimento, faturamento, retorno), andamento do Calendário, campanhas da
Redação, plano do Mídia On x realizado, Clipping da semana e tarefas — mais uma lista de "o que
precisa de atenção" calculada a partir disso. Cada bloco é lido com limite de tempo; bloco que
falha volta ``null`` e a página segue.

Cliente vê a mesma página com o filtro de sempre: só posts que pode ver, plano salvo, notícias
relevantes e tarefas com etiqueta "cliente". Campanhas da Redação e alertas internos são da Mugô.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

from .ig_supabase import sb_select

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
TIMEOUT = 15.0


async def _safe(name: str, fn: Callable[[], Awaitable[Any]]) -> Any:
    try:
        return await asyncio.wait_for(fn(), timeout=TIMEOUT)
    except Exception as exc:  # noqa: BLE001 — bloco que falha não derruba a Central
        print(f"[studio][central] bloco={name} erro={exc.__class__.__name__}")
        return None


def _month_bounds(month: date) -> tuple[date, date]:
    today = datetime.now(SAO_PAULO).date()
    nxt = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    end = min(nxt - timedelta(days=1), today - timedelta(days=1))
    return month, end


def _previous_bounds(start: date, end: date) -> tuple[date, date]:
    """Período anterior equivalente: mês fechado ou mesmos dias decorridos."""
    previous_end_of_month = start - timedelta(days=1)
    previous_start = previous_end_of_month.replace(day=1)
    elapsed_days = max(1, (end - start).days + 1)
    return previous_start, min(previous_end_of_month, previous_start + timedelta(days=elapsed_days - 1))


async def _number_period(client_id: str, start: date, end: date) -> Dict[str, Any]:
    from .studio_messages import _snapshot, _store_sales, _value
    snap = await _snapshot(client_id, start, end)
    sales = await _store_sales(client_id, start, end, snap["metrics"])
    spend = _value(snap["metrics"], "investment")
    revenue = sales.get("revenue")
    orders = sales.get("orders")
    return {"start": start.isoformat(), "end": end.isoformat(), "investimento": spend, "faturamento": revenue,
            "pedidos": orders, "ticket_medio": round(revenue / orders, 2) if revenue is not None and orders else None,
            "retorno": round(revenue / spend, 2) if revenue is not None and spend else None,
            "vendas_midia_paga": sales.get("paid_revenue"), "melhor_campanha": sales.get("top_campaign")}


async def _numbers(client_id: str, month: date) -> Optional[Dict[str, Any]]:
    start, end = _month_bounds(month)
    if end < start:
        return {"start": start.isoformat(), "end": None}
    previous_start, previous_end = _previous_bounds(start, end)
    current = await _number_period(client_id, start, end)
    try:
        previous = await _number_period(client_id, previous_start, previous_end)
    except Exception as exc:  # comparação ausente não apaga o período atual
        print(f"[studio][central] bloco=numeros_anteriores erro={exc.__class__.__name__}")
        previous = None
    return {**current, "previous": previous}


async def _social(client_id: str, month: date) -> Optional[Dict[str, Any]]:
    """Somente snapshots orgânicos persistidos; não atualiza Meta nem chama API externa."""
    from .brand_health_index import _instagram_totals
    from .social_report import load as load_social_report
    start, end = _month_bounds(month)
    if end < start:
        return None
    previous_start, previous_end = _previous_bounds(start, end)
    current, current_report = await asyncio.gather(
        _instagram_totals(client_id, start, end), load_social_report(client_id, month.strftime("%Y-%m"), fresh_images=False))
    if not current:
        return None
    try:
        previous, previous_report = await asyncio.gather(
            _instagram_totals(client_id, previous_start, previous_end),
            load_social_report(client_id, previous_start.strftime("%Y-%m"), fresh_images=False))
    except Exception as exc:  # comparação ausente não apaga snapshots atuais
        print(f"[studio][central] bloco=social_anterior erro={exc.__class__.__name__}")
        previous = None
        previous_report = {"built": False}
    current_overview = (current_report.get("data") or {}).get("overview") if current_report.get("built") else {}
    previous_overview = (previous_report.get("data") or {}).get("overview") if previous_report.get("built") else {}
    selected_month_end = (month.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    comparable_followers = previous_overview.get("new_followers") if end == selected_month_end else None
    return {"start": start.isoformat(), "end": end.isoformat(), "reach": current.get("reach"),
            "interactions": current.get("interactions"), "days": current.get("days"),
            "new_followers": current_overview.get("new_followers"),
            "previous": {"start": previous_start.isoformat(), "end": previous_end.isoformat(),
                         "reach": previous.get("reach"), "interactions": previous.get("interactions"),
                         "days": previous.get("days"), "new_followers": comparable_followers} if previous else None}


async def _calendar(client_id: str, month: date, *, agency: bool) -> Dict[str, Any]:
    from .studio_approvals import pipeline
    from .studio_client import CLIENT_STAGES
    data = await pipeline(client_id, month.strftime("%Y-%m"))
    items = data["items"] if agency else [i for i in data["items"] if i.get("stage") in CLIENT_STAGES]
    now = datetime.now(timezone.utc)
    upcoming = sorted((i for i in items if i.get("scheduled_at") and datetime.fromisoformat(str(i["scheduled_at"]).replace("Z", "+00:00")) >= now),
                      key=lambda i: i["scheduled_at"])[:5]
    counts = {stage: sum(1 for i in items if i.get("stage") == stage) for stage in data["stages"]}
    off_brand = [{"id": i["id"], "title": i.get("title"), "issues": len((i.get("signals") or {}).get("fora_da_marca") or [])}
                 for i in items if (i.get("signals") or {}).get("fora_da_marca")] if agency else []
    waiting = [i for i in items if i.get("stage") == "com_cliente" and (i.get("request") or {}).get("sent_at")
               and now - datetime.fromisoformat(str(i["request"]["sent_at"]).replace("Z", "+00:00")) > timedelta(days=2)]
    return {"total": len(items), "counts": counts,
            "upcoming": [{"id": i["id"], "title": i.get("title"), "format": i.get("format"), "scheduled_at": i.get("scheduled_at"),
                          "stage": i.get("stage"), "pillar": i.get("pillar")} for i in upcoming],
            "waiting_client": len(waiting), "off_brand": off_brand}


async def _media(client_id: str, month: date) -> Optional[Dict[str, Any]]:
    from .media_plan import plan_vs_actual
    data = await plan_vs_actual(client_id, month.strftime("%Y-%m"))
    plan = data.get("plan") or {}
    if not plan and not data.get("channels"):
        return None
    return {"objetivo": plan.get("objective"), "verba": plan.get("budget"), "elapsed_days": data.get("elapsed_days"),
            "days_in_month": data.get("days_in_month"),
            "channels": [{k: r.get(k) for k in ("channel", "label", "planned_spend", "spent", "expected_to_date", "projected_spend", "pace", "roas", "cpa")}
                         for r in data.get("channels") or []]}


async def _campaigns(client_id: str) -> List[Dict[str, Any]]:
    rows = await sb_select("studio_campaigns", select="id,name,status,briefing,calendar_item_ids,created_at", order="created_at.desc", limit=6,
                           filters={"client_id": f"eq.{client_id}", "status": "neq.arquivada"})
    return [{"id": r["id"], "name": r.get("name"), "status": r.get("status"), "objective": (r.get("briefing") or {}).get("objective"),
             "start": (r.get("briefing") or {}).get("start"), "end": (r.get("briefing") or {}).get("end"),
             "posts_no_calendario": len(r.get("calendar_item_ids") or [])} for r in rows]


async def _clipping(client_id: str) -> Optional[Dict[str, Any]]:
    from .studio_clipping import week_summary
    week = await week_summary(client_id)
    rows = await sb_select("studio_clippings", select="id,title,source,url,kind,sentiment,relevant,published_at", order="published_at.desc.nullslast",
                           limit=12, filters={"client_id": f"eq.{client_id}", "status": "neq.arquivado"})
    top = [r for r in rows if r.get("relevant") is not False][:3]
    if not week["current"]["total"] and not top:
        return None
    return {"week": week, "latest": top}


async def _tasks(client_id: str, *, agency: bool) -> Optional[Dict[str, Any]]:
    from .studio_tasks import OPEN_STATUSES, list_client_tasks, list_tasks
    data = await (list_tasks(client_id) if agency else list_client_tasks(client_id))
    if not data.get("available"):
        return {"available": False, "reason": data.get("reason")}
    tasks = data.get("tasks") or []
    today = datetime.now(SAO_PAULO).date().isoformat()
    open_tasks = [t for t in tasks if t.get("status") in OPEN_STATUSES]
    late = sum(1 for t in open_tasks if t.get("due_date") and t["due_date"] < today)
    stalled_before = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    stalled = sum(1 for t in open_tasks if t.get("updated_at") and str(t["updated_at"]) < stalled_before)
    rework = sum(1 for t in open_tasks if int(t.get("approval_round") or 0) > 1)
    out: Dict[str, Any] = {"available": True, "open": len(open_tasks), "late": late, "stalled": stalled, "rework": rework,
            "next": [{"title": t.get("title"), "due_date": t.get("due_date"), "status": t.get("status")}
                     for t in sorted(open_tasks, key=lambda t: t.get("due_date") or "9999")[:4]]}
    if agency:
        departments: Dict[str, int] = {}
        people: Dict[str, Dict[str, Any]] = {}
        for task in open_tasks:
            department = str(task.get("category") or "Sem departamento")
            departments[department] = departments.get(department, 0) + 1
            for assignee in task.get("assignees") or ([] if not task.get("assignee") else [task["assignee"]]):
                name = str(assignee.get("name") or "Responsável")
                person = people.setdefault(name, {"name": name, "tasks": 0, "late": 0, "rework": 0})
                person["tasks"] += 1
                person["late"] += int(bool(task.get("due_date") and task["due_date"] < today))
                person["rework"] += int(int(task.get("approval_round") or 0) > 1)
        out["workload"] = {"departments": [{"name": name, "tasks": count} for name, count in sorted(departments.items())],
                           "people": sorted(people.values(), key=lambda item: (-item["tasks"], item["name"]))}
    return out


async def _approval_history(client_id: str, month: date) -> Optional[Dict[str, Any]]:
    """Eventos reais dos últimos seis meses; cada linha persistida conta uma vez."""
    first = month
    for _ in range(5):
        first = (first - timedelta(days=1)).replace(day=1)
    approval_rows, task_rows = await asyncio.gather(
        sb_select("studio_approval_events", select="id,action,created_at", order="created_at.asc", limit=5000,
                  filters={"client_id": f"eq.{client_id}", "created_at": f"gte.{first.isoformat()}T00:00:00Z"}),
        sb_select("studio_task_events", select="id,kind,created_at", order="created_at.asc", limit=5000,
                  filters={"client_id": f"eq.{client_id}", "created_at": f"gte.{first.isoformat()}T00:00:00Z"}))
    months: List[str] = []
    cursor = first
    for _ in range(6):
        months.append(cursor.strftime("%Y-%m"))
        cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
    buckets = {key: {"month": key, "approved": 0, "internal_changes": 0, "client_changes": 0} for key in months}
    for row in approval_rows:
        bucket = buckets.get(str(row.get("created_at") or "")[:7])
        if bucket and row.get("action") == "aprovado": bucket["approved"] += 1
        if bucket and row.get("action") == "ajuste_solicitado": bucket["client_changes"] += 1
    for row in task_rows:
        bucket = buckets.get(str(row.get("created_at") or "")[:7])
        kind = row.get("kind")
        if bucket and kind in ("aprovado_interno", "aprovado_cliente"): bucket["approved"] += 1
        if bucket and kind == "ajuste_interno": bucket["internal_changes"] += 1
        if bucket and kind == "ajuste_cliente": bucket["client_changes"] += 1
    return {"months": list(buckets.values()), "definition": "Eventos registrados; não representa itens únicos."}


async def _profile_suggestion(client_id: str) -> Optional[Dict[str, Any]]:
    from .studio_brand_brain import pending_suggestion
    row = await pending_suggestion(client_id)
    return {"id": row["id"], "month": row.get("month")} if row else None


def _alerts(blocks: Dict[str, Any], *, agency: bool) -> List[Dict[str, str]]:
    """O que precisa de atenção, só a partir do que os blocos trouxeram (nada estimado)."""
    out: List[Dict[str, str]] = []
    cal = blocks.get("calendar") or {}
    if cal.get("waiting_client"):
        out.append({"level": "atencao", "module": "approval", "text": f"{cal['waiting_client']} post(s) com o cliente há mais de 2 dias sem resposta."})
    if agency and cal.get("off_brand"):
        out.append({"level": "atencao", "module": "calendar", "text": f"{len(cal['off_brand'])} post(s) com alerta de fidelidade à marca (oferta, número ou urgência sem dado)."})
    for ch in (blocks.get("media") or {}).get("channels") or []:
        pace = ch.get("pace")
        if pace and pace > 1.15:
            out.append({"level": "atencao", "module": "media", "text": f"{ch['label']}: no ritmo atual, gasta {round((pace - 1) * 100)}% acima da verba do mês."})
        elif pace and pace < 0.8 and (blocks.get("media") or {}).get("elapsed_days", 0) >= 7:
            out.append({"level": "info", "module": "media", "text": f"{ch['label']}: investindo {round((1 - pace) * 100)}% abaixo do planejado."})
    clip = (blocks.get("clipping") or {}).get("week") or {}
    if (clip.get("current") or {}).get("negativo"):
        out.append({"level": "atencao", "module": "clipping", "text": f"{clip['current']['negativo']} notícia(s) negativa(s) sobre a marca nesta semana."})
    if agency:
        for camp in blocks.get("campaigns") or []:
            if camp.get("status") != "arquivada" and not camp.get("posts_no_calendario"):
                out.append({"level": "info", "module": "campaigns", "text": f"Campanha “{camp['name']}” ainda não tem posts no Calendário."})
    if agency and blocks.get("profile_suggestion"):
        out.append({"level": "info", "module": "calendar", "text": "Nova sugestão do perfil da marca (IA) esperando revisão: Calendário → Perfil da marca."})
    tasks = blocks.get("tasks") or {}
    if tasks.get("late"):
        out.append({"level": "atencao", "module": "tasks", "text": f"{tasks['late']} tarefa(s) atrasada(s)."})
    if tasks.get("stalled"):
        out.append({"level": "info", "module": "tasks", "text": f"{tasks['stalled']} demanda(s) aberta(s) sem atualização há mais de 7 dias."})
    if tasks.get("rework"):
        out.append({"level": "info", "module": "tasks", "text": f"{tasks['rework']} demanda(s) aberta(s) com mais de uma rodada de aprovação."})
    return out[:10]


async def build_central(client_id: str, month: date, *, agency: bool) -> Dict[str, Any]:
    names = ["numbers", "calendar", "media", "social", "clipping", "tasks", "approval_history"] + (["campaigns", "profile_suggestion"] if agency else [])
    calls = [_safe("numeros", lambda: _numbers(client_id, month)),
             _safe("calendario", lambda: _calendar(client_id, month, agency=agency)),
             _safe("midia", lambda: _media(client_id, month)),
             _safe("social", lambda: _social(client_id, month)),
             _safe("clipping", lambda: _clipping(client_id)),
             _safe("tarefas", lambda: _tasks(client_id, agency=agency)),
             _safe("historico_aprovacoes", lambda: _approval_history(client_id, month))]
    if agency:
        calls.append(_safe("campanhas", lambda: _campaigns(client_id)))
        calls.append(_safe("sugestao_perfil", lambda: _profile_suggestion(client_id)))
    results = await asyncio.gather(*calls)
    blocks = dict(zip(names, results))
    return {"month": month.isoformat(), "agency": agency, **blocks, "alerts": _alerts(blocks, agency=agency)}
