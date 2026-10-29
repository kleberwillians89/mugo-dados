"""Melhor dia e horário para publicar no Instagram, por empresa.

Duas fontes, sempre no fuso de São Paulo:

1. Desempenho real dos posts (ig_media): cada post recebe um índice de
   alcance = alcance do post / mediana de alcance do MESMO formato no período.
   Assim um Reels não "ganha" de um carrossel só por ser Reels, e o índice 1,0
   significa "na média da própria conta". Os posts são agrupados por dia da
   semana e por faixa de 3 horas.
2. Seguidores online (ig_online_followers): mediana por hora de quantos
   seguidores estavam ativos. Mostra quando a base está no app, não quando ela
   reage; serve de desempate e de sinal para contas com poucos posts.

Leitura pura: não chama a Meta, não sincroniza e não grava nada.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from statistics import median
from typing import Any, Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo

from .ig_supabase import sb_select

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
WEEKDAYS = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")
BLOCK_HOURS = 3
MIN_POSTS_SLOT = 2          # abaixo disso a faixa nem entra no ranking
CONFIDENT_POSTS_SLOT = 4    # a partir daqui a confiança é "boa"
MAX_MEDIA_ROWS = 1000


def _block_label(hour: int) -> str:
    start = (hour // BLOCK_HOURS) * BLOCK_HOURS
    return f"{start:02d}h-{start + BLOCK_HOURS:02d}h"


def _format_of(row: Dict[str, Any]) -> str:
    product = str(row.get("media_product_type") or "").upper()
    media_type = str(row.get("media_type") or "").upper()
    if product == "REELS":
        return "reels"
    if media_type == "CAROUSEL_ALBUM":
        return "carrossel"
    if media_type == "VIDEO":
        return "video"
    return "imagem"


def _parse_ts(value: Any) -> Optional[datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    elif len(raw) >= 5 and raw[-5] in "+-" and raw[-3] != ":":
        raw = f"{raw[:-2]}:{raw[-2:]}"
    try:
        ts = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def _reach_of(insights: Dict[str, Any]) -> int:
    for key in ("reach", "views"):
        try:
            value = int(insights.get(key) or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            return value
    return 0


def _interactions_of(insights: Dict[str, Any]) -> int:
    try:
        total = int(insights.get("total_interactions") or 0)
    except (TypeError, ValueError):
        total = 0
    if total > 0:
        return total
    return sum(int(insights.get(k) or 0) for k in ("likes", "comments", "shares", "saved")
               if isinstance(insights.get(k), (int, float)))


def score_posts(rows: Iterable[Dict[str, Any]], *, start: date, end: date) -> List[Dict[str, Any]]:
    """Normaliza cada post pelo alcance mediano do próprio formato."""
    posts: List[Dict[str, Any]] = []
    for row in rows:
        ts = _parse_ts(row.get("timestamp"))
        if ts is None:
            continue
        local = ts.astimezone(SAO_PAULO)
        if not start <= local.date() <= end:
            continue
        insights = row.get("insights_json") or {}
        reach = _reach_of(insights)
        if reach <= 0:
            continue  # post sem insight não diz nada sobre horário
        posts.append({
            "format": _format_of(row),
            "weekday": local.weekday(),
            "hour": local.hour,
            "reach": reach,
            "interactions": _interactions_of(insights),
            "caption": row.get("caption"),  # só presente quando o select pediu
        })
    medians: Dict[str, float] = {}
    by_format: Dict[str, List[int]] = defaultdict(list)
    for post in posts:
        by_format[post["format"]].append(post["reach"])
    for fmt, values in by_format.items():
        medians[fmt] = float(median(values))
    for post in posts:
        base = medians.get(post["format"]) or 0
        post["reach_index"] = post["reach"] / base if base > 0 else None
        post["engagement_rate"] = post["interactions"] / post["reach"] if post["reach"] else None
    return [p for p in posts if p["reach_index"] is not None]


def _summarize(group: List[Dict[str, Any]]) -> Dict[str, Any]:
    rates = [p["engagement_rate"] for p in group if p["engagement_rate"] is not None]
    return {
        "posts": len(group),
        "reach_index": round(median(p["reach_index"] for p in group), 2),
        "engagement_rate": round(median(rates) * 100, 2) if rates else None,
        "confidence": "boa" if len(group) >= CONFIDENT_POSTS_SLOT else "baixa",
    }


def rank_slots(posts: List[Dict[str, Any]], *, limit: int = 5) -> List[Dict[str, Any]]:
    groups: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)
    for post in posts:
        groups[(post["weekday"], post["hour"] // BLOCK_HOURS)].append(post)
    ranked = []
    for (weekday, block), group in groups.items():
        if len(group) < MIN_POSTS_SLOT:
            continue
        ranked.append({"weekday": WEEKDAYS[weekday], "hours": _block_label(block * BLOCK_HOURS), **_summarize(group)})
    ranked.sort(key=lambda s: (s["reach_index"], s["posts"]), reverse=True)
    return ranked[:limit]


def summarize_by(posts: List[Dict[str, Any]], key: str) -> List[Dict[str, Any]]:
    groups: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for post in posts:
        bucket = post["weekday"] if key == "weekday" else post["hour"] // BLOCK_HOURS
        groups[bucket].append(post)
    out = []
    for bucket in sorted(groups):
        label = WEEKDAYS[bucket] if key == "weekday" else _block_label(bucket * BLOCK_HOURS)
        out.append({key if key == "weekday" else "hours": label, **_summarize(groups[bucket])})
    return out


def online_followers_by_hour(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Mediana de seguidores online por hora de São Paulo.

    A Meta não documenta o fuso de hour_key. O end_time de cada dia marca a
    meia-noite desse fuso (ex.: 07:00 UTC = meia-noite no Pacífico), então a
    diferença é deduzida do próprio dado em vez de presumida.
    """
    per_hour: Dict[int, List[int]] = defaultdict(list)
    days = set()
    for row in rows:
        end_time = _parse_ts(row.get("end_time"))
        try:
            hour_key = int(row.get("hour_key"))
            total = int(row.get("followers_online") or 0)
        except (TypeError, ValueError):
            continue
        if end_time is None or not 0 <= hour_key <= 23:
            continue
        midnight_utc_hour = end_time.astimezone(timezone.utc).hour
        # Data de referência pós-2019: São Paulo não tem mais horário de verão.
        utc_moment = datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(hours=hour_key + midnight_utc_hour)
        per_hour[utc_moment.astimezone(SAO_PAULO).hour].append(total)
        days.add(row.get("metric_date"))
    hours = [{"hour": f"{h:02d}h", "followers_online": int(median(v))} for h, v in sorted(per_hour.items())]
    peak = sorted(hours, key=lambda h: h["followers_online"], reverse=True)[:3]
    return {"days": len(days), "by_hour": hours, "peak_hours": [h["hour"] for h in peak]}


async def build_posting_times(client_id: str, *, start: str, end: str) -> Dict[str, Any]:
    since, until = date.fromisoformat(start), date.fromisoformat(end)
    # Margem de um dia nas pontas: o filtro exato acontece já no fuso de São Paulo.
    ts_from = (since - timedelta(days=1)).isoformat()
    media_rows = await sb_select(
        "ig_media",
        select="media_type,media_product_type,timestamp,insights_json",
        filters={"client_id": f"eq.{client_id}", "timestamp": f"gte.{ts_from}"},
        order="timestamp.desc",
        limit=MAX_MEDIA_ROWS,
    )
    posts = score_posts(media_rows, start=since, end=until)
    try:
        online_rows = await sb_select(
            "ig_online_followers",
            select="metric_date,end_time,hour_key,followers_online",
            filters={"client_id": f"eq.{client_id}", "metric_date": f"gte.{since.isoformat()}"},
            limit=24 * 400,
        )
    except Exception:
        online_rows = []  # tabela ainda não aplicada: segue só com os posts
    online = online_followers_by_hour(r for r in online_rows if str(r.get("metric_date") or "") <= until.isoformat())

    formats: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for post in posts:
        formats[post["format"]].append(post)

    notes = [
        "Índice de alcance 1,0 = média da própria conta para o mesmo formato; 1,3 = 30% acima.",
        "Horários no fuso de São Paulo.",
    ]
    if len(posts) < 20:
        notes.append("Poucos posts no período: trate o ranking como hipótese e amplie o intervalo.")
    if not online["days"]:
        notes.append("Seguidores online ainda sem histórico (coleta diária; exige 100+ seguidores).")

    return {
        "posts_analyzed": len(posts),
        "posts_by_format": {fmt: len(items) for fmt, items in sorted(formats.items())},
        # Alcance bruto mediano por formato: compara formatos entre si (o
        # índice de alcance não serve para isso, ele é relativo ao formato).
        "format_median_reach": {fmt: int(median(p["reach"] for p in items)) for fmt, items in sorted(formats.items())},
        "best_slots": rank_slots(posts),
        "best_slots_by_format": {fmt: rank_slots(items, limit=3) for fmt, items in sorted(formats.items())
                                 if len(items) >= MIN_POSTS_SLOT * 2},
        "by_weekday": summarize_by(posts, "weekday"),
        "by_hours": summarize_by(posts, "hours"),
        "online_followers": online,
        "observacoes": notes,
    }
