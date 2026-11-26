"""Alertas da Mídia On: avisa a equipe sem ninguém precisar abrir a tela.

Roda pelo Relógio dos jobs (``media-alerts``, de hora em hora), fora do Render. Para cada campanha que a Mídia On
colocou no Meta, uma chamada traz o status e os números dos últimos 3 dias; outra, os números desde o início.
Cada alerta vira UMA tarefa (alta prioridade, só a equipe vê) no Chat de tarefas da marca, e o mesmo alerta da mesma
campanha não se repete no mesmo dia (tabela media_alerts, única por dia).

Alertas:
- reprovada: a Meta reprovou o anúncio;
- com_problema: a Meta marcou a campanha com problema (pagamento, política, entrega);
- sem_entrega: está ligada, mas não teve impressão nos últimos 3 dias;
- custo_alto: custo por resultado dos últimos 3 dias 50% acima do custo desde o início (com gasto relevante);
- fim_proximo: ligada e termina em até 2 dias.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .ig_supabase import sb_insert, sb_select

ALERTS = "media_alerts"
TASKS = "studio_tasks"
COST_JUMP = 1.5
MIN_SPEND_3D = 20.0


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _brl(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _results(line: Dict[str, Any], wanted: tuple, objective: str) -> float:
    if objective == "alcance":
        return _num(line.get("reach"))
    actions = {a.get("action_type"): _num(a.get("value")) for a in line.get("actions") or []}
    return next((actions[k] for k in wanted if k in actions), 0.0)


def detect(name: str, payload: Dict[str, Any], status: str, recent: Dict[str, Any], total: Dict[str, Any],
           wanted: tuple, today: date) -> List[Dict[str, str]]:
    """Regras puras (testáveis): devolve [{kind, message}]."""
    out: List[Dict[str, str]] = []
    objective = payload.get("objective") or ""
    if status == "DISAPPROVED":
        out.append({"kind": "reprovada", "message": f"\"{name}\": a Meta reprovou o anúncio. Veja o motivo no Gerenciador e troque a arte ou o texto."})
    elif status == "WITH_ISSUES":
        out.append({"kind": "com_problema", "message": f"\"{name}\": a Meta marcou a campanha com problema (pagamento, política ou entrega)."})
    if status != "ACTIVE":
        return out
    start = str(payload.get("start_date") or "")[:10]
    if start and start <= (today - timedelta(days=3)).isoformat() and _num(recent.get("impressions")) == 0:
        out.append({"kind": "sem_entrega", "message": f"\"{name}\" está ligada, mas não apareceu para ninguém nos últimos 3 dias. "
                                                      "Confira público, verba e se o anúncio foi aprovado."})
    spend3, spend_all = _num(recent.get("spend")), _num(total.get("spend"))
    res3, res_all = _results(recent, wanted, objective), _results(total, wanted, objective)
    if spend3 >= MIN_SPEND_3D and res_all and spend_all > spend3:
        avg = spend_all / res_all
        now_cost = spend3 / res3 if res3 else None
        if now_cost is None or now_cost > avg * COST_JUMP:
            now_text = _brl(now_cost) if now_cost else f"nenhum resultado com {_brl(spend3)} gastos"
            out.append({"kind": "custo_alto", "message": f"\"{name}\": custo por resultado subiu nos últimos 3 dias ({now_text}) "
                                                        f"contra {_brl(avg)} desde o início. Vale trocar o criativo ou o público."})
    end = str(payload.get("end_date") or "")[:10]
    if end and today.isoformat() <= end <= (today + timedelta(days=2)).isoformat():
        out.append({"kind": "fim_proximo", "message": f"\"{name}\" termina em {end[8:10]}/{end[5:7]}. Se estiver indo bem, estenda a data."})
    return out


async def check_client(client_id: str, today: Optional[date] = None) -> int:
    from . import meta_ad_publisher as pub
    today = today or (datetime.now(timezone.utc) - timedelta(hours=3)).date()  # dia em São Paulo
    drafts = [d for d in await pub.list_drafts(client_id) if (d.get("meta_ids") or {}).get("campaign_id")]
    if not drafts:
        return 0
    try:
        account = await pub._ad_account(client_id)
    except Exception:  # noqa: BLE001 - sem conta conectada, nada a alertar
        return 0
    fields = "spend,impressions,reach,actions"

    async def one(d: Dict[str, Any]) -> List[Dict[str, str]]:
        cid = d["meta_ids"]["campaign_id"]
        try:
            head = await pub._graph("GET", f"/{cid}", token=account["token"],
                                    params={"fields": f"name,effective_status,insights.date_preset(last_3d){{{fields}}}"})
            full = await pub._graph("GET", f"/{cid}/insights", token=account["token"], params={"fields": fields, "date_preset": "maximum"})
        except Exception:  # noqa: BLE001
            return []
        recent = ((head.get("insights") or {}).get("data") or [{}])[0] or {}
        total = (full.get("data") or [{}])[0] or {}
        payload = d["payload"]
        name = payload.get("name") or head.get("name") or "Campanha"
        found = detect(name, payload, str(head.get("effective_status") or "").upper(), recent, total,
                       pub.RESULT_ACTIONS.get(payload.get("objective"), ()), today)
        return [{**f, "ref_id": d["id"]} for f in found]

    created = 0
    for found in await asyncio.gather(*(one(d) for d in drafts)):
        for alert in found:
            try:
                row = await sb_insert(ALERTS, {"client_id": client_id, "ref_id": alert["ref_id"], "kind": alert["kind"],
                                               "message": alert["message"], "day": today.isoformat()})
            except Exception:  # noqa: BLE001 - já avisado hoje (única por dia) ou tabela pendente
                continue
            if not row:
                continue
            await sb_insert(TASKS, {"client_id": client_id, "title": f"Alerta Mídia On: {alert['message']}"[:200],
                                    "notes": alert["message"] + "\n\nAberto automaticamente pelos alertas da Mídia On.",
                                    "status": "pending", "priority": "high", "due_date": today.isoformat(),
                                    "visible_to_client": False, "needs_client_approval": False}, returning="minimal")
            created += 1
    return created


async def run_all() -> Dict[str, Any]:
    from .meta_ad_publisher import TABLE
    rows = await sb_select(TABLE, select="client_id", filters={"status": "eq.publicada"}, limit=2000)
    clients = sorted({str(r["client_id"]) for r in rows if r.get("client_id")})
    total = {"clients": len(clients), "alerts": 0, "errors": 0}
    for cid in clients:
        try:
            total["alerts"] += await check_client(cid)
        except Exception as exc:  # noqa: BLE001
            total["errors"] += 1
            print(f"[media_alerts] failed error_type={type(exc).__name__}")
    return total
