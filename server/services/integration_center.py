"""Central de saúde das integrações (Administração, só a equipe Mugô).

Uma tela com todas as empresas e todas as fontes: o que está sincronizado, atrasado, sincronizando, com erro ou
pedindo reconexão, quando foi o último sucesso, quantas falhas na semana e o que fazer em cada caso.

Não recalcula nada por conta própria: o estado de cada fonte vem de ``data_health.client_data_health`` (a mesma
régua que o painel de cada empresa já usa, com as janelas esperadas de cada provedor). Aqui só junta todas as
empresas, soma as falhas da semana (``cron_job_runs``) e a fila de WhatsApp (``automation_outbox``) e traduz o
estado em uma ação. Somente leitura.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from .client_lifecycle import CRON_OPERATIONAL_STATUSES
from .data_health import client_data_health, job_provider
from .ig_supabase import sb_select

SP = ZoneInfo("America/Sao_Paulo")
PARALLEL = 4
WINDOW_DAYS = 7
PROVIDER_LABEL = {
    "meta_ads": "Meta Ads", "instagram": "Instagram", "instagram_content": "Instagram (posts)", "ga4": "GA4",
    "google_ads": "Google Ads", "shopify": "Shopify", "fbits": "FBITS", "fbits_official": "FBITS (indicadores oficiais)",
}
# Do mais grave para o mais tranquilo: a tela ordena por aqui.
SEVERITY = {"reauth_required": 0, "attention": 1, "stale": 2, "updating": 3, "no_data": 4, "synced": 5, "not_connected": 6}
ACTION = {
    "reauth_required": ("reconnect", "Reconectar em Integrações: o acesso expirou ou foi revogado."),
    "attention": ("review", "Abrir a integração e ver o erro; depois rodar a sincronização de novo."),
    "stale": ("sync", "Atrasada: rodar a sincronização agora e conferir se o agendamento está ativo."),
    "updating": ("wait", "Sincronizando agora."),
    "no_data": ("check", "Conectada, mas sem dado no período: conferir a conta selecionada."),
    "synced": ("none", "Tudo certo."),
    "not_connected": ("none", "Não conectada."),
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def row_for(source: Dict[str, Any], *, failures: int) -> Dict[str, Any]:
    """Uma fonte de uma empresa, pronta para a tela."""
    state = source.get("state") or "no_data"
    if not source.get("connected"):
        state = "not_connected"
    action, hint = ACTION.get(state, ACTION["attention"])
    return {
        "provider": source.get("provider"), "label": PROVIDER_LABEL.get(str(source.get("provider")), source.get("provider")),
        "state": state, "severity": SEVERITY.get(state, 1), "action": action, "hint": hint,
        "error_code": source.get("error_code"), "last_success_at": source.get("last_successful_sync_at"),
        "last_attempt_at": source.get("last_attempt_at"), "last_data_at": source.get("last_data_at"),
        "coverage_end": source.get("coverage_end"), "failures_7d": failures,
    }


def summarize(companies: List[Dict[str, Any]]) -> Dict[str, int]:
    rows = [s for c in companies for s in c["sources"] if s["state"] != "not_connected"]
    count = lambda *states: sum(1 for s in rows if s["state"] in states)  # noqa: E731
    return {
        "connections": len(rows), "ok": count("synced"), "updating": count("updating"),
        "problems": count("reauth_required", "attention"), "stale": count("stale"), "no_data": count("no_data"),
        "reauth": count("reauth_required"), "failures_7d": sum(s["failures_7d"] for s in rows),
        "companies_with_problem": sum(1 for c in companies if c["worst"] <= SEVERITY["stale"]),
    }


async def _companies() -> List[Dict[str, Any]]:
    rows = await sb_select("clients", select="id,name,status", order="name.asc", limit=1000)
    return [r for r in rows if str(r.get("status") or "").lower() in CRON_OPERATIONAL_STATUSES]


async def _failures(since: str) -> Dict[tuple, int]:
    rows = await sb_select("cron_job_runs", select="client_id,job_name,status", limit=5000,
                           filters={"status": "eq.error", "started_at": f"gte.{since}"})
    out: Dict[tuple, int] = {}
    for r in rows:
        provider = job_provider(r)
        if r.get("client_id") and provider:
            key = (str(r["client_id"]), provider)
            out[key] = out.get(key, 0) + 1
    return out


async def _outbox() -> Dict[str, Dict[str, int]]:
    """Fila do WhatsApp por empresa: o que está esperando e o que falhou."""
    rows = await sb_select("automation_outbox", select="client_id,status", limit=5000,
                           filters={"status": "in.(agendado,processando,falhou)"})
    out: Dict[str, Dict[str, int]] = {}
    for r in rows:
        bucket = out.setdefault(str(r.get("client_id") or ""), {"waiting": 0, "failed": 0})
        bucket["failed" if r.get("status") == "falhou" else "waiting"] += 1
    return out


async def overview(*, client_id: Optional[str] = None) -> Dict[str, Any]:
    now = _now()
    today = now.astimezone(SP).date()
    start, end = (today - timedelta(days=WINDOW_DAYS - 1)).isoformat(), today.isoformat()
    since = (now - timedelta(days=WINDOW_DAYS)).isoformat()
    companies = await _companies()
    if client_id:
        companies = [c for c in companies if c["id"] == client_id]
    failures, outbox = await asyncio.gather(_safe(_failures(since), {}), _safe(_outbox(), {}))
    gate = asyncio.Semaphore(PARALLEL)

    async def one(company: Dict[str, Any]) -> Dict[str, Any]:
        async with gate:
            try:
                health = await client_data_health(company["id"], start, end)
                error = None
            except Exception as exc:  # noqa: BLE001 — uma empresa ilegível não derruba a Central
                print(f"[integration_center] health_failed client_id={company['id']} {type(exc).__name__}")
                health, error = {"sources": []}, "Não foi possível ler a saúde desta empresa agora."
        sources = [row_for(s, failures=failures.get((company["id"], str(s.get("provider"))), 0)) for s in health["sources"]]
        sources.sort(key=lambda s: (s["severity"], s["label"]))
        queue = outbox.get(company["id"], {"waiting": 0, "failed": 0})
        connected = [s for s in sources if s["state"] != "not_connected"]
        worst = min((s["severity"] for s in connected), default=SEVERITY["not_connected"])
        if error:
            worst = SEVERITY["attention"]
        return {"id": company["id"], "name": company.get("name") or company["id"], "status": company.get("status"),
                "sources": sources, "worst": worst, "queue": queue, "error": error}

    result = await asyncio.gather(*(one(c) for c in companies))
    result.sort(key=lambda c: (c["worst"], str(c["name"]).lower()))
    return {"generated_at": now.isoformat(), "window": {"start": start, "end": end}, "summary": summarize(result),
            "queue": {"waiting": sum(c["queue"]["waiting"] for c in result), "failed": sum(c["queue"]["failed"] for c in result)},
            "companies": result}


async def _safe(awaitable: Any, fallback: Any) -> Any:
    try:
        return await awaitable
    except Exception as exc:  # noqa: BLE001
        print(f"[integration_center] read_failed {type(exc).__name__}")
        return fallback
