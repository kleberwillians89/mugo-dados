"""Jornada do cliente: identidade unificada + linha do tempo de eventos confirmados.

Junta numa pessoa só tudo o que a empresa já sabe dela, sem inventar ligação:
- pedidos da loja (Shopify ou FBITS) e vendas que o CRM da marca registra (Ruah);
- conversas do WhatsApp (número nativo do MUGOVERSO ou CRM da marca), com o anúncio que abriu a conversa.

Identidade (união de identificadores, nunca por nome): id do cliente na loja, e-mail (hash) e a ``phone_key`` do
telefone (a mesma chave que o WhatsApp e o CRM usam; o telefone em si nunca é gravado). Dois registros viram a
mesma pessoa só quando compartilham um desses identificadores.

Evidência de cada evento:
- ``observado``: o dado veio da fonte (UTM gravada no pedido, anúncio informado pela Meta na conversa);
- ``regra``: ligação por regra declarada na tela ("compra até 7 dias depois da conversa, mesmo telefone"), a
  mesma do painel de WhatsApp. Nada é distribuído por estimativa.

``rebuild`` monta e grava tudo da empresa (idempotente, apaga o que sumiu da fonte); a tela lê o que foi gravado.
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .ig_supabase import sb_delete, sb_select, sb_upsert

IDENTITIES = "customer_identities"
EVENTS = "customer_events"
RUNS = "customer_journey_runs"
LOOKBACK_DAYS = 400
LINK_WINDOW = timedelta(days=7)
PRIORITY = {"external_id": 0, "email_hash": 1, "phone_key": 2}
CHUNK = 500


def _text(value: Any) -> str:
    return str(value or "").strip()


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _dt(value: Any) -> Optional[datetime]:
    raw = _text(value)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def email_hash(value: Any) -> Optional[str]:
    from .customers import _normalized_email
    email = _normalized_email(value)
    return hashlib.sha256(f"mugo-mail:{email}".encode()).hexdigest()[:32] if email else None


def person_id(client_id: str, kind: str, value: str) -> str:
    return hashlib.sha256(f"{client_id}|person|{kind}|{value}".encode()).hexdigest()[:32]


class _Union:
    def __init__(self) -> None:
        self.parent: Dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def join(self, items: Iterable[str]) -> None:
        items = list(items)
        for item in items:
            self.find(item)  # um identificador sozinho também vira pessoa
        for other in items[1:]:
            a, b = self.find(items[0]), self.find(other)
            if a != b:
                self.parent[max(a, b)] = min(a, b)


def order_identifiers(order: Dict[str, Any]) -> List[str]:
    ids = []
    if _text(order.get("external_id")):
        ids.append(f"external_id:{_text(order['external_id'])}")
    mail = email_hash(order.get("email"))
    if mail:
        ids.append(f"email_hash:{mail}")
    ids.extend(f"phone_key:{k}" for k in order.get("phone_keys") or [] if k)
    return list(dict.fromkeys(ids))


def build(client_id: str, orders: List[Dict[str, Any]], leads: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Função pura: pedidos + conversas → identidades, eventos e números do que entrou.

    Pedido: {ref, provider, label, at, value, counts, cancelled, external_id, email, phone_keys, origin, customer_page}.
    Conversa: {phone_key, first_seen_at, origin}.
    """
    from .whatsapp_insights import origin_bucket, origin_label
    union = _Union()
    usable_orders = []
    for order in orders:
        ids = order_identifiers(order)
        if not ids or not _dt(order.get("at")):
            continue
        union.join(ids)
        usable_orders.append((order, ids))
    usable_leads = [(lead, f"phone_key:{lead['phone_key']}") for lead in leads if _text(lead.get("phone_key")) and _dt(lead.get("first_seen_at"))]
    for _, key in usable_leads:
        union.find(key)

    members: Dict[str, List[str]] = defaultdict(list)
    for key in list(union.parent):
        members[union.find(key)].append(key)
    person_of: Dict[str, str] = {}
    for root, keys in members.items():
        kind, value = min((k.split(":", 1) for k in keys), key=lambda kv: (PRIORITY[kv[0]], kv[1]))
        pid = person_id(client_id, kind, value)
        for k in keys:
            person_of[k] = pid

    identities: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for key, pid in person_of.items():
        kind, value = key.split(":", 1)
        identities[(kind, value)] = {"client_id": client_id, "kind": kind, "value": value, "person_id": pid}

    events: List[Dict[str, Any]] = []
    conversations: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for lead, key in usable_leads:
        pid = person_of[key]
        origin = lead.get("origin") or {}
        event = {"client_id": client_id, "event_key": f"wa:{lead['phone_key']}:{_dt(lead['first_seen_at']).isoformat()[:19]}",
                 "person_id": pid, "kind": "conversa_whatsapp", "at": _dt(lead["first_seen_at"]).isoformat(), "source": "whatsapp",
                 "channel": origin_bucket(origin), "campaign": _text(origin.get("ad_headline"))[:160] or None,
                 "ad_id": _text(origin.get("ad_id")) or None, "value": None, "evidence": "observado",
                 "detail": {"origem": origin_label(origin), "entry_code": origin.get("entry_code")}}
        events.append(event)
        conversations[pid].append(event)

    purchases_by_person: Dict[str, int] = defaultdict(int)
    stats = defaultdict(int)
    for order, ids in sorted(usable_orders, key=lambda pair: _dt(pair[0]["at"])):
        pid = person_of[ids[0]]
        at = _dt(order["at"])
        if order.get("customer_page"):
            identities[("customer_page", order["customer_page"])] = {"client_id": client_id, "kind": "customer_page",
                                                                     "value": order["customer_page"], "person_id": pid}
        origin = order.get("origin") or {}
        channel = _text(origin.get("origin_channel")) or None
        if order.get("cancelled"):
            kind = "pedido_cancelado"
        elif order.get("counts"):
            purchases_by_person[pid] += 1
            kind = "recompra" if purchases_by_person[pid] > 1 else "pedido"
        else:
            kind = "pedido"
        detail: Dict[str, Any] = {"pedido": order.get("label") or order["ref"], "conta_como_venda": bool(order.get("counts")),
                                  "utm_source": origin.get("utm_source"), "utm_medium": origin.get("utm_medium"),
                                  "origem_registrada_por": origin.get("attribution_source") or None}
        evidence = "observado"
        before = [c for c in conversations.get(pid, []) if _dt(c["at"]) <= at <= _dt(c["at"]) + LINK_WINDOW]
        if before and order.get("counts"):
            last = max(before, key=lambda c: c["at"])
            detail["depois_da_conversa"] = {"em": last["at"], "origem": last["detail"].get("origem")}
            if not channel or channel == "unknown":
                channel, evidence = "whatsapp", "regra"
            stats["purchases_after_whatsapp"] += 1
        if order.get("counts") and channel and channel != "unknown":
            stats["purchases_with_origin"] += 1
        if order.get("counts"):
            stats["purchases"] += 1
        events.append({"client_id": client_id, "event_key": f"order:{order.get('provider')}:{order['ref']}", "person_id": pid,
                       "kind": kind, "at": at.isoformat(), "source": order.get("provider") or "loja", "channel": channel,
                       "campaign": _text(origin.get("utm_campaign"))[:160] or None, "ad_id": None,
                       "value": round(_num(order.get("value")), 2), "evidence": evidence, "detail": detail})

    persons = set(person_of.values())
    with_purchase = set(purchases_by_person)
    with_whatsapp = set(conversations)
    return {"identities": list(identities.values()), "events": events,
            "stats": {"persons": len(persons), "persons_with_purchase": len(with_purchase), "persons_with_whatsapp": len(with_whatsapp),
                      "whatsapp_and_purchase": len(with_purchase & with_whatsapp), "repeat_buyers": sum(1 for n in purchases_by_person.values() if n > 1),
                      "orders_scanned": len(orders), "orders_without_identity": len(orders) - len(usable_orders),
                      "conversations": len(usable_leads), **stats}}


# ---------------------------------------------------------------- leitura das fontes

async def _load_orders(client_id: str, since: datetime) -> Tuple[str, List[Dict[str, Any]]]:
    from .commerce_context import FBITS, SHOPIFY, resolve_commerce_provider
    from .customers import _identity, customer_key
    from .sales_by_origin import ORIGIN_SELECT, _paged
    from .whatsapp_insights import _PHONE_FIELDS, order_phone_keys, phone_key

    provider = _text((await resolve_commerce_provider(client_id)).get("provider")).lower()
    out: List[Dict[str, Any]] = []
    if provider == SHOPIFY:
        from .shopify_reporting import _is_cancelled_order, _is_recognized_order
        rows, _ = await _paged("shopify_orders", select=("shopify_order_id,name,email,customer_id,financial_status,total_price,cancelled_at,"
                                                         f"cancel_reason,created_at_shopify,{ORIGIN_SELECT}," + ",".join(_PHONE_FIELDS)),
                               filters={"client_id": f"eq.{client_id}", "created_at_shopify": f"gte.{since.isoformat()}"},
                               order="created_at_shopify.asc,shopify_order_id.asc")
        profiles = {_text(p.get("shopify_customer_id")): p for p in await sb_select(
            "shopify_customers", select="shopify_customer_id,email,phone", filters={"client_id": f"eq.{client_id}"}, limit=20000)}
        for r in rows:
            profile = profiles.get(_text(r.get("customer_id"))) or {}
            keys = order_phone_keys(r)
            extra = phone_key(profile.get("phone"))
            if extra and extra not in keys:
                keys.append(extra)
            kind, value = _identity(external_id=r.get("customer_id"), email=r.get("email") or profile.get("email"), phone=profile.get("phone"))
            out.append({"ref": _text(r.get("shopify_order_id")), "provider": "shopify", "label": _text(r.get("name")) or None,
                        "at": r.get("created_at_shopify"), "value": r.get("total_price"), "counts": _is_recognized_order(r),
                        "cancelled": _is_cancelled_order(r), "external_id": r.get("customer_id"), "email": r.get("email") or profile.get("email"),
                        "phone_keys": keys, "origin": {k: r.get(k) for k in ORIGIN_SELECT.split(",")},
                        "customer_page": customer_key(client_id, kind, value) if kind else None})
    elif provider == FBITS:
        from .fbits_reporting import _counts_as_revenue, _tenant_revenue_context
        _, revenue_ids, _ = await _tenant_revenue_context(client_id)
        rows, _ = await _paged("fbits_orders", select=f"order_id,order_code,customer_id,customer_email,status_id,total_value,is_valid,order_date,{ORIGIN_SELECT}",
                               filters={"client_id": f"eq.{client_id}", "order_date": f"gte.{since.isoformat()}"}, order="order_date.asc,order_id.asc")
        people = {_text(p.get("fbits_customer_id")): p for p in await sb_select(
            "fbits_customers", select="fbits_customer_id,email,phone", filters={"client_id": f"eq.{client_id}"}, limit=20000)}
        for r in rows:
            person = people.get(_text(r.get("customer_id"))) or {}
            key = phone_key(person.get("phone"))
            kind, value = _identity(external_id=r.get("customer_id"), email=person.get("email") or r.get("customer_email"))
            out.append({"ref": _text(r.get("order_id")), "provider": "fbits", "label": _text(r.get("order_code")) or None,
                        "at": r.get("order_date"), "value": r.get("total_value"), "counts": _counts_as_revenue(r, revenue_ids),
                        "cancelled": r.get("is_valid") is False, "external_id": r.get("customer_id"),
                        "email": person.get("email") or r.get("customer_email"), "phone_keys": [key] if key else [],
                        "origin": {k: r.get(k) for k in ORIGIN_SELECT.split(",")},
                        "customer_page": customer_key(client_id, kind, value) if kind else None})
    return provider, out


async def _load_crm_sales(client_id: str, since: datetime, until: datetime) -> List[Dict[str, Any]]:
    from .whatsapp_sources import brand_sales
    sales = await brand_sales(client_id, since.date().isoformat(), until.date().isoformat())
    return [{"ref": s.get("_id") or f"crm:{i}", "provider": "crm", "label": s.get("name"), "at": s.get("created_at_shopify"),
             "value": s.get("value"), "counts": True, "cancelled": False, "phone_keys": s.get("phone_keys") or [],
             "origin": {}, "customer_page": None} for i, s in enumerate(sales)]


async def _load_leads(client_id: str, since: datetime, until: datetime) -> List[Dict[str, Any]]:
    from .whatsapp_sources import brand_leads
    result = await brand_leads(client_id, since.date().isoformat(), until.date().isoformat())
    return [lead for lead in (result or {}).get("leads") or [] if isinstance(lead, dict)]


# ---------------------------------------------------------------- gravação

async def rebuild(client_id: str) -> Dict[str, Any]:
    """Monta a jornada da empresa a partir das fontes e grava (idempotente)."""
    run_at = datetime.now(timezone.utc)
    since = run_at - timedelta(days=LOOKBACK_DAYS)
    provider, orders = await _load_orders(client_id, since)
    notes: List[str] = []
    try:
        orders += await _load_crm_sales(client_id, since, run_at)
    except Exception as exc:  # noqa: BLE001
        notes.append("Vendas do CRM da marca indisponíveis agora.")
        print(f"[customer_journey] crm_sales_failed client_id={client_id} {type(exc).__name__}")
    try:
        leads = await _load_leads(client_id, since, run_at)
    except Exception as exc:  # noqa: BLE001 — sem WhatsApp, a jornada segue só com pedidos
        leads = []
        notes.append("Conversas do WhatsApp indisponíveis agora.")
        print(f"[customer_journey] leads_failed client_id={client_id} {type(exc).__name__}")
    result = build(client_id, orders, leads)
    stamp = run_at.isoformat()
    for table, rows, conflict in ((IDENTITIES, result["identities"], "client_id,kind,value"), (EVENTS, result["events"], "client_id,event_key")):
        for offset in range(0, len(rows), CHUNK):
            await sb_upsert(table, [{**r, "built_at": stamp} for r in rows[offset:offset + CHUNK]], on_conflict=conflict)
        # O que sumiu da fonte (pedido apagado, pessoa que mudou de grupo) sai junto.
        await sb_delete(table, filters={"client_id": f"eq.{client_id}", "built_at": f"lt.{stamp}"}, returning="minimal")
    stats = {**result["stats"], "provider": provider or None, "notes": notes}
    await sb_upsert(RUNS, [{"client_id": client_id, "built_at": stamp, "stats": stats}], on_conflict="client_id")
    return {"built_at": stamp, "stats": stats}


# ---------------------------------------------------------------- leitura

def summarize_person(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    events = sorted(events, key=lambda e: str(e.get("at")))
    purchases = [e for e in events if e["kind"] in ("pedido", "recompra") and (e.get("detail") or {}).get("conta_como_venda", True)]
    first = events[0] if events else None
    first_purchase = purchases[0] if purchases else None
    days = None
    if first and first_purchase:
        days = max(0, (_dt(first_purchase["at"]) - _dt(first["at"])).days)
    return {"first_touch": first, "first_purchase": first_purchase, "purchases": len(purchases),
            "revenue": round(sum(_num(e.get("value")) for e in purchases), 2), "days_to_first_purchase": days,
            "channels": list(dict.fromkeys(e["channel"] for e in events if e.get("channel") and e["channel"] != "unknown")),
            "last_event_at": events[-1]["at"] if events else None}


async def journey_for_customer(client_id: str, customer_id: str) -> Dict[str, Any]:
    runs = await sb_select(RUNS, select="built_at,stats", filters={"client_id": f"eq.{client_id}"}, limit=1)
    if not runs:
        return {"status": "not_built", "events": [], "summary": None, "built_at": None}
    links = await sb_select(IDENTITIES, select="person_id", filters={"client_id": f"eq.{client_id}", "kind": "eq.customer_page",
                                                                     "value": f"eq.{_text(customer_id)}"}, limit=1)
    if not links:
        return {"status": "not_found", "events": [], "summary": None, "built_at": runs[0]["built_at"]}
    pid = links[0]["person_id"]
    events = await sb_select(EVENTS, select="event_key,kind,at,source,channel,campaign,ad_id,value,evidence,detail",
                             filters={"client_id": f"eq.{client_id}", "person_id": f"eq.{pid}"}, order="at.asc", limit=500)
    kinds = await sb_select(IDENTITIES, select="kind", filters={"client_id": f"eq.{client_id}", "person_id": f"eq.{pid}"}, limit=50)
    linked = sorted({k["kind"] for k in kinds if k["kind"] != "customer_page"})
    return {"status": "ok", "events": events, "summary": summarize_person(events), "identities": linked, "built_at": runs[0]["built_at"]}


async def journey_status(client_id: str) -> Dict[str, Any]:
    runs = await sb_select(RUNS, select="built_at,stats", filters={"client_id": f"eq.{client_id}"}, limit=1)
    return {"built_at": runs[0]["built_at"], "stats": runs[0]["stats"]} if runs else {"built_at": None, "stats": None}


async def run_all() -> Dict[str, Any]:
    """Cron diário: monta a jornada das empresas operacionais com loja conectada. Uma falha não para as outras."""
    from .commerce_context import resolve_commerce_provider
    from .integration_center import _companies
    total: Dict[str, Any] = {"clients": 0, "skipped": 0, "errors": 0, "persons": 0}
    for company in await _companies():
        cid = _text(company.get("id"))
        try:
            if not _text((await resolve_commerce_provider(cid)).get("provider")):
                total["skipped"] += 1
                continue
            result = await rebuild(cid)
            total["clients"] += 1
            total["persons"] += int(result["stats"].get("persons") or 0)
        except Exception as exc:  # noqa: BLE001
            total["errors"] += 1
            print(f"[customer_journey] client_failed client_id={cid} {type(exc).__name__}")
    return total
