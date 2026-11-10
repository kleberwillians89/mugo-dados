"""Mídia On: no começo de cada mês, uma estratégia pronta por objetivo para cada empresa.

Objetivos: vendas, leads, tráfego, alcance, retenção de clientes e remarketing. Cada uma usa os dados
dos últimos 90 dias (Meta, Google, loja), a meta do mês, o perfil e o conhecimento da marca e o calendário
(build_strategy) e ganha a leitura da IA (narrative). Fica gravada no histórico do mês: a equipe abre
o Mídia On, escolhe o objetivo, valida, ajusta o que não concordar e salva o plano.

Rodar de novo no mesmo mês não duplica: objetivo que já tem estratégia gerada no mês é pulado.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from .ig_supabase import sb_select
from .media_plan import list_strategies, record_strategy
from .media_strategy import OBJECTIVES, build_strategy, narrative

SAO_PAULO = ZoneInfo("America/Sao_Paulo")


async def _clients() -> List[str]:
    try:
        rows = await sb_select("clients", select="id,status", limit=500)
    except Exception:  # noqa: BLE001 — schema sem status
        rows = await sb_select("clients", select="id", limit=500)
    return sorted(str(r["id"]) for r in rows if r.get("id") and str(r.get("status") or "active") not in ("inactive", "archived", "deleted"))


async def generate_for_client(client_id: str, month: str, *, objectives: Optional[List[str]] = None) -> Dict[str, Any]:
    existing = {str(s.get("objective")) for s in await list_strategies(client_id, month)}
    done, skipped, failed = [], [], []
    for objective in objectives or list(OBJECTIVES):
        if objective in existing:
            skipped.append(objective)
            continue
        try:
            strategy = await build_strategy(client_id, month=month, objective=objective, distribution="equilibrado")
            try:
                strategy["narrative"] = await narrative(client_id, strategy)
            except Exception as exc:  # noqa: BLE001 — números valem sem a leitura da IA
                strategy["narrative"] = None
                print(f"[media][monthly] narrative client_id={client_id} objective={objective} failed={getattr(exc, 'code', type(exc).__name__)}")
            strategy["auto_generated"] = True
            record = await record_strategy(client_id, strategy, objective=objective, margin=None, custom_budget=None, user_id=None)
            (done if record.get("saved") else failed).append(objective)
        except Exception as exc:  # noqa: BLE001 — um objetivo não para os outros
            failed.append(objective)
            print(f"[media][monthly] client_id={client_id} objective={objective} failed={getattr(exc, 'code', type(exc).__name__)}")
    return {"client_id": client_id, "created": done, "skipped": skipped, "failed": failed}


async def run_monthly(client_id: Optional[str] = None, month: Optional[str] = None) -> Dict[str, Any]:
    month = month or datetime.now(SAO_PAULO).strftime("%Y-%m")
    clients = [client_id] if client_id else await _clients()
    results = []
    for cid in clients:
        try:
            results.append(await generate_for_client(cid, month))
        except Exception as exc:  # noqa: BLE001 — uma empresa não para as outras
            results.append({"client_id": cid, "created": [], "skipped": [], "failed": ["all"], "error": type(exc).__name__})
    return {"month": month, "clients": len(clients),
            "created": sum(len(r["created"]) for r in results), "failed": sum(len(r["failed"]) for r in results), "results": results}
