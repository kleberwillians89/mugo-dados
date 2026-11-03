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


async def _numbers(client_id: str, month: date) -> Optional[Dict[str, Any]]:
    from .studio_messages import _snapshot, _store_sales, _value
    start, end = _month_bounds(month)
    if end < start:
        return {"start": start.isoformat(), "end": None}
    snap = await _snapshot(client_id, start, end)
    sales = await _store_sales(client_id, start, end, snap["metrics"])
    spend = _value(snap["metrics"], "investment")
    revenue = sales.get("revenue")
    return {"start": start.isoformat(), "end": end.isoformat(), "investimento": spend, "faturamento": revenue,
            "pedidos": sales.get("orders"), "retorno": round(revenue / spend, 2) if revenue is not None and spend else None,
            "vendas_midia_paga": sales.get("paid_revenue"), "melhor_campanha": sales.get("top_campaign")}


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
    from .crm_bridge import list_client_tasks, list_tasks
    data = await (list_tasks(client_id) if agency else list_client_tasks(client_id))
    if not data.get("available"):
        return {"available": False, "reason": data.get("reason")}
    tasks = data.get("tasks") or []
    today = datetime.now(SAO_PAULO).date().isoformat()
    open_tasks = [t for t in tasks if t.get("status") in ("pending", "in_progress")]
    return {"available": True, "open": len(open_tasks), "late": sum(1 for t in open_tasks if t.get("due_date") and t["due_date"] < today),
            "next": [{"title": t.get("title"), "due_date": t.get("due_date"), "status": t.get("status")}
                     for t in sorted(open_tasks, key=lambda t: t.get("due_date") or "9999")[:4]]}


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
    tasks = blocks.get("tasks") or {}
    if tasks.get("late"):
        out.append({"level": "atencao", "module": "tasks", "text": f"{tasks['late']} tarefa(s) atrasada(s)."})
    return out[:10]


async def build_central(client_id: str, month: date, *, agency: bool) -> Dict[str, Any]:
    names = ["numbers", "calendar", "media", "clipping", "tasks"] + (["campaigns"] if agency else [])
    calls = [_safe("numeros", lambda: _numbers(client_id, month)),
             _safe("calendario", lambda: _calendar(client_id, month, agency=agency)),
             _safe("midia", lambda: _media(client_id, month)),
             _safe("clipping", lambda: _clipping(client_id)),
             _safe("tarefas", lambda: _tasks(client_id, agency=agency))]
    if agency:
        calls.append(_safe("campanhas", lambda: _campaigns(client_id)))
    results = await asyncio.gather(*calls)
    blocks = dict(zip(names, results))
    return {"month": month.isoformat(), "agency": agency, **blocks, "alerts": _alerts(blocks, agency=agency)}
