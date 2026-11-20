"""Aprendizados da marca: o ciclo fechado da IA.

Uns 7 dias depois de cada post publicado pelo MUGOVERSO, compara o resultado com a média do próprio formato
(alcance, salvamentos, compartilhamentos) e guarda UMA conclusão por post. O mesmo para os anúncios criados na
Mídia On (CTR e custo por resultado contra a mediana da conta). A IA lê as conclusões mais recentes antes de criar
(seção "aprendizados_da_marca") e cita no "por que este post" em qual se baseou.

As conclusões são montadas com regra fixa, sem IA: número é número (e não custa crédito).
Roda pelo Relógio dos jobs (``brand-learnings``, 1 vez por dia), fora do Render.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from statistics import median
from typing import Any, Dict, List, Optional

from .ig_supabase import sb_select, sb_upsert

TABLE = "brand_learnings"
WEEKDAYS = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")
FORMAT_LABEL = {"REELS": "Reels", "VIDEO": "vídeo", "CAROUSEL_ALBUM": "carrossel", "IMAGE": "imagem", "STORY": "story"}
ABOVE, BELOW = 1.3, 0.7


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _x(value: float) -> str:
    return f"{value:.1f}".replace(".", ",") + "×"


def verdict_of(index: float) -> str:
    return "acima" if index >= ABOVE else "abaixo" if index <= BELOW else "na_media"


def post_lesson(facts: Dict[str, Any]) -> str:
    """Uma frase que a equipe e a IA entendem: o que foi, como foi e o que fazer."""
    fmt = facts.get("formato") or "post"
    head = f"{fmt.capitalize()} \"{facts['pauta']}\"" if facts.get("pauta") else f"{fmt.capitalize()} de {facts.get('data', '')}"
    extras = [f"pilar {facts['pilar']}"] if facts.get("pilar") else []
    if facts.get("gancho"):
        extras.append(f"gancho \"{facts['gancho']}\"")
    base = f"{head}{' (' + ', '.join(extras) + ')' if extras else ''}, {facts['dia']} às {facts['hora']}h: "
    numbers = f"{_x(facts['alcance_vs_media'])} o alcance médio de {fmt}"
    if facts.get("salvamentos"):
        numbers += f", {facts['salvamentos']} salvamentos"
    if facts.get("compartilhamentos"):
        numbers += f", {facts['compartilhamentos']} compartilhamentos"
    action = {"acima": "Repetir o formato e o tipo de gancho.", "abaixo": "Evitar repetir assim; testar outro gancho ou formato.",
              "na_media": "Resultado dentro do esperado."}[facts["veredito"]]
    return f"{base}{numbers}. {action}"[:600]


async def learn_posts(client_id: str, now: Optional[datetime] = None) -> int:
    """Posts publicados pelo MUGOVERSO há 7 a 45 dias que ainda não viraram aprendizado."""
    from .posting_times import score_posts
    now = now or datetime.now(timezone.utc)
    items = await sb_select("studio_calendar_items", select="published_media_id,title,hook,pillar,scheduled_at", limit=200,
                            filters={"client_id": f"eq.{client_id}", "published_media_id": "not.is.null",
                                     "scheduled_at": f"gte.{(now - timedelta(days=45)).isoformat()}",
                                     "and": f"(scheduled_at.lte.{(now - timedelta(days=7)).isoformat()})"})
    if not items:
        return 0
    known = {r["ref_id"] for r in await sb_select(TABLE, select="ref_id", limit=1000,
                                                     filters={"client_id": f"eq.{client_id}", "kind": "eq.post"})}
    todo = {str(i["published_media_id"]): i for i in items if str(i["published_media_id"]) not in known}
    if not todo:
        return 0
    since = (now - timedelta(days=120)).date()
    media = await sb_select("ig_media", select="media_id,media_type,media_product_type,timestamp,insights_json,caption", limit=500,
                            filters={"client_id": f"eq.{client_id}", "timestamp": f"gte.{since.isoformat()}"}, order="timestamp.desc")
    insights = {str(m.get("media_id")): (m.get("insights_json") or {}) for m in media}
    scored = {str(p.get("media_id")): p for p in score_posts(media, start=since, end=date.max) if p.get("media_id")}
    rows = []
    for media_id, item in todo.items():
        post = scored.get(media_id)
        if not post:
            continue  # ainda sem números do Instagram: tenta de novo no próximo dia
        data = insights.get(media_id) or {}
        facts = {"pauta": (item.get("title") or "")[:120], "gancho": (item.get("hook") or "")[:120] or None,
                 "pilar": (item.get("pillar") or "")[:60] or None, "formato": FORMAT_LABEL.get(post["format"], str(post["format"]).lower()),
                 "alcance": post["reach"], "alcance_vs_media": round(post["reach_index"], 2),
                 "curtidas": int(_num(data.get("likes"))), "comentarios": int(_num(data.get("comments"))),
                 "salvamentos": int(_num(data.get("saved"))), "compartilhamentos": int(_num(data.get("shares"))),
                 "dia": WEEKDAYS[post["weekday"]], "hora": post["hour"], "data": str(item.get("scheduled_at") or "")[:10]}
        facts["veredito"] = verdict_of(post["reach_index"])
        rows.append({"client_id": client_id, "kind": "post", "ref_id": media_id, "verdict": facts["veredito"],
                     "lesson": post_lesson(facts), "facts": facts, "published_at": item.get("scheduled_at")})
    if rows:
        await sb_upsert(TABLE, rows, on_conflict="client_id,kind,ref_id")
    return len(rows)


async def learn_ads(client_id: str, now: Optional[datetime] = None) -> int:
    """Anúncios criados na Mídia On com pelo menos 7 dias e R$ 50 de gasto: CTR e custo por resultado contra a
    mediana dos anúncios da conta no mesmo período."""
    from .studio_intelligence import _mugo_ad_copies
    now = now or datetime.now(timezone.utc)
    copies = await _mugo_ad_copies(client_id)
    if not copies:
        return 0
    known = {r["ref_id"] for r in await sb_select(TABLE, select="ref_id", limit=1000,
                                                     filters={"client_id": f"eq.{client_id}", "kind": "eq.ad"})}
    since = (now - timedelta(days=90)).date().isoformat()
    stats = await sb_select("ad_daily_stats", select="ad_id,ad_name,stat_date,spend,impressions,clicks,conversions,revenue", limit=5000,
                            filters={"client_id": f"eq.{client_id}", "stat_date": f"gte.{since}"}, order="stat_date.desc")
    ads: Dict[str, Dict[str, Any]] = {}
    for r in stats:
        a = ads.setdefault(str(r.get("ad_id") or ""), {"name": r.get("ad_name"), "spend": 0.0, "impressions": 0.0, "clicks": 0.0,
                                                        "conversions": 0.0, "first": None})
        for k in ("spend", "impressions", "clicks", "conversions"):
            a[k] += _num(r.get(k))
        day = str(r.get("stat_date") or "")[:10]
        a["first"] = min(a["first"] or day, day)
    pool = [a for a in ads.values() if a["spend"] >= 20 and a["impressions"]]
    if len(pool) < 3:
        return 0
    ctr_median = median(a["clicks"] / a["impressions"] for a in pool)
    with_conv = [a["spend"] / a["conversions"] for a in pool if a["conversions"]]
    cpa_median = median(with_conv) if len(with_conv) >= 3 else None
    cutoff = (now - timedelta(days=7)).date().isoformat()
    rows = []
    for ad_id, copy in copies.items():
        a = ads.get(ad_id)
        if ad_id in known or not a or a["spend"] < 50 or not a["impressions"] or (a["first"] or "9999") > cutoff:
            continue
        ctr = a["clicks"] / a["impressions"]
        if cpa_median and a["conversions"]:
            index, metric = cpa_median / (a["spend"] / a["conversions"]), "custo por resultado"
        else:
            index, metric = (ctr / ctr_median if ctr_median else 1.0), "taxa de cliques"
        verdict = verdict_of(index)
        facts = {"anuncio": a["name"], **copy, "investimento": round(a["spend"], 2), "ctr_pct": round(ctr * 100, 2),
                 "conversoes": int(a["conversions"]), "comparado_por": metric, "indice": round(index, 2), "veredito": verdict}
        what = f"Anúncio \"{a['name']}\" ({copy.get('formato', 'imagem')}" + (f", título \"{copy['titulo']}\"" if copy.get("titulo") else "") + ")"
        result = {"acima": f"{_x(index)} melhor que a mediana da conta em {metric}. Repetir a linha de texto e o formato.",
                  "abaixo": f"{_x(1 / index if index else 0)} pior que a mediana da conta em {metric}. Evitar repetir assim.",
                  "na_media": f"Dentro da mediana da conta em {metric}."}[verdict]
        rows.append({"client_id": client_id, "kind": "ad", "ref_id": ad_id, "verdict": verdict, "lesson": f"{what}: {result}"[:600],
                     "facts": facts, "published_at": f"{a['first']}T12:00:00+00:00"})
    if rows:
        await sb_upsert(TABLE, rows, on_conflict="client_id,kind,ref_id")
    return len(rows)


async def recent(client_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    """O que a IA lê: as conclusões mais recentes, primeiro as que fogem da média (acima ou abaixo)."""
    rows = await sb_select(TABLE, select="kind,verdict,lesson,published_at", limit=60, order="created_at.desc",
                           filters={"client_id": f"eq.{client_id}"})
    rows.sort(key=lambda r: str(r.get("published_at") or ""), reverse=True)
    rows.sort(key=lambda r: r.get("verdict") == "na_media")  # estável: fora da média primeiro, mais recentes antes
    return [{"tipo": "post" if r["kind"] == "post" else "anúncio", "resultado": r["verdict"], "aprendizado": r["lesson"],
             "quando": str(r.get("published_at") or "")[:10]} for r in rows[:limit]]


async def run_all() -> Dict[str, Any]:
    clients = await sb_select("clients", select="id", limit=500)
    total = {"clients": 0, "posts": 0, "ads": 0, "errors": 0}
    for c in clients:
        cid = str(c.get("id") or "")
        if not cid:
            continue
        total["clients"] += 1
        for fn, key in ((learn_posts, "posts"), (learn_ads, "ads")):
            try:
                total[key] += await fn(cid)
            except Exception as exc:  # noqa: BLE001 - uma marca com problema não para as outras
                total["errors"] += 1
                print(f"[brand_learnings] {key} failed error_type={type(exc).__name__}")
    return total
