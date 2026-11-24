"""Leitura da IA das campanhas NO AR (Mídia On), com os números da Meta de agora.

O Resumo Executivo mostra a estratégia salva (pode ser de semanas atrás) e julgava tudo por receita/ROAS. Aqui:

1. lê da Meta, por campanha publicada pelo MUGOVERSO, os números desde o início e dos últimos 7 dias
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
MAX_CAMPAIGNS = 12
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


async def _insights(client_id: str, row: Dict[str, Any], preset: str) -> Dict[str, float]:
    from . import meta_ad_publisher as pub
    _, ids, account = await pub._published(client_id, row["id"])
    payload = pub.clean_payload(row.get("payload") or {})
    objects = pub._ads_of(ids) if ids.get("joined") else [str(ids["campaign_id"])]
    wanted = pub.RESULT_ACTIONS.get(payload["objective"], ())
    total = {"spend": 0.0, "impressions": 0.0, "reach": 0.0, "link_clicks": 0.0, "results": 0.0, "purchase_value": 0.0}
    for object_id in objects:
        body = await pub._graph("GET", f"/{object_id}/insights", token=account["token"],
                                params={"fields": "spend,impressions,reach,inline_link_clicks,actions,action_values", "date_preset": preset})
        for line in body.get("data") or []:
            total["spend"] += _num(line.get("spend"))
            total["impressions"] += _num(line.get("impressions"))
            total["reach"] += _num(line.get("reach"))
            total["link_clicks"] += _num(line.get("inline_link_clicks"))
            actions = {a.get("action_type"): _num(a.get("value")) for a in line.get("actions") or []}
            values = {a.get("action_type"): _num(a.get("value")) for a in line.get("action_values") or []}
            total["results"] += next((actions[k] for k in wanted if k in actions), 0.0)
            total["purchase_value"] += next((values[k] for k in PURCHASE_VALUES if k in values), 0.0)
    if payload["objective"] == "alcance":
        total["results"] = total["reach"]
    return total


async def collect(client_id: str, today: Optional[date] = None) -> List[Dict[str, Any]]:
    """Campanhas publicadas pelo MUGOVERSO com os números de agora (falha de uma não derruba as outras)."""
    from . import meta_ad_publisher as pub
    today = today or datetime.now(timezone.utc).date()
    rows = [r for r in await pub.list_drafts(client_id) if (r.get("meta_ids") or {}).get("campaign_id")][:MAX_CAMPAIGNS]
    gate = asyncio.Semaphore(4)

    async def one(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        payload = row.get("payload") or {}
        objective = str(payload.get("objective") or "")
        async with gate:
            try:
                total, week = await asyncio.gather(_insights(client_id, row, "maximum"), _insights(client_id, row, "last_7d"))
            except Exception as exc:  # noqa: BLE001
                print(f"[media_live_read] insights_failed client_id={client_id} error_type={type(exc).__name__}")
                return None
        running, left = _days(payload.get("start_date"), payload.get("end_date"), today)
        t, w = kpis(objective, total), kpis(objective, week)
        if not t["investido"]:
            return None
        return {"id": row["id"], "campanha": payload.get("name"), "objetivo": OBJECTIVE_LABEL.get(objective, objective),
                "objetivo_id": objective, "verba_diaria": payload.get("daily_budget"),
                "inicio": payload.get("start_date"), "fim": payload.get("end_date"), "dias_no_ar": running, "dias_restantes": left,
                "desde_o_inicio": t, "ultimos_7_dias": w, "sinais": flags(objective, t, w, days_running=running, days_left=left)}

    found = await asyncio.gather(*(one(r) for r in rows))
    return [c for c in found if c]


SCHEMA_NOTE = "veredito: escalar, manter, ajustar ou pausar."
INSTRUCTIONS = (
    "Você é o gestor de tráfego sênior da agência, lendo as campanhas que estão NO AR agora, com os números da Meta de hoje. "
    "Seja sagaz, direto e específico, como num WhatsApp para o dono da marca.\n"
    "REGRAS:\n"
    "- Julgue cada campanha PELO OBJETIVO DELA: Alcance → CPM, frequência e pessoas alcançadas; Tráfego → custo por clique no "
    "link e CTR do link; Vendas → ROAS, custo por compra e valor vendido; Cadastros/WhatsApp → custo por resultado. "
    "Nunca diga que uma campanha de alcance ou tráfego está 'sem conversão' ou com 'ROAS zero': não é o trabalho dela. "
    "Se for o caso, diga o que ela entrega para o funil (ex.: tráfego barato que pode alimentar remarketing).\n"
    "- Compare desde o início com os últimos 7 dias para dizer se está melhorando ou piorando.\n"
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
                  "message": "Nenhuma campanha publicada pelo MUGOVERSO com investimento na Meta ainda."}
        _CACHE[client_id] = (time.monotonic(), result)
        return result
    prompt = (f"HOJE: {today.isoformat()}\nCAMPANHAS NO AR (números da Meta; valores em reais):\n"
              + json.dumps([{k: v for k, v in c.items() if k != "objetivo_id"} for c in campaigns], ensure_ascii=False)
              + "\n\nEscreva: resumo (2 a 3 frases, o que está funcionando e o que não está, com número), uma leitura e uma ação "
                "por campanha (use o id recebido) e até 4 próximos passos em ordem de prioridade.")
    data = await llm_json(brand="estrategia", client_id=client_id, instructions=INSTRUCTIONS, prompt=prompt,
                          schema_name="media_live_read", schema=_schema(), temperature=0.3, timeout=90, guidance=False)
    by_id = {c["id"]: c for c in campaigns}
    reads = []
    for item in data.get("campanhas") or []:
        c = by_id.get(str(item.get("id")))
        if c:
            reads.append({"id": c["id"], "campanha": c["campanha"], "objetivo": c["objetivo"], "veredito": item.get("veredito"),
                          "leitura": str(item.get("leitura") or "")[:600], "acao": str(item.get("acao") or "")[:400],
                          "numeros": c["desde_o_inicio"], "ultimos_7_dias": c["ultimos_7_dias"], "sinais": c["sinais"]})
    result = {"resumo": str(data.get("resumo") or "")[:800] or None, "campanhas": reads,
              "proximos_passos": [str(p)[:300] for p in data.get("proximos_passos") or []][:4], "checked_at": checked_at}
    _CACHE[client_id] = (time.monotonic(), result)
    return result
