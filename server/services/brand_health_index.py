"""Índice de saúde MUGOVERSO — a nota que liga tudo (Clipping → Saúde da marca).

Inspirado no "Share of Attention" da Winnin, mas com o que só o MUGOVERSO tem: a venda da loja.
Cada pilar vira uma nota de 0 a 100 no período escolhido; o índice é a média ponderada dos pilares
que têm dado. Pilar sem dado (ex.: empresa sem loja conectada) sai da conta e o peso dele é
redistribuído entre os outros — a tela mostra isso, nunca inventa número.

Pilares:
- ``conversa``  — sentimento líquido das menções (notícias, comentários, Direct): (líquido + 100) / 2.
- ``reputacao`` — alertas abertos de termos sensíveis/queda: 100 − 25 por alerta alto − 10 por médio.
- ``atencao``   — alcance + interações do Instagram vs período anterior (nota de crescimento).
- ``presenca``  — share de voz nas notícias: marca ÷ (marca + concorrentes); 50% ou mais = 100.
- ``conversao`` — pedidos + receita da loja (Shopify/Fbits) vs período anterior (nota de crescimento).

Nota de crescimento: estável = 60; cada 1% de alta soma 0,8 ponto (+50% = 100) e cada 1% de queda
tira 0,8 (−75% = 0). Saiu do zero = 80.

Pesos: padrão abaixo; cada empresa ajusta em ``brand_health_settings.index_weights`` (equipe Mugô ou
admin do cliente). Peso 0 desliga o pilar.
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any, Awaitable, Dict, List, Optional

import httpx

from . import brand_health as bh
from .ig_supabase import sb_rpc, sb_select, sb_upsert
from .studio_calendar import StudioError

PILLARS = ("conversa", "conversao", "atencao", "presenca", "reputacao")
DEFAULT_WEIGHTS: Dict[str, int] = {"conversa": 30, "conversao": 25, "atencao": 20, "presenca": 15, "reputacao": 10}
PILLAR_NAME = {
    "conversa": "Conversa", "conversao": "Conversão em vendas", "atencao": "Atenção no Instagram",
    "presenca": "Presença na mídia", "reputacao": "Reputação",
}
PILLAR_HINT = {
    "conversa": "Sentimento das menções em notícias, comentários e Direct.",
    "conversao": "Pedidos e receita da loja contra o período anterior.",
    "atencao": "Alcance e interações do Instagram contra o período anterior.",
    "presenca": "Fatia da atenção que fica com a marca contra os concorrentes: notícias do radar e interações no Instagram (Benchmarking).",
    "reputacao": "Alertas de termos sensíveis e quedas abertos agora.",
}
SOURCE_TIMEOUT = 25.0


# ------------------------------------------------------------------ notas (funções puras)

def _round(value: float) -> int:
    """Arredonda meio para cima (62,5 → 63), como a pessoa espera ver na tela."""
    return int(value + 0.5) if value >= 0 else -int(-value + 0.5)


def _clamp(value: float) -> int:
    return max(0, min(100, _round(value)))


def change_pct(cur: Optional[float], prev: Optional[float]) -> Optional[float]:
    if cur is None or prev is None or not prev:
        return None
    return (cur - prev) / prev * 100


def growth_score(cur: Optional[float], prev: Optional[float]) -> Optional[int]:
    """Estável = 60; ±0,8 ponto por 1% de variação. Saiu do zero = 80; sem movimento nos dois = sem nota."""
    if cur is None or prev is None:
        return None
    if not prev:
        return 80 if cur > 0 else None
    return _clamp(60 + 0.8 * change_pct(cur, prev))


def blend(scores: List[Optional[int]]) -> Optional[int]:
    valid = [s for s in scores if s is not None]
    return _round(sum(valid) / len(valid)) if valid else None


def share_score(brand: int, competitors: int) -> tuple[Optional[int], Optional[float]]:
    """Share de voz (%) e nota: sem concorrente no radar ou sem notícia nenhuma = sem nota."""
    total = brand + competitors
    if not competitors or not total:
        return None, None
    share = brand / total * 100
    return _clamp(share * 2), round(share, 1)


def clean_weights(raw: Any) -> Dict[str, int]:
    """Só pilares conhecidos, inteiros de 0 a 100; o que faltar volta ao padrão."""
    source = raw if isinstance(raw, dict) else {}
    out: Dict[str, int] = {}
    for key in PILLARS:
        try:
            out[key] = max(0, min(100, int(source.get(key, DEFAULT_WEIGHTS[key]))))
        except (TypeError, ValueError):
            out[key] = DEFAULT_WEIGHTS[key]
    return out


def compose(pillars: List[Dict[str, Any]], weights: Dict[str, int]) -> Dict[str, Any]:
    """Média ponderada dos pilares com nota; devolve o índice e o peso efetivo (%) de cada pilar."""
    active = [p for p in pillars if p["score"] is not None and weights.get(p["key"], 0) > 0]
    total = sum(weights[p["key"]] for p in active)
    for p in pillars:
        w = weights.get(p["key"], 0)
        p["weight"] = w
        p["effective_weight"] = round(w / total * 100, 1) if total and p in active else 0.0
    if not total:
        return {"index": None, "label": None, "coverage": 0}
    index = _round(sum(p["score"] * weights[p["key"]] for p in active) / total)
    configured = sum(w for w in weights.values() if w > 0)
    return {"index": index, "label": bh.health_label(index), "coverage": _round(total / configured * 100) if configured else 0}


# ------------------------------------------------------------------ fontes

async def _safe(name: str, awaitable: Awaitable[Any]) -> Any:
    try:
        return await asyncio.wait_for(awaitable, timeout=SOURCE_TIMEOUT)
    except Exception as exc:  # noqa: BLE001 — pilar sem dado sai da conta; não derruba o índice
        print(f"[brand_health_index] source_failed source={name} {type(exc).__name__}")
        return None


async def _instagram_totals(client_id: str, start: date, end: date) -> Optional[Dict[str, int]]:
    from .ig_dashboard import get_dashboard
    report = await get_dashboard(client_id=client_id, start=start.isoformat(), end=end.isoformat())
    daily = report.get("daily") or []
    if not report.get("connection_id") or not daily:
        return None
    return {"reach": sum(int(r.get("reach") or 0) for r in daily),
            "interactions": sum(int(r.get("total_interactions") or r.get("interactions") or 0) for r in daily)}


async def _sales_totals(client_id: str, start: date, end: date) -> Optional[Dict[str, float]]:
    from .sales_by_origin import build_sales_by_origin
    report = await build_sales_by_origin(client_id, start=start.isoformat(), end=end.isoformat())
    totals = report.get("totals")
    if report.get("status") not in ("available", "partial") or not totals:
        return None
    return {"orders": float(totals.get("orders") or 0), "revenue": float(totals.get("revenue") or 0)}


async def _news_share(client_id: str, start: date, end: date) -> Dict[str, int]:
    lo, hi = bh._bounds(start, end)
    rows = await sb_rpc("brand_health_share", {"p_client": client_id, "p_start": lo, "p_end": hi})
    out = {"marca": 0, "concorrente": 0}
    for row in rows if isinstance(rows, list) else []:
        key = "concorrente" if row.get("kind") == "concorrente" else "marca"
        out[key] += int(row.get("n") or 0)
    return out


async def _instagram_share(client_id: str, days: int) -> Optional[float]:
    """Share de atenção no Instagram contra os concorrentes do Benchmarking (None sem coleta ou sem concorrente)."""
    from .benchmark import instagram_block
    competitors = await sb_select("benchmark_competitors", select="name,instagram_handle,active",
                                  filters={"client_id": f"eq.{client_id}", "active": "is.true"}, limit=100)
    block = await instagram_block(client_id, competitors, days=days)
    rows = block.get("rows") or []
    brand = next((r for r in rows if r.get("is_brand")), None)
    if not brand or len(rows) < 2 or brand.get("share") is None:
        return None
    return float(brand["share"])


async def _conversation(client_id: str, start: date, end: date) -> Dict[str, Any]:
    split = bh._split(await bh._buckets(client_id, start, end, "year", list(bh.SOURCES)))
    return {"net": bh.net_sentiment(split), "analyzed": sum(split[s] for s in bh.SENTIMENTS)}


# ------------------------------------------------------------------ pesos

async def get_weights(client_id: str) -> Dict[str, Any]:
    try:
        rows = await sb_select(bh.SETTINGS, select="index_weights", filters={"client_id": f"eq.{client_id}"}, limit=1)
    except httpx.HTTPStatusError:
        # Migração 000100 ainda não aplicada: segue com o padrão.
        rows = []
    raw = (rows[0] if rows else {}).get("index_weights")
    return {"weights": clean_weights(raw), "custom": isinstance(raw, dict)}


async def save_weights(client_id: str, weights: Dict[str, Any], *, user_id: str) -> Dict[str, Any]:
    clean = clean_weights(weights)
    if not any(clean.values()):
        raise StudioError("WEIGHTS_INVALID", "Deixe pelo menos um pilar com peso maior que zero.")
    now = bh._now().isoformat()
    settings = await bh.get_settings(client_id)
    row = {"client_id": client_id, "index_weights": clean, "weights_updated_by": user_id, "weights_updated_at": now}
    if not settings.get("saved"):
        # Primeira gravação da empresa: cria a linha com os limites padrão dos alertas.
        row.update({k: settings[k] for k in ("sensitive_terms", "index_drop_points", "negative_day_pct")})
    await sb_upsert(bh.SETTINGS, [row], on_conflict="client_id")
    return {"weights": clean, "custom": True}


# ------------------------------------------------------------------ índice

def _pillar(key: str, score: Optional[int], detail: str, *, value: Any = None, previous: Any = None,
            change: Optional[float] = None, reason: Optional[str] = None) -> Dict[str, Any]:
    return {"key": key, "name": PILLAR_NAME[key], "hint": PILLAR_HINT[key], "score": score, "detail": detail,
            "value": value, "previous": previous, "change": None if change is None else round(change, 1),
            "reason": None if score is not None else reason}


def _fmt_int(value: float) -> str:
    return f"{int(round(value)):,}".replace(",", ".")


async def compute(client_id: str, *, start: date, end: date, with_alert_detail: bool = False) -> Dict[str, Any]:
    bh.validate_period(start, end, "year")
    length = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=length - 1)

    (conv, alerts, weights, ig_cur, ig_prev, sales_cur, sales_prev, share, ig_share) = await asyncio.gather(
        _safe("conversation", _conversation(client_id, start, end)),
        _safe("alerts", bh.open_alerts(client_id)),
        get_weights(client_id),
        _safe("instagram", _instagram_totals(client_id, start, end)),
        _safe("instagram_prev", _instagram_totals(client_id, prev_start, prev_end)),
        _safe("sales", _sales_totals(client_id, start, end)),
        _safe("sales_prev", _sales_totals(client_id, prev_start, prev_end)),
        _safe("news_share", _news_share(client_id, start, end)),
        _safe("instagram_share", _instagram_share(client_id, max(7, min(length, 90)))),
    )

    pillars: List[Dict[str, Any]] = []

    net = (conv or {}).get("net")
    analyzed = int((conv or {}).get("analyzed") or 0)
    pillars.append(_pillar(
        "conversa", None if net is None else _clamp((net + 100) / 2),
        f"Sentimento líquido {net:+d} em {_fmt_int(analyzed)} menções analisadas" if net is not None else "",
        value=net, reason="Ainda sem menções analisadas pela IA no período."))

    if alerts is None:
        pillars.append(_pillar("reputacao", None, "", reason="Não foi possível ler os alertas agora."))
    else:
        high = sum(1 for a in alerts if a.get("severity") == "alto")
        detail = ("Nenhum alerta aberto" if not alerts else
                  (f"{len(alerts)} {'alerta aberto' if len(alerts) == 1 else 'alertas abertos'}"
                   f"{f', {high} alto' + ('s' if high > 1 else '') if high else ''}") if with_alert_detail else "Há pontos em acompanhamento pela equipe")
        pillars.append(_pillar("reputacao", bh.alert_score(alerts), detail, value=len(alerts)))

    if ig_cur and ig_prev is not None:
        prev = ig_prev
        score = blend([growth_score(ig_cur["reach"], prev["reach"]), growth_score(ig_cur["interactions"], prev["interactions"])])
        ch = change_pct(ig_cur["reach"], prev["reach"])
        pillars.append(_pillar(
            "atencao", score,
            f"Alcance {_fmt_int(ig_cur['reach'])} e {_fmt_int(ig_cur['interactions'])} interações no período",
            value=ig_cur, previous=prev, change=ch, reason="Sem alcance nem interações nos dois períodos."))
    else:
        pillars.append(_pillar("atencao", None, "", reason=(
            "Sem dados do período anterior para comparar." if ig_cur else "Instagram não conectado ou sem dados no período.")))

    if sales_cur and sales_prev is not None:
        prev = sales_prev or {"orders": 0, "revenue": 0}
        score = blend([growth_score(sales_cur["orders"], prev["orders"]), growth_score(sales_cur["revenue"], prev["revenue"])])
        pillars.append(_pillar(
            "conversao", score,
            f"{_fmt_int(sales_cur['orders'])} pedidos e R$ {_fmt_int(sales_cur['revenue'])} em vendas",
            value=sales_cur, previous=prev, change=change_pct(sales_cur["revenue"], prev["revenue"]),
            reason="Sem pedidos nos dois períodos."))
    else:
        pillars.append(_pillar("conversao", None, "", reason="Loja (Shopify ou Fbits) não conectada."))

    brand_news, rival_news = int((share or {}).get("marca") or 0), int((share or {}).get("concorrente") or 0)
    news_score, news_share = share_score(brand_news, rival_news)
    ig_score = None if ig_share is None else _clamp(ig_share * 2)
    parts = []
    if news_share is not None:
        parts.append(f"{news_share:.0f}% das notícias do radar ({brand_news} de {brand_news + rival_news})")
    if ig_share is not None:
        parts.append(f"{ig_share:.0f}% das interações no Instagram contra os concorrentes")
    pillars.append(_pillar(
        "presenca", blend([news_score, ig_score]), " · ".join(parts),
        value={"noticias": news_share, "instagram": ig_share},
        reason=("Cadastre concorrentes no radar do Clipping ou no Benchmarking (com o @ do Instagram) para medir a fatia de atenção."
                if not rival_news else "Sem notícias no período.")))

    order = {k: i for i, k in enumerate(PILLARS)}
    pillars.sort(key=lambda p: order[p["key"]])
    result = compose(pillars, weights["weights"])
    return {
        "period": {"start": start.isoformat(), "end": end.isoformat(),
                   "previous_start": prev_start.isoformat(), "previous_end": prev_end.isoformat()},
        **result,
        "pillars": pillars,
        "weights": weights["weights"],
        "default_weights": dict(DEFAULT_WEIGHTS),
        "custom_weights": weights["custom"],
    }
