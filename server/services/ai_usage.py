"""
Consumo de IA por cliente: cada chamada à OpenAI grava tokens de entrada/saída, modelo, recurso
(schema/tela) e, se falhou, o código do erro (ex.: http_429:insufficient_quota = sem crédito).

* Gravar nunca derruba a chamada de IA: falha ao registrar só vira log.
* Custo é ESTIMATIVA em dólar pela tabela de preço por 1 milhão de tokens (sobrescreva com
  AI_PRICES_JSON='{"gpt-4.1-mini": [0.4, 1.6]}'). A fatura oficial continua sendo a da OpenAI.
* Só metadados: nunca prompt, resposta ou chave.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

TABLE = "ai_usage_events"

# USD por 1 milhão de tokens: (entrada, saída). Preços públicos da OpenAI; confira na fatura.
DEFAULT_PRICES: Dict[str, tuple] = {
    "gpt-4.1": (2.00, 8.00), "gpt-4.1-mini": (0.40, 1.60), "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4o": (2.50, 10.00), "gpt-4o-mini": (0.15, 0.60),
    "gpt-5": (1.25, 10.00), "gpt-5-mini": (0.25, 2.00), "gpt-5-nano": (0.05, 0.40),
    "o4-mini": (1.10, 4.40), "o3": (2.00, 8.00),
}
QUOTA_CODES = ("insufficient_quota", "billing_hard_limit_reached")
_pending: set = set()


def prices() -> Dict[str, tuple]:
    table = dict(DEFAULT_PRICES)
    try:
        extra = json.loads(os.getenv("AI_PRICES_JSON") or "{}")
        for model, pair in (extra or {}).items():
            table[str(model)] = (float(pair[0]), float(pair[1]))
    except (ValueError, TypeError, IndexError, KeyError):
        pass
    return table


def price_for(model: str) -> Optional[tuple]:
    """Preço do modelo; aceita versões datadas (gpt-4.1-mini-2025-04-14 → gpt-4.1-mini)."""
    table = prices()
    name = (model or "").lower()
    if name in table:
        return table[name]
    for key in sorted(table, key=len, reverse=True):
        if name.startswith(key):
            return table[key]
    return None


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> Optional[float]:
    price = price_for(model)
    if not price:
        return None
    return round((input_tokens * price[0] + output_tokens * price[1]) / 1_000_000, 6)


def usage_from(body: Any) -> Dict[str, int]:
    usage = (body or {}).get("usage") if isinstance(body, dict) else None
    usage = usage or {}
    inp = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
    out = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
    total = int(usage.get("total_tokens") or inp + out)
    return {"input_tokens": inp, "output_tokens": out, "total_tokens": total}


def _client(client_id: Optional[str]) -> Optional[str]:
    if client_id:
        return str(client_id)[:120]
    try:
        from .tenant import _REQUEST_CLIENT
        return _REQUEST_CLIENT.get()
    except Exception:  # noqa: BLE001
        return None


def build_row(*, feature: str, model: str, client_id: Optional[str] = None, body: Any = None,
              error_code: Optional[str] = None) -> Dict[str, Any]:
    use = usage_from(body) if body is not None else {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    return {"client_id": _client(client_id), "feature": (feature or "ia")[:80], "model": (model or "")[:80],
            **use, "cost_usd": estimate_cost(model, use["input_tokens"], use["output_tokens"]),
            "status": "erro" if error_code else "ok", "error_code": (error_code or None) and str(error_code)[:80]}


async def _insert(row: Dict[str, Any]) -> None:
    try:
        from .ig_supabase import sb_insert
        await sb_insert(TABLE, row)
    except Exception as exc:  # noqa: BLE001 — registrar consumo nunca derruba a IA
        print(f"[ai_usage] record_failed feature={row.get('feature')} err={type(exc).__name__}")


def track(*, feature: str, model: str, client_id: Optional[str] = None, body: Any = None,
          error_code: Optional[str] = None) -> None:
    """Registra em segundo plano (não espera o banco)."""
    row = build_row(feature=feature, model=model, client_id=client_id, body=body, error_code=error_code)
    try:
        task = asyncio.get_running_loop().create_task(_insert(row))
    except RuntimeError:
        return
    _pending.add(task)
    task.add_done_callback(_pending.discard)


def track_response(response: Any, *, feature: str, model: str, client_id: Optional[str] = None) -> None:
    """Atalho para a resposta httpx da OpenAI: sucesso grava tokens; erro grava o código (status + tipo)."""
    status = getattr(response, "status_code", 0)
    try:
        body = response.json()
    except Exception:  # noqa: BLE001
        body = None
    if status >= 400:
        err = (body or {}).get("error") if isinstance(body, dict) else None
        code = str((err.get("code") or err.get("type") or "") if isinstance(err, dict) else "").strip()[:60]
        track(feature=feature, model=model, client_id=client_id, error_code=f"http_{status}" + (f":{code}" if code else ""))
    else:
        track(feature=feature, model=model, client_id=client_id, body=body)


# ---------------------------------------------------------------- relatório

def _day(value: Any) -> str:
    return str(value or "")[:10]


def aggregate(rows: List[Dict[str, Any]], names: Dict[str, str]) -> Dict[str, Any]:
    clients: Dict[str, Dict[str, Any]] = {}
    features: Dict[str, Dict[str, Any]] = {}
    days: Dict[str, Dict[str, Any]] = {}
    totals = {"calls": 0, "errors": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cost_usd": 0.0}
    last_error: Optional[Dict[str, Any]] = None
    unpriced: set = set()

    def add(bucket: Dict[str, Any], row: Dict[str, Any]) -> None:
        bucket["calls"] += 1
        bucket["errors"] += 1 if row.get("status") == "erro" else 0
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            bucket[key] += int(row.get(key) or 0)
        bucket["cost_usd"] = round(bucket["cost_usd"] + float(row.get("cost_usd") or 0), 6)

    empty = lambda: {"calls": 0, "errors": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cost_usd": 0.0}  # noqa: E731
    for row in rows:
        cid = row.get("client_id") or "_sem_empresa"
        c = clients.setdefault(cid, {"client_id": row.get("client_id"), "name": names.get(cid) or ("Sem empresa (tarefas internas)" if cid == "_sem_empresa" else cid),
                                     **empty(), "features": {}, "last_error": None, "last_call": None})
        add(c, row)
        add(c["features"].setdefault(row.get("feature") or "ia", empty()), row)
        add(features.setdefault(row.get("feature") or "ia", empty()), row)
        add(days.setdefault(_day(row.get("created_at")), empty()), row)
        add(totals, row)
        if not c["last_call"] or str(row.get("created_at")) > str(c["last_call"]):
            c["last_call"] = row.get("created_at")
        if row.get("status") == "erro":
            err = {"code": row.get("error_code"), "at": row.get("created_at"), "feature": row.get("feature"), "client": c["name"]}
            if not c["last_error"] or str(err["at"]) > str(c["last_error"]["at"]):
                c["last_error"] = err
            if not last_error or str(err["at"]) > str(last_error["at"]):
                last_error = err
        if row.get("status") == "ok" and row.get("cost_usd") is None and row.get("model"):
            unpriced.add(row["model"])
    ordered = sorted(clients.values(), key=lambda c: (-c["total_tokens"], c["name"]))
    for c in ordered:
        c["features"] = [{"feature": k, **v} for k, v in sorted(c["features"].items(), key=lambda kv: -kv[1]["total_tokens"])]
    quota = bool(last_error and any(code in str(last_error.get("code") or "") for code in QUOTA_CODES))
    return {"totals": totals, "clients": ordered,
            "features": [{"feature": k, **v} for k, v in sorted(features.items(), key=lambda kv: -kv[1]["total_tokens"])],
            "daily": [{"date": k, **v} for k, v in sorted(days.items())],
            "last_error": last_error, "quota_exhausted": quota, "unpriced_models": sorted(unpriced)}


async def report(*, start: Optional[str] = None, end: Optional[str] = None) -> Dict[str, Any]:
    from .ig_supabase import sb_select
    today = datetime.now(timezone.utc).date()
    try:
        first = date.fromisoformat(start) if start else today.replace(day=1)
        last = date.fromisoformat(end) if end else today
    except ValueError:
        first, last = today.replace(day=1), today
    if last < first:
        first, last = last, first
    if (last - first).days > 400:
        first = last - timedelta(days=400)
    rows: List[Dict[str, Any]] = []
    offset, page = 0, 1000
    while True:
        chunk = await sb_select(TABLE, select="client_id,feature,model,input_tokens,output_tokens,total_tokens,cost_usd,status,error_code,created_at",
                                filters={"created_at": f"gte.{first.isoformat()}T00:00:00Z", "and": f"(created_at.lt.{(last + timedelta(days=1)).isoformat()}T00:00:00Z)"},
                                order="created_at.asc", limit=page, offset=offset)
        rows.extend(chunk or [])
        if not chunk or len(chunk) < page or len(rows) >= 50_000:
            break
        offset += page
    ids = sorted({r["client_id"] for r in rows if r.get("client_id")})
    names: Dict[str, str] = {}
    if ids:
        try:
            for c in await sb_select("clients", select="id,name", filters={"id": f"in.({','.join(ids)})"}, limit=len(ids)):
                names[c["id"]] = c.get("name") or c["id"]
        except Exception:  # noqa: BLE001
            pass
    return {"period": {"start": first.isoformat(), "end": last.isoformat()}, "currency": "USD", "estimated": True,
            **aggregate(rows, names)}
