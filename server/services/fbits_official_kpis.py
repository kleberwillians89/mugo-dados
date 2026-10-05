"""KPIs executivos OFICIAIS da FBITS/Wake (receita, pedidos, ticket médio).

Fonte: GET /dashboard/faturamento da própria loja, consultado com o token da
conexão do tenant. São os mesmos indicadores do painel FBITS, por isso NÃO são
reconstruídos a partir das situações dos pedidos.

Os demais números do dashboard (clientes, aguardando, cancelados, descontos,
frete, tendência, produtos) continuam derivados de GET /pedidos — ver
fbits_reporting.

Período: a API recebe só datas (aaaa-mm-dd), dias inteiros no calendário da
loja; o período do dashboard já é um intervalo de datas inclusivo, então é
enviado como está — sem conversão de fuso nem hora de fim de dia. O período
anterior vai no comparativo da MESMA chamada, para comparar conceitos iguais.

Cache em memória por tenant (sucesso: 5 min). Falha não é cacheada como
número: fica em espera curta (429: Retry-After) para não insistir num token
limitado — 5 requisições com o limite esgotado bloqueiam o token por 1 hora.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional, Tuple

from .fbits_client import FbitsApiError, FbitsClient
from .fbits_connections import load_fbits_connection, fbits_cooldown_remaining
from .ig_supabase import sb_update
from datetime import datetime, timedelta, timezone
from .generic_connections import get_connection
from .runtime_cache import get_cached_or_load, invalidate_namespace

OFFICIAL_KPI_SOURCE = "fbits_dashboard"
FALLBACK_KPI_SOURCE = "fbits_orders_fallback"
CACHE_TTL_SECONDS = 300
FAILURE_BACKOFF_SECONDS = 30
RATE_LIMIT_BACKOFF_SECONDS = 60
OFFICIAL_TIMEOUT_SECONDS = 15.0

# (client_id, chave do período) -> (expira_em, código do erro)
_FAILURES: Dict[Tuple[str, str], Tuple[float, str]] = {}


def _default_client_factory(token: str) -> FbitsClient:
    # Leitura no carregamento do dashboard: falha rápida (sem retentativa) e
    # fallback identificado, em vez de segurar a tela por várias tentativas.
    return FbitsClient(token, timeout=OFFICIAL_TIMEOUT_SECONDS, server_error_retries=0)


client_factory = _default_client_factory


class OfficialKpisUnavailable(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _s(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _number(payload: Dict[str, Any], key: str) -> Optional[float]:
    value = payload.get(key)
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        return float(_s(value).replace(",", "."))
    except ValueError:
        return None


def parse_revenue_indicators(payload: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
    """indicadorReceita/Pedido/TicketMedio (+ Comparativo) -> current/previous.

    O ticket é o da própria FBITS (não é recalculado). Sem receita ou pedidos
    numéricos a resposta é inválida — nunca vira zero.
    """
    def block(suffix: str) -> Optional[Dict[str, float]]:
        revenue = _number(payload, f"indicadorReceita{suffix}")
        orders = _number(payload, f"indicadorPedido{suffix}")
        ticket = _number(payload, f"indicadorTicketMedio{suffix}")
        if revenue is None or orders is None:
            return None
        return {
            "receita_oficial": round(revenue, 2),
            "pedidos": int(round(orders)),
            "ticket_medio": round(ticket, 2) if ticket is not None else (round(revenue / orders, 2) if orders else 0.0),
        }

    current = block("")
    if current is None:
        raise OfficialKpisUnavailable("FBITS_DASHBOARD_INVALID_RESPONSE")
    return {"current": current, "previous": block("Comparativo")}


def _cache_namespace(client_id: str) -> str:
    return f"fbits_official_kpis:{client_id}"


async def invalidate_official_kpis(client_id: str) -> None:
    """Chamado ao agendar e ao concluir a sincronização da empresa. Mantém a
    espera de 429 (insistir pioraria o bloqueio do token)."""
    await invalidate_namespace(_cache_namespace(client_id))
    for key in [key for key, (_until, code) in _FAILURES.items() if key[0] == client_id and code != "FBITS_RATE_LIMITED"]:
        _FAILURES.pop(key, None)


async def _tenant_client(client_id: str) -> FbitsClient:
    row = await load_fbits_connection(client_id)
    if not row or _s(row.get("status")).lower() in {"disconnected", "not_configured"} or row.get("disconnected_at"):
        raise OfficialKpisUnavailable("FBITS_NOT_CONNECTED")
    if fbits_cooldown_remaining(row):
        raise OfficialKpisUnavailable("FBITS_RATE_LIMITED")
    full = await get_connection(client_id, _s(row.get("id")), include_token=True)
    try:
        token = _s(json.loads(full.get("_token") or "{}").get("token"))
    except (TypeError, ValueError):
        token = ""
    if not token:
        raise OfficialKpisUnavailable("FBITS_REAUTH_REQUIRED")
    return client_factory(token)


async def fetch_official_kpis(
    *, client_id: str, start: str, end: str, previous_start: str, previous_end: str,
) -> Dict[str, Any]:
    """Indicadores oficiais do período e do período anterior, para o tenant.

    Levanta OfficialKpisUnavailable(code) quando não há número oficial; quem
    chama decide o fallback e o identifica no payload.
    """
    key = f"{start}:{end}:{previous_start}:{previous_end}"
    failure = _FAILURES.get((client_id, key))
    if failure and failure[0] > time.monotonic():
        raise OfficialKpisUnavailable(failure[1])

    async def load() -> Dict[str, Any]:
        client = await _tenant_client(client_id)
        try:
            payload = await client.revenue_indicators(
                start=start, end=end, compare_start=previous_start, compare_end=previous_end,
            )
        except FbitsApiError as exc:
            if exc.code == "FBITS_RATE_LIMITED":
                wait = max(60, exc.retry_after or 3600)
                row = await load_fbits_connection(client_id)
                if row:
                    metadata = dict(row.get("metadata") or {})
                    metadata["rate_limit_until"] = (datetime.now(timezone.utc) + timedelta(seconds=wait)).isoformat()
                    await sb_update("integration_connections", patch={"metadata": metadata}, filters={"client_id": f"eq.{client_id}", "id": f"eq.{row['id']}"})
            else:
                wait = FAILURE_BACKOFF_SECONDS
            _FAILURES[(client_id, key)] = (time.monotonic() + wait, exc.code)
            raise OfficialKpisUnavailable(exc.code) from None
        return parse_revenue_indicators(payload)

    try:
        value, cache_hit = await get_cached_or_load(
            namespace=_cache_namespace(client_id), key=key, ttl_seconds=CACHE_TTL_SECONDS, loader=load,
        )
    except OfficialKpisUnavailable as exc:
        print(f"[fbits][official_kpis] client_id={client_id} start={start} end={end} status=unavailable code={exc.code}")
        raise
    except Exception as exc:  # Supabase/cripto: nunca vira número falso
        print(f"[fbits][official_kpis] client_id={client_id} start={start} end={end} status=error error_type={exc.__class__.__name__}")
        raise OfficialKpisUnavailable("FBITS_DASHBOARD_ERROR") from None
    _FAILURES.pop((client_id, key), None)
    current = value["current"]
    print(
        f"[fbits][official_kpis] pid={os.getpid()} client_id={client_id} start={start} end={end} status=ok cache_hit={str(cache_hit).lower()} "
        f"receita={current['receita_oficial']} pedidos={current['pedidos']} ticket={current['ticket_medio']}"
    )
    return value
