"""Índice de saúde MUGOVERSO — a nota que liga tudo (Clipping → Saúde da marca).

Inspirado no "Share of Attention" da Winnin, mas com o que só o MUGOVERSO tem: a venda da loja.
Cada pilar vira uma nota de 0 a 100 no período escolhido; o índice é a média ponderada dos pilares
que têm dado. Pilar sem dado (ex.: empresa sem loja conectada) sai da conta e o peso dele é
redistribuído entre os outros — a tela mostra isso, nunca inventa número.

Pilares:
- ``conversa``  — sentimento líquido das menções (notícias, comentários, Direct): (líquido + 100) / 2.
  Comentário no próprio perfil pesa metade (quem comenta costuma ser fã). Precisa de pelo menos
  ``MIN_MENTIONS`` menções analisadas, e o líquido é "encolhido" para o neutro com ``PRIOR_MENTIONS``
  menções neutras imaginárias: amostra pequena não vira nota extrema (ajuste de confiança).
- ``reputacao`` — alertas abertos de termos sensíveis/queda: 100 − 25 por alerta alto − 10 por médio.
  Só entra na conta com ``MIN_MENTIONS`` menções monitoradas no período ("sem alerta" sem monitorar nada não é 100).
- ``atencao``   — alcance + interações do Instagram vs período anterior (nota de crescimento). O período
  anterior precisa ter dado em pelo menos metade dos dias; parcial compara pela média por dia.
- ``presenca``  — share de voz contra a FATIA JUSTA: com N concorrentes a fatia justa é 1/(N+1).
  Na fatia justa = 50; o dobro dela = 100; metade = 25.
- ``conversao`` — pedidos + receita da loja (Shopify/Fbits) vs período anterior (nota de crescimento).

Nota de crescimento: estável = 50 (o meio da régua); cada 1% de variação vale 0,8 ponto, igual para alta
e queda (+62,5% = 100, −62,5% = 0). Saiu do zero = 60 (base pequena não é prova de crescimento).

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
MIN_PREV_DAYS = 7  # piso; o período anterior precisa de dado em pelo menos metade dos dias
MIN_MENTIONS = 30  # abaixo disso a amostra de menções é pequena demais para dar nota
PRIOR_MENTIONS = bh.PRIOR_MENTIONS
SOURCE_WEIGHT = bh.SOURCE_WEIGHT
STABLE_SCORE = 50
FROM_ZERO_SCORE = 60
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
    """Estável = 50; ±0,8 ponto por 1% de variação (simétrico). Saiu do zero = 60; sem movimento = sem nota."""
    if cur is None or prev is None:
        return None
    if not prev:
        return FROM_ZERO_SCORE if cur > 0 else None
    return _clamp(STABLE_SCORE + 0.8 * change_pct(cur, prev))


def blend(scores: List[Optional[int]]) -> Optional[int]:
    valid = [s for s in scores if s is not None]
    return _round(sum(valid) / len(valid)) if valid else None


def fair_share_score(share: Optional[float], rivals: int) -> Optional[int]:
    """Nota do share (%) contra a fatia justa 1/(N+1): na fatia justa = 50, o dobro = 100."""
    if share is None or rivals < 1:
        return None
    fair = 100 / (rivals + 1)
    return _clamp(50 * share / fair)


def share_score(brand: int, competitors: int, rivals: int = 1) -> tuple[Optional[int], Optional[float]]:
    """Share de voz (%) e nota: sem concorrente no radar ou sem notícia nenhuma = sem nota."""
    total = brand + competitors
    if not competitors or not total:
        return None, None
    share = brand / total * 100
    return fair_share_score(share, max(1, rivals)), round(share, 1)


weighted_net = bh.weighted_net


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
    # Só conta como "com dado" o dia que a Meta devolveu algum número (dia sem snapshot não vira zero).
    series = sorted(
        (str(r.get("date") or r.get("start") or "")[:10], int(r.get("reach") or 0),
         int(r.get("total_interactions") or r.get("interactions") or 0))
        for r in daily if any(r.get(k) is not None for k in ("reach", "total_interactions", "interactions")))
    return {"reach": sum(x[1] for x in series), "interactions": sum(x[2] for x in series),
            "days": len(series), "series": series}


def available_split(series: List[tuple], length: int) -> Optional[Dict[str, Any]]:
    """Sem período anterior completo: compara com o que existe — os últimos k dias com dado contra os k
    anteriores (mesmo número de dias dos dois lados). None se não houver pelo menos MIN_PREV_DAYS de cada lado."""
    days = sorted({d[0]: d for d in series if d[0]}.values())
    k = min(length, len(days) // 2)
    if k < MIN_PREV_DAYS:
        return None
    recent, earlier = days[-k:], days[-2 * k:-k]

    def total(block: List[tuple]) -> Dict[str, Any]:
        return {"reach": sum(x[1] for x in block), "interactions": sum(x[2] for x in block), "days": len(block),
                "from": block[0][0], "to": block[-1][0]}
    return {"current": total(recent), "previous": total(earlier), "days": k}


def _ddmm(iso: str) -> str:
    return f"{iso[8:10]}/{iso[5:7]}"


async def _sales_totals(client_id: str, start: date, end: date) -> Optional[Dict[str, float]]:
    from .sales_by_origin import build_sales_by_origin
    report = await build_sales_by_origin(client_id, start=start.isoformat(), end=end.isoformat())
    totals = report.get("totals")
    if report.get("status") not in ("available", "partial") or not totals:
        return None
    return {"orders": float(totals.get("orders") or 0), "revenue": float(totals.get("revenue") or 0)}


async def _news_share(client_id: str, start: date, end: date) -> Dict[str, int]:
    from .studio_clipping import get_settings as clipping_settings
    lo, hi = bh._bounds(start, end)
    rows, settings = await asyncio.gather(
        sb_rpc("brand_health_share", {"p_client": client_id, "p_start": lo, "p_end": hi}),
        clipping_settings(client_id))
    out = {"marca": 0, "concorrente": 0, "rivais": len((settings or {}).get("competitor_terms") or [])}
    for row in rows if isinstance(rows, list) else []:
        key = "concorrente" if row.get("kind") == "concorrente" else "marca"
        out[key] += int(row.get("n") or 0)
    return out


async def _instagram_share(client_id: str, days: int) -> Optional[Dict[str, float]]:
    """Share de atenção no Instagram contra os concorrentes do Benchmarking (None sem coleta ou sem concorrente)."""
    from .benchmark import instagram_block
    competitors = await sb_select("benchmark_competitors", select="name,instagram_handle,active",
                                  filters={"client_id": f"eq.{client_id}", "active": "is.true"}, limit=100)
    block = await instagram_block(client_id, competitors, days=days)
    rows = block.get("rows") or []
    return share_against_measured(rows)


def share_against_measured(rows: List[Dict[str, Any]]) -> Optional[Dict[str, float]]:
    """Share da marca só contra concorrentes COM dado no período: concorrente sem post/interação lido
    (perfil privado, coleta falhou) não vira 0% dele e 100% da marca."""
    brand = next((r for r in rows if r.get("is_brand")), None)
    measured = [r for r in rows if not r.get("is_brand") and int(r.get("interactions_in_period") or 0) > 0]
    if not brand:
        return None
    if not measured:
        others = sum(1 for r in rows if not r.get("is_brand"))
        return {"share": None, "rivals": 0, "unmeasured": others} if others else None
    mine = int(brand.get("interactions_in_period") or 0)
    total = mine + sum(int(r["interactions_in_period"]) for r in measured)
    return {"share": round(mine / total * 100, 1), "rivals": len(measured)}


async def _conversation(client_id: str, start: date, end: date) -> Dict[str, Any]:
    splits = bh.splits_by_source(await bh._buckets(client_id, start, end, "year", list(bh.SOURCES)))
    analyzed = sum(split[s] for split in splits.values() for s in bh.SENTIMENTS)
    mentions = sum(sum(split.values()) for split in splits.values())
    return {"net": weighted_net(splits), "analyzed": analyzed, "mentions": mentions}


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


def _ig_value(block: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return None if block is None else {k: v for k, v in block.items() if k != "series"}


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
    mentions = int((conv or {}).get("mentions") or analyzed)
    enough = net is not None and analyzed >= MIN_MENTIONS
    pillars.append(_pillar(
        "conversa", _clamp((net + 100) / 2) if enough else None,
        f"Sentimento líquido {net:+d} em {_fmt_int(analyzed)} menções analisadas (ajustado pelo tamanho da amostra)" if enough else "",
        value=net if enough else None,
        reason=("Ainda sem menções analisadas pela IA no período." if not analyzed else
                f"Fora da conta: só {analyzed} menções analisadas no período; precisa de {MIN_MENTIONS} para uma nota justa.")))

    if alerts is None:
        pillars.append(_pillar("reputacao", None, "", reason="Não foi possível ler os alertas agora."))
    elif not alerts and mentions < MIN_MENTIONS:
        pillars.append(_pillar("reputacao", None, "", reason=(
            f"Fora da conta: só {mentions} menções monitoradas no período; sem alerta com tão pouco monitorado não prova reputação boa.")))
    else:
        high = sum(1 for a in alerts if a.get("severity") == "alto")
        detail = ("Nenhum alerta aberto" if not alerts else
                  (f"{len(alerts)} {'alerta aberto' if len(alerts) == 1 else 'alertas abertos'}"
                   f"{f', {high} alto' + ('s' if high > 1 else '') if high else ''}") if with_alert_detail else "Há pontos em acompanhamento pela equipe")
        pillars.append(_pillar("reputacao", bh.alert_score(alerts), detail, value=len(alerts)))

    prev_days = int(ig_prev.get("days", length)) if ig_prev else 0  # sem a contagem de dias: período completo
    need_days = max(MIN_PREV_DAYS, (length + 1) // 2)
    if ig_cur and ig_prev is not None and prev_days >= need_days:
        # Período anterior incompleto (histórico do Instagram começa depois): compara pela MÉDIA POR DIA.
        partial = prev_days < length
        cur_days = max(1, int(ig_cur.get("days") or length))

        def rate(block: Dict[str, Any], key: str, days: int) -> float:
            return block[key] / days if partial else block[key]
        score = blend([growth_score(rate(ig_cur, "reach", cur_days), rate(ig_prev, "reach", prev_days)),
                       growth_score(rate(ig_cur, "interactions", cur_days), rate(ig_prev, "interactions", prev_days))])
        ch = change_pct(rate(ig_cur, "reach", cur_days), rate(ig_prev, "reach", prev_days))
        detail = f"Alcance {_fmt_int(ig_cur['reach'])} e {_fmt_int(ig_cur['interactions'])} interações no período"
        if partial:
            detail += f" · comparado pela média por dia ({prev_days} de {length} dias do período anterior têm dado)"
        pillars.append(_pillar("atencao", score, detail, value=_ig_value(ig_cur), previous=_ig_value(ig_prev), change=ch,
                               reason="Sem alcance nem interações nos dois períodos."))
    elif ig_cur and (fallback := available_split((ig_prev or {}).get("series", []) + ig_cur.get("series", []), length)):
        cur_b, prev_b = fallback["current"], fallback["previous"]
        score = blend([growth_score(cur_b["reach"], prev_b["reach"]),
                       growth_score(cur_b["interactions"], prev_b["interactions"])])
        prev_label = f"{prev_start.strftime('%d/%m')} a {prev_end.strftime('%d/%m')}"
        detail = (f"Alcance {_fmt_int(ig_cur['reach'])} e {_fmt_int(ig_cur['interactions'])} interações no período · "
                  f"sem histórico de {prev_label}, comparado com o que existe: últimos {fallback['days']} dias com dado "
                  f"({_ddmm(cur_b['from'])}–{_ddmm(cur_b['to'])}) contra os {fallback['days']} anteriores "
                  f"({_ddmm(prev_b['from'])}–{_ddmm(prev_b['to'])})")
        pillars.append(_pillar("atencao", score, detail, value=_ig_value(cur_b), previous=_ig_value(prev_b),
                               change=change_pct(cur_b["reach"], prev_b["reach"]),
                               reason="Sem alcance nem interações nos dois períodos."))
    else:
        prev_label = f"{prev_start.strftime('%d/%m')} a {prev_end.strftime('%d/%m')}"
        pillars.append(_pillar("atencao", None, "", reason=(
            f"Fora da conta: só {prev_days} de {length} dias com dados do Instagram de {prev_label} "
            f"(precisa de {need_days}) para comparar. Escolha um período menor ou aguarde a busca do histórico." if ig_cur
            else "Instagram não conectado ou sem dados no período.")))

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
    news_rivals = int((share or {}).get("rivais") or 1)
    news_score, news_share = share_score(brand_news, rival_news, news_rivals)
    ig_pct = None if not ig_share else ig_share.get("share")
    ig_rivals = int((ig_share or {}).get("rivals") or 0)
    ig_score = fair_share_score(ig_pct, ig_rivals)
    parts = []
    if news_share is not None:
        parts.append(f"{news_share:.0f}% das notícias do radar ({brand_news} de {brand_news + rival_news}; "
                     f"fatia justa {100 / (max(1, news_rivals) + 1):.0f}%)")
    if ig_score is not None:
        parts.append(f"{ig_pct:.0f}% das interações no Instagram contra {ig_rivals} "
                     f"{'concorrente' if ig_rivals == 1 else 'concorrentes'} (fatia justa {100 / (ig_rivals + 1):.0f}%)")
    pillars.append(_pillar(
        "presenca", blend([news_score, ig_score]), " · ".join(parts),
        value={"noticias": news_share, "instagram": ig_pct},
        reason=(f"Fora da conta: {(ig_share or {}).get('unmeasured')} concorrente(s) no Benchmarking sem interações lidas no período "
                "(perfil privado ou coleta pendente) e sem notícias de concorrentes no radar. Atualize o Benchmarking."
                if (ig_share or {}).get("unmeasured") and not rival_news else
                "Cadastre concorrentes no radar do Clipping ou no Benchmarking (com o @ do Instagram) para medir a fatia de atenção."
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
