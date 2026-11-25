"""Leitura da IA das campanhas NO AR (Mídia On): Meta (conta inteira, ao vivo) e Google (sincronização diária).

O Resumo Executivo mostra a estratégia salva (pode ser de semanas atrás) e julgava tudo por receita/ROAS. Aqui:

1. lê da Meta TODAS as campanhas ativas da conta (do MUGOVERSO ou do Gerenciador), desde o início e últimos 7 dias,
   e do Google as campanhas que gastaram nos últimos dias (30 e 7 dias, da sincronização diária)
   (gasto, alcance, frequência, cliques, CTR, CPC, CPM, resultado do objetivo e, em vendas, valor de compra);
2. calcula sem IA os indicadores CERTOS para o objetivo de cada campanha (alcance: CPM e frequência; tráfego:
   CPC e CTR do link; vendas: ROAS e custo por compra; cadastros: custo por cadastro) e marca o que é sinal
   (fase de aprendizado, frequência alta, CTR baixo, verba acabando, campanha parada);
3. a IA (modelo forte + cérebro da marca + o que posts e anúncios já renderam) escreve o diagnóstico de cada
   campanha e as próximas ações, sempre pelo objetivo dela, e nunca chama de "sem conversão" uma campanha de
   alcance ou tráfego.

Cache de 30 min por marca (a Meta fecha os números com atraso; "Atualizar" força a releitura).
"""
from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

CACHE_TTL = 30 * 60
MAX_CAMPAIGNS = 20
_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}

OBJECTIVE_LABEL = {"vendas": "Vendas", "leads": "Cadastros", "trafego": "Tráfego para o site", "alcance": "Alcance",
                   "whatsapp": "Conversas no WhatsApp", "retencao": "Clientes que já compraram", "remarketing": "Remarketing",
                   "engajamento": "Engajamento"}
PURCHASE_VALUES = ("offsite_conversion.fb_pixel_purchase", "purchase", "omni_purchase")
# Referências amplas de mercado (Meta, Brasil) só para marcar sinal; a IA decide com o contexto.
CTR_LOW, CTR_GOOD = 0.8, 1.5          # CTR de link, %
FREQ_HIGH = 3.0                        # frequência média
LEARNING_DAYS = 3


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def kpis(objective: str, n: Dict[str, float]) -> Dict[str, Any]:
    """Indicadores do objetivo a partir dos totais. Puro, para teste."""
    spend, imp, reach = n.get("spend", 0.0), n.get("impressions", 0.0), n.get("reach", 0.0)
    link, results, value = n.get("link_clicks", 0.0), n.get("results", 0.0), n.get("purchase_value", 0.0)
    out: Dict[str, Any] = {
        "investido": round(spend, 2), "impressoes": int(imp), "alcance": int(reach),
        "frequencia": round(imp / reach, 2) if reach else None,
        "cpm": round(spend / imp * 1000, 2) if imp else None,
        "cliques_no_link": int(link), "ctr_link_pct": round(link / imp * 100, 2) if imp else None,
        "cpc_link": round(spend / link, 2) if link else None,
    }
    if objective in ("vendas", "retencao", "remarketing"):
        out.update({"compras": int(results), "custo_por_compra": round(spend / results, 2) if results else None,
                    "valor_de_compras": round(value, 2), "roas": round(value / spend, 2) if spend and value else None})
    elif objective in ("leads", "whatsapp", "engajamento"):
        out.update({"resultados": int(results), "custo_por_resultado": round(spend / results, 2) if results else None})
    return out


def flags(objective: str, total: Dict[str, Any], week: Dict[str, Any], *, days_running: Optional[int],
          days_left: Optional[int]) -> List[str]:
    """Sinais que a IA precisa considerar (regras fixas). Puro, para teste."""
    out: List[str] = []
    if days_running is not None and days_running < LEARNING_DAYS:
        out.append(f"no ar há {days_running} dia(s): ainda em fase de aprendizado, não julgar custo como definitivo")
    freq = total.get("frequencia")
    if freq and freq >= FREQ_HIGH:
        out.append(f"frequência {freq:.1f}: o mesmo público está vendo várias vezes (risco de saturação)")
    ctr = total.get("ctr_link_pct")
    if objective in ("trafego", "vendas", "leads", "remarketing") and ctr is not None and total.get("impressoes", 0) >= 2000:
        if ctr < CTR_LOW:
            out.append(f"CTR do link {ctr:.2f}%: baixo, o criativo ou a oferta não estão puxando o clique")
        elif ctr >= CTR_GOOD:
            out.append(f"CTR do link {ctr:.2f}%: bom")
    if week.get("investido", 0) == 0 and total.get("investido", 0) > 0:
        out.append("sem gasto nos últimos 7 dias: campanha parada ou sem entrega")
    if days_left is not None and 0 <= days_left <= 3:
        out.append(f"termina em {days_left} dia(s)")
    if objective in ("vendas", "retencao", "remarketing") and total.get("investido", 0) >= 100 and not total.get("compras"):
        out.append("já investiu sem nenhuma compra registrada pelo pixel (conferir pixel/evento antes de concluir)")
    return out


def _days(start: Any, end: Any, today: date) -> Tuple[Optional[int], Optional[int]]:
    def parse(v: Any) -> Optional[date]:
        try:
            return date.fromisoformat(str(v)[:10])
        except (TypeError, ValueError):
            return None
    s, e = parse(start), parse(end)
    return ((today - s).days if s else None), ((e - today).days if e else None)


# Objetivo da Meta (API) → objetivo do MUGOVERSO, para campanhas criadas fora dele.
META_OBJECTIVE = {
    "OUTCOME_SALES": "vendas", "CONVERSIONS": "vendas", "PRODUCT_CATALOG_SALES": "vendas",
    "OUTCOME_LEADS": "leads", "LEAD_GENERATION": "leads",
    "OUTCOME_TRAFFIC": "trafego", "LINK_CLICKS": "trafego", "OUTCOME_APP_PROMOTION": "trafego", "APP_INSTALLS": "trafego",
    "OUTCOME_AWARENESS": "alcance", "REACH": "alcance", "BRAND_AWARENESS": "alcance",
    "OUTCOME_ENGAGEMENT": "engajamento", "POST_ENGAGEMENT": "engajamento", "VIDEO_VIEWS": "engajamento", "PAGE_LIKES": "engajamento",
    "MESSAGES": "whatsapp",
}
RESULT_ACTIONS = {
    "leads": ("offsite_conversion.fb_pixel_lead", "lead", "onsite_conversion.lead_grouped"),
    "vendas": PURCHASE_VALUES, "retencao": PURCHASE_VALUES, "remarketing": PURCHASE_VALUES,
    "trafego": ("link_click",), "engajamento": ("post_engagement",),
    "whatsapp": ("onsite_conversion.messaging_conversation_started_7d", "onsite_conversion.total_messaging_connection"),
}
GOOGLE = "google"
GOOGLE_DAYS = 30
ACTIVE_GOOGLE_DAYS = 3  # o Google não guarda status aqui: "no ar" = gastou nos últimos 3 dias com dados


def meta_totals(line: Dict[str, Any], objective: str) -> Dict[str, float]:
    """Uma linha de insights (nível campanha) → totais usados por kpis(). Puro, para teste."""
    actions = {a.get("action_type"): _num(a.get("value")) for a in line.get("actions") or []}
    values = {a.get("action_type"): _num(a.get("value")) for a in line.get("action_values") or []}
    out = {"spend": _num(line.get("spend")), "impressions": _num(line.get("impressions")), "reach": _num(line.get("reach")),
           "link_clicks": _num(line.get("inline_link_clicks")),
           "results": next((actions[k] for k in RESULT_ACTIONS.get(objective, ()) if k in actions), 0.0),
           "purchase_value": next((values[k] for k in PURCHASE_VALUES if k in values), 0.0)}
    if objective == "alcance":
        out["results"] = out["reach"]
    return out


def google_kpis(n: Dict[str, float]) -> Dict[str, Any]:
    """Indicadores de uma campanha do Google (Pesquisa, PMax, Shopping). Puro, para teste."""
    spend, imp, clicks = n.get("cost", 0.0), n.get("impressions", 0.0), n.get("clicks", 0.0)
    conv, value = n.get("conversions", 0.0), n.get("conversion_value", 0.0)
    return {"investido": round(spend, 2), "impressoes": int(imp), "cliques": int(clicks),
            "ctr_pct": round(clicks / imp * 100, 2) if imp else None, "cpc": round(spend / clicks, 2) if clicks else None,
            "conversoes": round(conv, 1), "custo_por_conversao": round(spend / conv, 2) if conv else None,
            "valor_de_conversoes": round(value, 2), "roas": round(value / spend, 2) if spend and value else None}


def google_campaigns(rows: List[Dict[str, Any]], today: date) -> List[Dict[str, Any]]:
    """Linhas diárias por campanha (google_ads_daily_stats) → campanhas no ar com 30 e 7 dias. Puro, para teste."""
    if not rows:
        return []
    last_day = max(str(r.get("stat_date") or "")[:10] for r in rows)
    last = date.fromisoformat(last_day)
    week_from, active_from = (last.toordinal() - 6), (last.toordinal() - ACTIVE_GOOGLE_DAYS + 1)
    keys = ("cost", "impressions", "clicks", "conversions", "conversion_value")
    by: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        cid = str(r.get("campaign_id") or "")
        if not cid:
            continue
        day = date.fromisoformat(str(r.get("stat_date"))[:10]).toordinal()
        item = by.setdefault(cid, {"name": r.get("campaign_name") or "Campanha Google", "total": dict.fromkeys(keys, 0.0),
                                   "week": dict.fromkeys(keys, 0.0), "recent": 0.0, "first": day})
        item["first"] = min(item["first"], day)
        for k in keys:
            item["total"][k] += _num(r.get(k))
            if day >= week_from:
                item["week"][k] += _num(r.get(k))
        if day >= active_from:
            item["recent"] += _num(r.get("cost"))
    out = []
    stale = (today - last).days
    for cid, item in by.items():
        if item["recent"] <= 0:
            continue
        t, w = google_kpis(item["total"]), google_kpis(item["week"])
        signals = [f"dados do Google sincronizados até {last_day}" + (f" ({stale} dia(s) atrás)" if stale > 1 else "")]
        if t["investido"] >= 100 and not t["conversoes"]:
            signals.append("já investiu sem nenhuma conversão registrada no Google (conferir a tag de conversão)")
        if t["ctr_pct"] is not None and t["impressoes"] >= 2000 and t["ctr_pct"] < 1:
            signals.append(f"CTR {t['ctr_pct']:.2f}%: baixo para Google (anúncio ou palavra-chave pouco relevante)")
        out.append({"id": f"google:{cid}", "canal": "Google", "campanha": item["name"], "objetivo": "Google Ads",
                    "objetivo_id": GOOGLE, "periodo": f"últimos {GOOGLE_DAYS} dias", "desde_o_inicio": t, "ultimos_7_dias": w,
                    "sinais": signals})
    return out


async def _meta_campaigns(client_id: str, today: date) -> List[Dict[str, Any]]:
    """Todas as campanhas ATIVAS da conta de anúncios (criadas no MUGOVERSO ou no Gerenciador)."""
    import json
    from . import meta_ad_publisher as pub
    from .meta_live_insights import _paged
    account = await pub._ad_account(client_id)
    act, token = account["act"], account["token"]
    fields = "campaign_id,spend,impressions,reach,inline_link_clicks,actions,action_values"
    camps, total_rows, week_rows = await asyncio.gather(
        _paged(f"/{act}/campaigns", token, {"limit": 100, "fields": "id,name,objective,effective_status,daily_budget,lifetime_budget,start_time,stop_time",
                                           "effective_status": json.dumps(["ACTIVE"])}),
        _paged(f"/{act}/insights", token, {"level": "campaign", "fields": fields, "date_preset": "maximum", "limit": 200}),
        _paged(f"/{act}/insights", token, {"level": "campaign", "fields": fields, "date_preset": "last_7d", "limit": 200}),
    )
    try:
        drafts = {str((r.get("meta_ids") or {}).get("campaign_id")): r.get("payload") or {}
                  for r in await pub.list_drafts(client_id) if (r.get("meta_ids") or {}).get("campaign_id")}
    except Exception:  # noqa: BLE001
        drafts = {}
    totals = {str(r.get("campaign_id")): r for r in total_rows or []}
    weeks = {str(r.get("campaign_id")): r for r in week_rows or []}
    out = []
    for c in camps or []:
        cid = str(c.get("id"))
        draft = drafts.get(cid, {})
        objective = str(draft.get("objective") or META_OBJECTIVE.get(str(c.get("objective") or ""), "engajamento"))
        t = kpis(objective, meta_totals(totals.get(cid, {}), objective))
        w = kpis(objective, meta_totals(weeks.get(cid, {}), objective))
        if not t["investido"]:
            continue
        start = draft.get("start_date") or c.get("start_time")
        end = draft.get("end_date") or c.get("stop_time")
        running, left = _days(start, end, today)
        budget = draft.get("daily_budget") or (round(_num(c.get("daily_budget")) / 100, 2) or None)
        out.append({"id": f"meta:{cid}", "canal": "Meta", "campanha": c.get("name") or draft.get("name") or "Campanha",
                    "objetivo": OBJECTIVE_LABEL.get(objective, objective), "objetivo_id": objective,
                    "criada_no_mugoverso": bool(draft), "verba_diaria": budget, "inicio": str(start or "")[:10] or None,
                    "fim": str(end or "")[:10] or None, "dias_no_ar": running, "dias_restantes": left,
                    "desde_o_inicio": t, "ultimos_7_dias": w, "sinais": flags(objective, t, w, days_running=running, days_left=left)})
    return out


async def _google_campaigns(client_id: str, today: date) -> List[Dict[str, Any]]:
    from datetime import timedelta
    from .google_ads import resolve_google_ads_context
    from .ig_supabase import sb_select
    context = await resolve_google_ads_context(client_id)
    start = (today - timedelta(days=GOOGLE_DAYS)).isoformat()
    rows = await sb_select("google_ads_daily_stats", filters={
        "client_id": f"eq.{client_id}", "connection_id": f"eq.{context.connection_id}", "customer_id": f"eq.{context.customer_id}",
        "stat_date": f"gte.{start}"}, limit=20000)
    return google_campaigns(rows, today)


async def collect(client_id: str, today: Optional[date] = None) -> List[Dict[str, Any]]:
    """Campanhas no ar agora, Meta (conta inteira) e Google. Um canal fora do ar não derruba o outro."""
    today = today or datetime.now(timezone.utc).date()
    found: List[Dict[str, Any]] = []
    for name, job in (("meta", _meta_campaigns(client_id, today)), ("google", _google_campaigns(client_id, today))):
        try:
            found.extend(await job)
        except Exception as exc:  # noqa: BLE001 (sem conexão do canal é normal)
            print(f"[media_live_read] {name}_unavailable client_id={client_id} error_type={type(exc).__name__}")
    found.sort(key=lambda c: -(c["ultimos_7_dias"].get("investido") or 0))
    return found[:MAX_CAMPAIGNS]


SCHEMA_NOTE = "veredito: escalar, manter, ajustar ou pausar."
INSTRUCTIONS = (
    "Você é o gestor de tráfego sênior da agência, lendo as campanhas que estão NO AR agora na Meta e no Google. "
    "Seja sagaz, direto e específico, como num WhatsApp para o dono da marca.\n"
    "REGRAS:\n"
    "- Julgue cada campanha PELO OBJETIVO DELA: Alcance → CPM, frequência e pessoas alcançadas; Tráfego → custo por clique no "
    "link e CTR do link; Vendas → ROAS, custo por compra e valor vendido; Cadastros/WhatsApp → custo por resultado; "
    "Google Ads → custo por conversão, ROAS, CPC e CTR. "
    "Nunca diga que uma campanha de alcance ou tráfego está 'sem conversão' ou com 'ROAS zero': não é o trabalho dela. "
    "Se for o caso, diga o que ela entrega para o funil (ex.: tráfego barato que pode alimentar remarketing).\n"
    "- Compare desde o início com os últimos 7 dias para dizer se está melhorando ou piorando. Compare Meta e Google entre si "
    "quando tiverem o mesmo papel (ex.: custo por venda nos dois).\n"
    "- EXPLICAÇÕES: o que nos números explica o resultado de cada campanha (ex.: CTR baixo puxa o CPC, frequência alta encarece, "
    "fase de aprendizado). Fale em sinal, não em certeza.\n"
    "- MELHORIAS: o que mudar para melhorar, campanha por campanha, em ordem de impacto.\n"
    "- Respeite os SINAIS (fase de aprendizado, frequência alta, CTR baixo, campanha parada, termina logo).\n"
    "- Use o calendário: datas como Black Friday mudam o que fazer (ex.: aquecer público antes, converter na data).\n"
    "- Use o CÉREBRO DA MARCA e o que posts e anúncios já renderam para dar ação com cara da marca.\n"
    "- Ação concreta e executável (ex.: 'subir a verba de R$ 30 para R$ 45/dia', 'trocar o criativo 2 pelo Reels X', "
    "'criar remarketing com quem clicou'). Nada genérico como 'monitorar diariamente'.\n"
    "- Não invente número: use só os dados. Português do Brasil, sem travessão. " + SCHEMA_NOTE
)


def _schema() -> Dict[str, Any]:
    from .studio_llm import STR, arr, obj
    return obj({"resumo": STR, "campanhas": arr(obj({"id": STR, "veredito": {"type": "string", "enum": ["escalar", "manter", "ajustar", "pausar"]},
                                                      "leitura": STR, "acao": STR})),
                "explicacoes": arr(obj({"id": STR, "texto": STR})), "melhorias": arr(obj({"id": STR, "texto": STR})),
                "proximos_passos": arr(STR)})


async def read(client_id: str, *, refresh: bool = False) -> Dict[str, Any]:
    hit = _CACHE.get(client_id)
    if hit and not refresh and time.monotonic() - hit[0] < CACHE_TTL:
        return {**hit[1], "cached": True}
    import json
    from .studio_llm import llm_json
    today = datetime.now(timezone.utc).date()
    campaigns = await collect(client_id, today)
    checked_at = datetime.now(timezone.utc).isoformat()
    if not campaigns:
        result = {"resumo": None, "campanhas": [], "proximos_passos": [], "checked_at": checked_at,
                  "explicacoes": [], "melhorias": [],
                  "message": "Nenhuma campanha no ar com investimento na Meta ou no Google agora."}
        _CACHE[client_id] = (time.monotonic(), result)
        return result
    prompt = (f"HOJE: {today.isoformat()}\nCAMPANHAS NO AR (Meta e Google; valores em reais):\n"
              + json.dumps([{k: v for k, v in c.items() if k != "objetivo_id"} for c in campaigns], ensure_ascii=False)
              + "\n\nEscreva: resumo (2 a 3 frases, o que está funcionando e o que não está, com número), uma leitura e uma ação "
                "por campanha (use o id recebido), explicacoes (o que explica o resultado, uma por campanha relevante, com o id), "
                "melhorias (o que pode melhorar, com o id, em ordem de impacto) e até 4 próximos passos em ordem de prioridade.")
    data = await llm_json(brand="estrategia", client_id=client_id, instructions=INSTRUCTIONS, prompt=prompt,
                          schema_name="media_live_read", schema=_schema(), temperature=0.3, timeout=90, guidance=False)
    by_id = {c["id"]: c for c in campaigns}
    reads = []
    for item in data.get("campanhas") or []:
        c = by_id.get(str(item.get("id")))
        if c:
            reads.append({"id": c["id"], "canal": c.get("canal", "Meta"), "campanha": c["campanha"], "objetivo": c["objetivo"],
                          "veredito": item.get("veredito"),
                          "leitura": str(item.get("leitura") or "")[:600], "acao": str(item.get("acao") or "")[:400],
                          "numeros": c["desde_o_inicio"], "ultimos_7_dias": c["ultimos_7_dias"], "sinais": c["sinais"]})
    def notes(key: str) -> List[Dict[str, Any]]:
        out = []
        for item in data.get(key) or []:
            c = by_id.get(str(item.get("id")))
            if c and str(item.get("texto") or "").strip():
                out.append({"id": c["id"], "canal": c.get("canal", "Meta"), "campanha": c["campanha"], "texto": str(item["texto"])[:500]})
        return out[:8]
    result = {"resumo": str(data.get("resumo") or "")[:800] or None, "campanhas": reads,
              "explicacoes": notes("explicacoes"), "melhorias": notes("melhorias"),
              "proximos_passos": [str(p)[:300] for p in data.get("proximos_passos") or []][:4], "checked_at": checked_at}
    _CACHE[client_id] = (time.monotonic(), result)
    return result
