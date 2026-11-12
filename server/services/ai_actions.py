"""Ações da IA: o número pede ação → a IA executa sozinha com as ferramentas do MUGOVERSO → resultado medido.

Com tudo conectado, não há fila de aprovação: cada ação detectada roda na hora (``AUTO_KINDS``) e fica no
histórico com o que foi feito. O que sai para o cliente final tem janela para a equipe desistir:
- campanha_reativacao: cria a campanha de e-mail para quem está sem comprar (só quem aceitou) e agenda para daqui a
  ``REACTIVATION_DELAY_HOURS`` h; cancelar a campanha no E-mail marketing desiste do envio;
- ligar_fluxo: liga o fluxo de segunda compra (e-mail);
- ligar_carrinho: liga a sequência de e-mail do carrinho (Shopify: também o aviso de checkout; outras lojas: quando os
  carrinhos já chegam pelo webhook genérico);
- alerta_cac: só informa (CAC do mês muito acima da média), fica como "ciente".
Tipo fora de ``AUTO_KINDS`` continua como proposta para aprovar.

Os detectores são funções puras sobre um retrato dos números (``detect``). A IA (OpenAI, mesma chave do resto)
só escreve título, explicação e o texto da campanha; sem chave, entra um texto padrão — a ação continua valendo.
``dedupe_key`` (tipo + mês) evita repropor a mesma coisa.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .ig_supabase import sb_insert, sb_select, sb_update

TABLE = "ai_actions"
FIELDS = "id,kind,title,rationale,evidence,payload,status,proposed_at,decided_at,executed_at,result,error"
MIN_REACTIVATION = 50
MIN_CUSTOMERS_FLOW = 100
MIN_CARTS_SIGNAL = 50
CAC_ALERT_RATIO = 1.3
AUTO_KINDS = {"campanha_reativacao", "ligar_fluxo", "ligar_carrinho", "alerta_cac"}
REACTIVATION_DELAY_HOURS = 24


class ActionError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(code)
        self.code = code
        self.message = message
        self.status = status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _money(v: float) -> str:
    return f"R$ {v:,.0f}".replace(",", ".")


# ---------------------------------------------------------------- detectores (puros)

def detect(snapshot: Dict[str, Any], *, month: str) -> List[Dict[str, Any]]:
    """Recebe números já calculados e devolve as propostas cabíveis (sem texto da IA ainda)."""
    out: List[Dict[str, Any]] = []
    inactive = int(snapshot.get("inactive_with_consent") or 0)
    if snapshot.get("sender_ready") and inactive >= MIN_REACTIVATION and not snapshot.get("recent_reactivation_campaign"):
        out.append({"kind": "campanha_reativacao", "dedupe_key": f"campanha_reativacao:{month}",
                    "evidence": {"inactive_with_consent": inactive, "days": 90,
                                 "avg_ticket": snapshot.get("avg_ticket")},
                    "payload": {"audience": {"segment": "sem_compra", "days": 90, "only_consent": True}}})
    repeat = snapshot.get("repeat_rate")
    flows = snapshot.get("flows_enabled") or []
    if (snapshot.get("customers") or 0) >= MIN_CUSTOMERS_FLOW and repeat is not None and repeat < 30 and "segunda_compra" not in flows \
            and snapshot.get("sender_ready"):
        out.append({"kind": "ligar_fluxo", "dedupe_key": f"ligar_fluxo:segunda_compra:{month}",
                    "evidence": {"repeat_rate": repeat, "customers": snapshot.get("customers"),
                                 "median_days_to_second": snapshot.get("median_days_to_second")},
                    "payload": {"flow": "segunda_compra", "delay_days": int(snapshot.get("median_days_to_second") or 30)}})
    shopify_signal = snapshot.get("provider") == "shopify" and int(snapshot.get("orders_30d") or 0) >= MIN_CARTS_SIGNAL
    other_store_signal = snapshot.get("provider") not in (None, "shopify") and int(snapshot.get("carts_30d") or 0) > 0  # webhook genérico ligado
    if (shopify_signal or other_store_signal) and not snapshot.get("cart_enabled") and snapshot.get("sender_ready"):
        out.append({"kind": "ligar_carrinho", "dedupe_key": f"ligar_carrinho:{month}",
                    "evidence": {"orders_30d": snapshot.get("orders_30d"), "carts_30d": snapshot.get("carts_30d")},
                    "payload": {"steps": [{"channel": "email", "delay_minutes": 60}, {"channel": "email", "delay_minutes": 1440}]}})
    last, avg = snapshot.get("cac_last_month"), snapshot.get("cac_avg_prev")
    if last and avg and last > avg * CAC_ALERT_RATIO:
        out.append({"kind": "alerta_cac", "dedupe_key": f"alerta_cac:{month}",
                    "evidence": {"cac_last_month": last, "cac_avg_prev": avg, "increase_pct": round((last / avg - 1) * 100, 1)},
                    "payload": {}})
    return out


DEFAULT_TEXT = {
    "campanha_reativacao": lambda e: (f"Reativar {e['inactive_with_consent']} clientes que pararam de comprar",
                                      f"{e['inactive_with_consent']} clientes que aceitaram receber e-mails não compram há mais de 90 dias. "
                                      "Uma campanha de reativação costuma trazer parte deles de volta sem custo de mídia."),
    "ligar_fluxo": lambda e: ("Ligar o fluxo de segunda compra",
                              f"Só {e['repeat_rate']}% dos clientes compraram de novo. Um e-mail automático no momento em que a "
                              "segunda compra costuma acontecer aumenta a recompra."),
    "ligar_carrinho": lambda e: ("Ligar a recuperação de carrinho por e-mail",
                                 f"A loja teve {e['orders_30d']} pedidos em 30 dias e a recuperação de carrinho está desligada. "
                                 "Quem abandona o checkout recebe um lembrete em 1 h e outro em 24 h."),
    "alerta_cac": lambda e: (f"CAC subiu {e['increase_pct']}% no último mês",
                             f"O custo para trazer um cliente novo foi {_money(e['cac_last_month'])}, contra a média de "
                             f"{_money(e['cac_avg_prev'])} nos meses anteriores. Vale revisar campanhas e públicos."),
}


async def _write_copy(client_id: str, proposal: Dict[str, Any], brand: str) -> Dict[str, Any]:
    """Título/explicação (e, na reativação, assunto e texto do e-mail) escritos pela IA, com fallback padrão."""
    title, rationale = DEFAULT_TEXT[proposal["kind"]](proposal["evidence"])
    copy: Dict[str, Any] = {"title": title, "rationale": rationale}
    if proposal["kind"] == "campanha_reativacao":
        copy.update({"subject": "Sentimos sua falta, {{primeiro_nome}}",
                     "text": "Faz um tempo que você não passa por aqui. Chegou muita coisa nova — vem ver."})
    try:
        from .studio_llm import llm_json, obj
        schema = obj({"title": {"type": "string"}, "rationale": {"type": "string"}, "subject": {"type": "string"}, "text": {"type": "string"}})
        data = await llm_json(
            instructions=("Você é a analista de CRM da agência Mugô. Escreva em português do Brasil, direto, sem exagero. "
                          "Use só os números dados; não invente desconto, prazo nem promoção. Título com até 70 caracteres; "
                          "explicação com até 3 frases dizendo o que os dados mostram e o que a ação faz. "
                          "Se a ação for campanha de reativação, escreva também o assunto (pode usar {{primeiro_nome}}) e um texto curto "
                          "do e-mail (2 frases); senão devolva subject e text vazios."),
            prompt=f"Marca: {brand}\nAção: {proposal['kind']}\nDados: {proposal['evidence']}",
            schema_name="ai_action_copy", schema=schema, temperature=0.4, timeout=40, client_id=client_id, max_output_tokens=500)
        for key in ("title", "rationale", "subject", "text"):
            if str(data.get(key) or "").strip() and (key in ("title", "rationale") or proposal["kind"] == "campanha_reativacao"):
                copy[key] = str(data[key]).strip()[:2000 if key == "rationale" else 200]
    except Exception as exc:  # noqa: BLE001 — sem IA, a proposta segue com o texto padrão
        print(f"[ai_actions] copy_fallback client_id={client_id} {type(exc).__name__}")
    return copy


# ---------------------------------------------------------------- retrato dos números

async def snapshot(client_id: str) -> Dict[str, Any]:
    from . import cart_recovery, commercial_flows, email_marketing
    from .customer_value import overview as value_overview
    provider, contacts = await email_marketing.load_contacts(client_id)
    blocked = await email_marketing.suppressed(client_id)
    inactive = email_marketing.select_audience(contacts, {"segment": "sem_compra", "days": 90, "only_consent": True}, blocked=blocked)
    status = await email_marketing.sender_status(client_id)
    since = (_now() - timedelta(days=14)).isoformat()
    recent = await sb_select("email_campaigns", select="id,audience", filters={"client_id": f"eq.{client_id}", "created_at": f"gte.{since}"}, limit=50)
    flows = [f["kind"] for f in await commercial_flows.list_flows(client_id) if f.get("enabled")]
    cart = await cart_recovery.get_settings(client_id)
    snap: Dict[str, Any] = {
        "provider": provider, "sender_ready": status.get("ready") or (status.get("from_email") and not status.get("send_enabled")),
        "inactive_with_consent": len(inactive), "recent_reactivation_campaign": any((c.get("audience") or {}).get("segment") == "sem_compra" for c in recent),
        "flows_enabled": flows, "cart_enabled": bool(cart.get("enabled")),
    }
    since30 = (_now() - timedelta(days=30)).isoformat()
    if provider == "shopify":
        orders = await sb_select("shopify_orders", select="shopify_order_id", filters={"client_id": f"eq.{client_id}", "created_at_shopify": f"gte.{since30}"},
                                 limit=1000)
        snap["orders_30d"] = len(orders)
        carts = await sb_select("abandoned_carts", select="checkout_id", filters={"client_id": f"eq.{client_id}", "created_at_shop": f"gte.{since30}"}, limit=1000)
        snap["carts_30d"] = len(carts)
    elif provider:
        carts = await sb_select("abandoned_carts", select="checkout_id", filters={"client_id": f"eq.{client_id}", "created_at_shop": f"gte.{since30}"}, limit=1000)
        snap["carts_30d"] = len(carts)
    try:
        value = await value_overview(client_id)
    except Exception:  # noqa: BLE001 — sem jornada: as ações que dependem dela não aparecem
        value = {"status": "not_built"}
    if value.get("status") == "ok":
        s = value["summary"]
        snap.update({"customers": s["customers"], "repeat_rate": s["repeat_rate"], "median_days_to_second": s["median_days_to_second"]})
        cacs = [m["cac"] for m in value["months"][:-1] if m["cac"]]  # mês corrente ainda aberto fica de fora
        if len(cacs) >= 4:
            snap["cac_last_month"], snap["cac_avg_prev"] = cacs[-1], round(sum(cacs[-6:-1]) / len(cacs[-6:-1]), 2)
        tickets = [(m["revenue_new"] + m["revenue_returning"]) / max(1, m["new"] + m["returning"]) for m in value["months"][-3:]]
        snap["avg_ticket"] = round(sum(tickets) / len(tickets), 2) if tickets else None
    return snap


async def generate(client_id: str) -> Dict[str, Any]:
    from .email_marketing import get_settings
    snap = await snapshot(client_id)
    month = _now().strftime("%Y-%m")
    proposals = detect(snap, month=month)
    existing = {r["dedupe_key"] for r in await sb_select(TABLE, select="dedupe_key", filters={"client_id": f"eq.{client_id}"}, limit=1000)}
    brand = (await get_settings(client_id)).get("from_name") or client_id
    from . import saas
    left = await saas.remaining(client_id, "ai_actions_month")
    created = executed = 0
    for p in proposals:
        if p["dedupe_key"] in existing:
            continue
        if left is not None and created >= left:
            break  # limite de ações da IA do plano no mês
        copy = await _write_copy(client_id, p, brand)
        payload = {**p["payload"], **({"subject": copy.get("subject"), "text": copy.get("text")} if p["kind"] == "campanha_reativacao" else {})}
        row = await sb_insert(TABLE, {"client_id": client_id, "kind": p["kind"], "dedupe_key": p["dedupe_key"], "title": copy["title"][:200],
                                      "rationale": copy["rationale"][:2000], "evidence": p["evidence"], "payload": payload})
        created += 1
        if p["kind"] in AUTO_KINDS and row and row.get("id"):
            try:
                await _apply(client_id, {**row, "status": "proposta"}, user_id=None, auto=True)
                executed += 1
            except Exception as exc:  # noqa: BLE001 — a falha fica gravada na própria ação
                print(f"[ai_actions] auto_failed client_id={client_id} kind={p['kind']} {type(exc).__name__}")
    return {"created": created, "executed": executed, "checked": len(proposals)}


async def list_actions(client_id: str) -> List[Dict[str, Any]]:
    rows = await sb_select(TABLE, select=FIELDS, filters={"client_id": f"eq.{client_id}"}, order="proposed_at.desc", limit=60)
    for r in rows:
        if r["status"] == "executada":
            try:
                r["measurement"] = await measure(client_id, r)
            except Exception:  # noqa: BLE001
                r["measurement"] = None
    return rows


# ---------------------------------------------------------------- decisão e execução

async def _get(client_id: str, action_id: str) -> Dict[str, Any]:
    rows = await sb_select(TABLE, select=FIELDS, filters={"client_id": f"eq.{client_id}", "id": f"eq.{action_id}"}, limit=1)
    if not rows:
        raise ActionError("NOT_FOUND", "Ação não encontrada.", 404)
    return rows[0]


async def execute(client_id: str, action: Dict[str, Any], *, user_id: Optional[str], auto: bool = False) -> Dict[str, Any]:
    from . import cart_recovery, commercial_flows, email_marketing
    kind, payload = action["kind"], action.get("payload") or {}
    if kind == "campanha_reativacao":
        design = {"blocks": [{"type": "logo", "align": "center"}, {"type": "titulo", "text": payload.get("subject") or "Sentimos sua falta", "align": "center"},
                             {"type": "texto", "text": payload.get("text") or "", "align": "center"},
                             {"type": "botao", "label": "Ver novidades", "href": "{{link_loja}}", "align": "center"}]}
        campaign = await email_marketing.save_campaign(client_id, {"name": f"Reativação (IA) {_now().strftime('%d/%m')}",
                                                                   "subject": payload.get("subject") or "Sentimos sua falta, {{primeiro_nome}}",
                                                                   "design": design, "audience": payload.get("audience")}, user_id=user_id)
        when = (_now() + timedelta(hours=REACTIVATION_DELAY_HOURS)).isoformat() if auto else None
        await email_marketing.schedule(client_id, campaign["id"], when)
        return {"campaign_id": campaign["id"], **({"scheduled_at": when} if when else {})}
    if kind == "ligar_fluxo":
        flow = await commercial_flows.save_flow(client_id, payload.get("flow") or "segunda_compra",
                                                {"enabled": True, "channel": "email", "delay_days": payload.get("delay_days") or 30}, user_id=user_id)
        return {"flow": flow["kind"], "delay_days": flow["delay_days"]}
    if kind == "ligar_carrinho":
        from .commerce_context import resolve_commerce_provider
        provider = str((await resolve_commerce_provider(client_id)).get("provider") or "").lower()
        hooks = await cart_recovery.register_webhooks(client_id) if provider == "shopify" else {"inbound": True}
        await cart_recovery.save_settings(client_id, {"enabled": True, "steps": payload.get("steps")}, user_id=user_id)
        return {"webhooks": hooks}
    return {}


async def decide(client_id: str, action_id: str, decision: str, *, user_id: Optional[str]) -> Dict[str, Any]:
    action = await _get(client_id, action_id)
    if action["status"] != "proposta":
        raise ActionError("ALREADY_DECIDED", "Esta ação já foi decidida.", 409)
    if decision == "rejeitar":
        await sb_update(TABLE, filters={"client_id": f"eq.{client_id}", "id": f"eq.{action_id}"},
                        patch={"status": "rejeitada", "decided_by": user_id, "decided_at": _now().isoformat()}, returning="minimal")
        return await _get(client_id, action_id)
    if decision != "aprovar":
        raise ActionError("INVALID_DECISION", "Decisão inválida.")
    return await _apply(client_id, action, user_id=user_id)


async def _apply(client_id: str, action: Dict[str, Any], *, user_id: Optional[str], auto: bool = False) -> Dict[str, Any]:
    action_id = action["id"]
    stamp = _now().isoformat()
    filters = {"client_id": f"eq.{client_id}", "id": f"eq.{action_id}", "status": "eq.proposta"}
    if action["kind"] == "alerta_cac":
        await sb_update(TABLE, filters=filters, patch={"status": "ciente", "decided_by": user_id, "decided_at": stamp}, returning="minimal")
        return await _get(client_id, action_id)
    try:
        result = await execute(client_id, action, user_id=user_id, auto=auto)
        if auto:
            result = {**result, "auto": True}
    except Exception as exc:  # noqa: BLE001
        message = getattr(exc, "message", None) or "A execução falhou. Nada foi enviado."
        await sb_update(TABLE, filters=filters, patch={"status": "falhou", "decided_by": user_id, "decided_at": stamp, "error": str(message)[:500]},
                        returning="minimal")
        return await _get(client_id, action_id)
    await sb_update(TABLE, filters=filters, returning="minimal",
                    patch={"status": "executada", "decided_by": user_id, "decided_at": stamp, "executed_at": _now().isoformat(), "result": result})
    return await _get(client_id, action_id)


async def measure(client_id: str, action: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Resultado depois da execução, com a mesma régua das telas de origem."""
    from . import cart_recovery, commercial_flows, email_marketing
    result = action.get("result") or {}
    if action["kind"] == "campanha_reativacao" and result.get("campaign_id"):
        stats = await email_marketing.campaign_stats(client_id, result["campaign_id"])
        return {"sent": stats["sent"], "open_rate": stats["open_rate"], "click_rate": stats["click_rate"]}
    if action["kind"] == "ligar_fluxo":
        flows = (await commercial_flows.overview(client_id, 30))["flows"]
        r = next((f["result"] for f in flows if f["kind"] == result.get("flow")), None)
        return {"sent": r["sent"], "buyers": r["buyers"], "revenue": r["revenue"]} if r else None
    if action["kind"] == "ligar_carrinho":
        s = (await cart_recovery.overview(client_id, 30))["summary"]
        return {"sent": s["contacted"], "buyers": s["recovered"], "revenue": s["recovered_value"]}
    return None


async def run_all() -> Dict[str, Any]:
    """Cron semanal: gera propostas para as empresas operacionais com loja conectada."""
    from .commerce_context import resolve_commerce_provider
    from .integration_center import _companies
    total = {"clients": 0, "created": 0, "errors": 0}
    for company in await _companies():
        cid = str(company.get("id") or "")
        try:
            if not (await resolve_commerce_provider(cid)).get("provider"):
                continue
            out = await generate(cid)
            total["clients"] += 1
            total["created"] += out["created"]
        except Exception as exc:  # noqa: BLE001
            total["errors"] += 1
            print(f"[ai_actions] client_failed client_id={cid} {type(exc).__name__}")
    return total
