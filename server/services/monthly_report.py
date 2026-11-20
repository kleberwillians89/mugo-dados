"""Relatório mensal completo (cresce em cima do Relatório social, na mesma tela).

Além dos 6 slides de social (social_report), junta o resto do mês:
- mídia paga (Meta, anúncio por anúncio: investimento, resultado, melhores e piores);
- WhatsApp (conversas, de onde vieram, quantas viraram venda e quanto venderam);
- vendas da loja (pedidos, faturamento, ticket médio e contra o mês anterior);
- resumo e próximos passos escritos pela IA com esses números (a equipe revisa).

Fluxo: no dia 1º o Relógio dos jobs (``monthly-reports``) fecha o mês anterior como RASCUNHO (monthly_reports).
A equipe confere e clica "Liberar para o cliente"; só então o cliente vê o mês na tela e pode existir o link
para quem não tem login. Mês sem linha em monthly_reports (relatórios antigos) continua como sempre foi: visível.
Os números do mês fechado ficam guardados (o mês não muda depois); "Atualizar números" refaz o retrato.
"""
from __future__ import annotations

import calendar
import json
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .ig_supabase import sb_select, sb_update, sb_upsert
from .studio_calendar import StudioError

TABLE = "monthly_reports"


def _bounds(month: str) -> tuple[date, date]:
    try:
        first = date.fromisoformat(f"{month}-01")
    except ValueError:
        raise StudioError("REPORT_MONTH_INVALID") from None
    return first, first.replace(day=calendar.monthrange(first.year, first.month)[1])


def _prev(month: str) -> str:
    first, _ = _bounds(month)
    return (first - timedelta(days=1)).strftime("%Y-%m")


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


async def _paid(client_id: str, first: date, last: date) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for offset in range(0, 20000, 1000):
        chunk = await sb_select("ad_daily_stats", select="ad_id,ad_name,campaign_name,spend,impressions,reach,clicks,conversions,revenue",
                                limit=1000, offset=offset, order="stat_date.asc",
                                filters={"client_id": f"eq.{client_id}", "and": f"(stat_date.gte.{first},stat_date.lte.{last})"})
        rows.extend(chunk)
        if len(chunk) < 1000:
            break
    if not rows:
        return {}
    ads: Dict[str, Dict[str, Any]] = {}
    total = {"spend": 0.0, "impressions": 0.0, "clicks": 0.0, "conversions": 0.0, "revenue": 0.0}
    for r in rows:
        a = ads.setdefault(str(r.get("ad_id") or ""), {"anuncio": r.get("ad_name"), "campanha": r.get("campaign_name"),
                                                        "spend": 0.0, "impressions": 0.0, "clicks": 0.0, "conversions": 0.0, "revenue": 0.0})
        for k in total:
            v = _num(r.get(k))
            a[k] += v
            total[k] += v
    if not total["spend"]:
        return {}

    def view(a: Dict[str, Any]) -> Dict[str, Any]:
        return {"anuncio": a.get("anuncio"), "campanha": a.get("campanha"), "investimento": round(a["spend"], 2),
                "conversoes": int(a["conversions"]), "receita": round(a["revenue"], 2),
                "roas": round(a["revenue"] / a["spend"], 2) if a["spend"] and a["revenue"] else None,
                "ctr_pct": round(a["clicks"] / a["impressions"] * 100, 2) if a["impressions"] else None}
    spent = [a for a in ads.values() if a["spend"] >= 20]
    by_revenue = any(a["revenue"] for a in spent)
    spent.sort(key=lambda a: (a["revenue"] / a["spend"]) if by_revenue else (a["clicks"] / a["impressions"] if a["impressions"] else 0), reverse=True)
    return {"investimento": round(total["spend"], 2), "impressoes": int(total["impressions"]), "cliques": int(total["clicks"]),
            "conversoes": int(total["conversions"]), "receita": round(total["revenue"], 2),
            "roas": round(total["revenue"] / total["spend"], 2) if total["revenue"] else None,
            "custo_por_conversao": round(total["spend"] / total["conversions"], 2) if total["conversions"] else None,
            "anuncios": len(ads), "comparado_por": "retorno (ROAS)" if by_revenue else "taxa de cliques",
            "melhores": [view(a) for a in spent[:3]], "piores": [view(a) for a in spent[-2:]] if len(spent) >= 5 else []}


async def _whatsapp(client_id: str, first: date, last: date) -> Dict[str, Any]:
    from .whatsapp_insights import build_whatsapp_insights
    out = await build_whatsapp_insights(client_id, start=first.isoformat(), end=last.isoformat())
    if out.get("status") == "crm_unavailable" or not out.get("totals"):
        return {}
    t = out["totals"]
    if not t.get("conversations"):
        return {}
    return {"conversas": t.get("conversations"), "viraram_venda": t.get("converted_conversations"), "taxa_pct": t.get("conversion_rate"),
            "pedidos": t.get("orders"), "receita": t.get("revenue"), "parte_da_loja_pct": t.get("share_of_store_revenue"),
            "origens": [{"origem": o.get("label"), "conversas": o.get("conversations"), "vendas": o.get("sales"), "receita": o.get("revenue")}
                        for o in (out.get("origins") or [])][:5]}


async def _sales(client_id: str, first: date, last: date) -> Dict[str, Any]:
    from .whatsapp_insights import _shopify_orders

    async def month_total(a: date, b: date) -> tuple[int, float]:
        orders, _ = await _shopify_orders(client_id, f"{a}T03:00:00+00:00", f"{b + timedelta(days=1)}T02:59:59+00:00")
        return len(orders), sum(_num(o.get("value")) for o in orders)
    count, revenue = await month_total(first, last)
    if not count:
        return {}
    p_first, p_last = _bounds(_prev(first.strftime("%Y-%m")))
    p_count, p_revenue = await month_total(p_first, p_last)
    return {"pedidos": count, "faturamento": round(revenue, 2), "ticket_medio": round(revenue / count, 2),
            "pedidos_mes_anterior": p_count, "faturamento_mes_anterior": round(p_revenue, 2),
            "variacao_faturamento_pct": round((revenue - p_revenue) / p_revenue * 100, 1) if p_revenue else None}


async def build_business(client_id: str, month: str) -> Dict[str, Any]:
    first, last = _bounds(month)
    data: Dict[str, Any] = {"month": month, "built_at": datetime.now(timezone.utc).isoformat()}
    for key, fn in (("midia", _paid), ("whatsapp", _whatsapp), ("vendas", _sales)):
        try:
            data[key] = await fn(client_id, first, last)
        except Exception as exc:  # noqa: BLE001 - fonte fora do ar: a seção some, o resto segue
            print(f"[monthly_report] {key} unavailable error_type={type(exc).__name__}")
            data[key] = {}
    return data


async def _summary(client_id: str, data: Dict[str, Any], social: Optional[Dict[str, Any]]) -> Optional[str]:
    from .studio_llm import STR, arr, llm_json, obj
    slim = {k: data.get(k) for k in ("midia", "whatsapp", "vendas")}
    if social:
        slim["social"] = {k: social.get(k) for k in ("month_label", "overview")}
    if not any(slim.values()):
        return None
    try:
        out = await llm_json(client_id=client_id,
            instructions=("Você é o estrategista da agência Mugô fechando o mês do cliente. Escreva o resumo do mês em 3 a 5 "
                          "pontos curtos e depois 2 a 3 próximos passos práticos. Use SÓ os números dados (não invente métrica, "
                          "não arredonde para cima). Português do Brasil, direto, sem emoji, sem travessão."),
            prompt=json.dumps(slim, ensure_ascii=False, default=str), schema_name="monthly_report_summary",
            schema=obj({"resumo": arr(STR), "proximos_passos": arr(STR)}), temperature=0.3, timeout=60)
    except Exception as exc:  # noqa: BLE001 - sem IA, a equipe escreve
        print(f"[monthly_report] summary_failed error_type={type(exc).__name__}")
        return None
    resumo = [str(x).strip() for x in out.get("resumo") or [] if str(x).strip()][:5]
    passos = [str(x).strip() for x in out.get("proximos_passos") or [] if str(x).strip()][:3]
    text = "\n".join(resumo + ([""] + ["Próximos passos:"] + passos if passos else []))
    return text[:4000] or None


async def get_row(client_id: str, month: str) -> Optional[Dict[str, Any]]:
    rows = await sb_select(TABLE, select="*", limit=1, filters={"client_id": f"eq.{client_id}", "month": f"eq.{month}"})
    return rows[0] if rows else None


def view(row: Optional[Dict[str, Any]], *, agency: bool) -> Dict[str, Any]:
    if not row:
        return {"exists": False, "status": None}
    out = {"exists": True, "status": row.get("status"), "data": row.get("data") or {}, "summary": row.get("summary"),
           "released_at": row.get("released_at"), "updated_at": row.get("updated_at")}
    if agency:
        out["share_token"] = row.get("share_token")
    return out


async def close(client_id: str, month: str, *, refresh_social: bool = True) -> Dict[str, Any]:
    """Fecha (ou refaz) o mês: números de mídia, WhatsApp e vendas, o social e o resumo da IA. Mantém o status."""
    data = await build_business(client_id, month)
    social = None
    if refresh_social:
        try:
            from .social_report import build
            social = (await build(client_id, month)).get("data")
        except Exception as exc:  # noqa: BLE001 - sem Instagram, o relatório sai sem os slides de social
            print(f"[monthly_report] social_unavailable error_type={type(exc).__name__}")
    summary = await _summary(client_id, data, social)
    current = await get_row(client_id, month)
    row = {"client_id": client_id, "month": month, "data": data, "updated_at": datetime.now(timezone.utc).isoformat()}
    if summary or not current:
        row["summary"] = summary
    if not current:
        row["status"] = "rascunho"
    await sb_upsert(TABLE, [row], on_conflict="client_id,month")
    return await get_row(client_id, month) or row


async def save_summary(client_id: str, month: str, summary: str) -> Dict[str, Any]:
    rows = await sb_update(TABLE, filters={"client_id": f"eq.{client_id}", "month": f"eq.{month}"},
                           patch={"summary": summary.strip()[:4000] or None, "updated_at": datetime.now(timezone.utc).isoformat()})
    if not rows:
        raise StudioError("REPORT_NOT_BUILT")
    return rows[0]


async def set_status(client_id: str, month: str, *, release: bool, user_name: str) -> Dict[str, Any]:
    patch: Dict[str, Any] = {"status": "liberado" if release else "rascunho", "updated_at": datetime.now(timezone.utc).isoformat()}
    if release:
        patch.update({"released_at": datetime.now(timezone.utc).isoformat(), "released_by": user_name[:120]})
    else:
        patch["share_token"] = None  # voltou para rascunho: o link deixa de funcionar
    rows = await sb_update(TABLE, filters={"client_id": f"eq.{client_id}", "month": f"eq.{month}"}, patch=patch)
    if not rows:
        raise StudioError("REPORT_NOT_BUILT")
    return rows[0]


async def share(client_id: str, month: str) -> str:
    row = await get_row(client_id, month)
    if not row:
        raise StudioError("REPORT_NOT_BUILT")
    if row.get("status") != "liberado":
        raise StudioError("REPORT_NOT_RELEASED")
    if row.get("share_token"):
        return row["share_token"]
    token = secrets.token_urlsafe(24)
    await sb_update(TABLE, filters={"id": f"eq.{row['id']}"}, patch={"share_token": token}, returning="minimal")
    return token


async def client_can_see(client_id: str, month: str) -> bool:
    """Cliente vê o mês se ele foi liberado, ou se é de antes do fechamento automático (sem linha)."""
    row = await get_row(client_id, month)
    return row is None or row.get("status") == "liberado"


async def public(token: str) -> Dict[str, Any]:
    """Relatório pelo link (sem login): só mês liberado, só o que está no relatório."""
    if not token or len(token) < 24 or len(token) > 80:
        raise StudioError("REPORT_NOT_FOUND")
    rows = await sb_select(TABLE, select="*", limit=1, filters={"share_token": f"eq.{token}", "status": "eq.liberado"})
    if not rows:
        raise StudioError("REPORT_NOT_FOUND")
    row = rows[0]
    from .social_report import load
    try:
        social = await load(row["client_id"], row["month"])
    except Exception:  # noqa: BLE001
        social = {"built": False}
    client = await sb_select("clients", select="name", limit=1, filters={"id": f"eq.{row['client_id']}"})
    return {"month": row["month"], "brand": (client[0].get("name") if client else None) or "Marca",
            "business": row.get("data") or {}, "summary": row.get("summary"),
            "social": {k: social.get(k) for k in ("built", "data", "insights", "images")} if social.get("built") else {"built": False}}


async def close_all(now: Optional[datetime] = None) -> Dict[str, Any]:
    """Dia 1º: fecha o mês anterior de todas as marcas (não refaz o que já existe)."""
    now = now or datetime.now(timezone.utc)
    month = (now.date().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    clients = await sb_select("clients", select="id", limit=500)
    out = {"month": month, "closed": 0, "skipped": 0, "errors": 0}
    for c in clients:
        cid = str(c.get("id") or "")
        if not cid:
            continue
        if await get_row(cid, month):
            out["skipped"] += 1
            continue
        try:
            await close(cid, month)
            out["closed"] += 1
        except Exception as exc:  # noqa: BLE001
            out["errors"] += 1
            print(f"[monthly_report] close_failed error_type={type(exc).__name__}")
    return out
