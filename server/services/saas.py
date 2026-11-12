"""Estrutura de SaaS: planos, assinatura por empresa, uso do mês, limites, faturas e implantação (onboarding).

Regras:
- Empresa sem assinatura = sem limite (os clientes atuais da Mugô continuam como estão).
- Limites contam só envio real: e-mail na fila/enviado/entregue (simulado não conta), WhatsApp enviado, ações da IA
  propostas no mês, concorrentes e produtos monitorados ativos, usuários com acesso.
- Assinatura cancelada = envios bloqueados (limite 0). Atrasada = aviso; continua funcionando.
- Cobrança "manual": o job mensal gera a fatura no dia de cobrança; a Mugô marca como paga. Um provedor (Asaas ou
  Stripe) entra depois usando as mesmas tabelas (provider_*).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from .ig_supabase import _assert_env, _base_url, _headers, _request, sb_select, sb_update, sb_upsert

PLANS = "saas_plans"
SUBS = "client_subscriptions"
INVOICES = "billing_invoices"
LIMIT_KEYS = ("users", "email_sends_month", "whatsapp_month", "ai_actions_month", "competitors", "monitored_products")
LIMIT_LABEL = {"users": "Usuários", "email_sends_month": "E-mails no mês", "whatsapp_month": "WhatsApp no mês",
               "ai_actions_month": "Ações da IA no mês", "competitors": "Concorrentes", "monitored_products": "Produtos monitorados"}
STATUSES = ("teste", "ativa", "atrasada", "cancelada", "cortesia")
OVERDUE_GRACE_DAYS = 7


class QuotaError(Exception):
    def __init__(self, code: str, message: str, status: int = 402):
        super().__init__(code)
        self.code = code
        self.message = message
        self.status = status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def month_start(now: Optional[datetime] = None) -> datetime:
    now = now or _now()
    return datetime(now.year, now.month, 1, tzinfo=timezone.utc)


async def _count(table: str, filters: Dict[str, str]) -> int:
    """Conta linhas sem trazê-las (Content-Range do PostgREST)."""
    _assert_env()
    params = {"select": "*", "limit": "1", **filters}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{_base_url()}/{table}", params=params, headers={**_headers(), "Prefer": "count=exact", "Range-Unit": "items"})
    resp.raise_for_status()
    total = (resp.headers.get("content-range") or "*/0").split("/")[-1]
    return int(total) if total.isdigit() else 0


# ---------------------------------------------------------------- planos e assinatura

async def list_plans(include_inactive: bool = False) -> List[Dict[str, Any]]:
    filters = {} if include_inactive else {"active": "is.true"}
    return await sb_select(PLANS, select="id,name,price_month_cents,limits,features,active,sort", filters=filters, order="sort.asc", limit=50)


def clean_plan(body: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if "name" in body:
        name = str(body.get("name") or "").strip()[:60]
        if len(name) < 2:
            raise QuotaError("INVALID_PLAN", "Dê um nome ao plano.", 400)
        out["name"] = name
    if "price_month_cents" in body:
        try:
            out["price_month_cents"] = max(0, int(body["price_month_cents"]))
        except (TypeError, ValueError):
            raise QuotaError("INVALID_PLAN", "Preço inválido.", 400) from None
    if "limits" in body:
        limits = {}
        for key in LIMIT_KEYS:
            value = (body.get("limits") or {}).get(key)
            if value is None or value == "":
                continue  # sem número = sem limite naquele item
            try:
                limits[key] = max(0, int(value))
            except (TypeError, ValueError):
                raise QuotaError("INVALID_PLAN", f"Limite inválido em {LIMIT_LABEL[key]}.", 400) from None
        out["limits"] = limits
    if "features" in body:
        out["features"] = [str(f).strip()[:120] for f in (body.get("features") or []) if str(f).strip()][:12]
    if "active" in body:
        out["active"] = bool(body["active"])
    return out


async def save_plan(plan_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    rows = await sb_select(PLANS, select="id", filters={"id": f"eq.{plan_id}"}, limit=1)
    if not rows:
        raise QuotaError("NOT_FOUND", "Plano não encontrado.", 404)
    await sb_update(PLANS, filters={"id": f"eq.{plan_id}"}, patch=clean_plan(body), returning="minimal")
    return next(p for p in await list_plans(True) if p["id"] == plan_id)


async def get_subscription(client_id: str) -> Optional[Dict[str, Any]]:
    rows = await sb_select(SUBS, select="client_id,plan_id,status,trial_ends_at,current_period_end,billing_day,billing_provider,notes,updated_at",
                           filters={"client_id": f"eq.{client_id}"}, limit=1)
    if not rows:
        return None
    sub = rows[0]
    plans = {p["id"]: p for p in await list_plans(True)}
    sub["plan"] = plans.get(sub["plan_id"])
    return sub


async def set_subscription(client_id: str, body: Dict[str, Any], *, user_id: Optional[str]) -> Dict[str, Any]:
    plans = {p["id"]: p for p in await list_plans(True)}
    plan_id = str(body.get("plan_id") or "")
    if plan_id not in plans:
        raise QuotaError("INVALID_PLAN", "Escolha um plano.", 400)
    status = body.get("status") if body.get("status") in STATUSES else "teste"
    row: Dict[str, Any] = {"client_id": client_id, "plan_id": plan_id, "status": status, "updated_by": user_id, "updated_at": _now().isoformat(),
                           "billing_day": max(1, min(int(body.get("billing_day") or 5), 28)), "notes": str(body.get("notes") or "")[:1000] or None}
    if status == "teste":
        days = max(1, min(int(body.get("trial_days") or 14), 60))
        row["trial_ends_at"] = (_now() + timedelta(days=days)).isoformat()
    await sb_upsert(SUBS, [row], on_conflict="client_id")
    return await get_subscription(client_id)  # type: ignore[return-value]


async def remove_subscription(client_id: str) -> None:
    from .ig_supabase import sb_delete
    await sb_delete(SUBS, filters={"client_id": f"eq.{client_id}"}, returning="minimal")


# ---------------------------------------------------------------- uso e limites

async def usage(client_id: str, now: Optional[datetime] = None) -> Dict[str, int]:
    start = month_start(now).isoformat()
    cid = f"eq.{client_id}"

    async def safe(table: str, filters: Dict[str, str]) -> int:
        try:
            return await _count(table, filters)
        except Exception:  # noqa: BLE001 — tabela de uma etapa ainda não aplicada conta como zero
            return 0

    email = await safe("email_sends", {"client_id": cid, "created_at": f"gte.{start}", "kind": "in.(campanha,carrinho,fluxo)",
                                       "status": "in.(na_fila,enviado,entregue,bounce,spam)"})
    wa = await safe("flow_sends", {"client_id": cid, "at": f"gte.{start}", "channel": "eq.whatsapp", "status": "eq.enviado"}) + \
        await safe("cart_recovery_touches", {"client_id": cid, "at": f"gte.{start}", "channel": "eq.whatsapp", "status": "eq.enviado"})
    return {
        "email_sends_month": email, "whatsapp_month": wa,
        "ai_actions_month": await safe("ai_actions", {"client_id": cid, "proposed_at": f"gte.{start}"}),
        "users": await safe("client_memberships", {"client_id": cid}),
        "competitors": await safe("benchmark_competitors", {"client_id": cid, "active": "is.true"}),
        "monitored_products": await safe("benchmark_products", {"client_id": cid, "active": "is.true"}),
    }


def remaining_from(sub: Optional[Dict[str, Any]], used: Dict[str, int], key: str) -> Optional[int]:
    """Função pura: None = sem limite; 0 = acabou (ou assinatura cancelada)."""
    if not sub:
        return None
    if sub.get("status") == "cancelada":
        return 0
    limit = ((sub.get("plan") or {}).get("limits") or {}).get(key)
    if limit is None:
        return None
    return max(0, int(limit) - int(used.get(key) or 0))


async def remaining(client_id: str, key: str) -> Optional[int]:
    try:
        sub = await get_subscription(client_id)
        if not sub:
            return None
        return remaining_from(sub, await usage(client_id), key)
    except Exception:  # noqa: BLE001 — limite é regra comercial: sem como ler (ex.: 000112 não aplicada), não trava o envio
        return None


async def require(client_id: str, key: str, needed: int = 1) -> None:
    left = await remaining(client_id, key)
    if left is not None and left < needed:
        label = LIMIT_LABEL[key].lower()
        raise QuotaError("PLAN_LIMIT", f"O plano não comporta isso: faltam {needed - left} em {label} (restam {left}). "
                                       "Fale com a Mugô para mudar de plano.")


# ---------------------------------------------------------------- implantação

async def onboarding(client_id: str) -> List[Dict[str, Any]]:
    from .commerce_context import resolve_commerce_provider
    from .data_health import client_data_health
    steps: List[Dict[str, Any]] = []
    try:
        today = date.today()
        sources = {s["provider"]: s for s in (await client_data_health(client_id, (today - timedelta(days=7)).isoformat(), today.isoformat()))["sources"]}
    except Exception as exc:  # noqa: BLE001
        print(f"[saas] onboarding_health_failed client_id={client_id} {type(exc).__name__}")
        sources = {}
    provider = (await resolve_commerce_provider(client_id)).get("provider")
    connected = lambda p: bool((sources.get(p) or {}).get("connected"))  # noqa: E731

    async def exists(table: str, filters: Dict[str, str]) -> bool:
        try:
            return bool(await sb_select(table, select="client_id", filters={"client_id": f"eq.{client_id}", **filters}, limit=1))
        except httpx.HTTPError:
            return False

    sender = await exists("email_settings", {"from_email": "not.is.null"})
    # Loja: conectada pelo provedor resolvido OU pela fonte de saúde (FBITS/Shopify).
    provider = provider or ("fbits" if connected("fbits") else "shopify" if connected("shopify") else None)
    steps += [
        {"key": "loja", "label": "Conectar a loja (Shopify ou FBITS)", "done": bool(provider), "route": "integrations"},
        {"key": "meta", "label": "Conectar Meta (anúncios e Instagram)", "done": connected("meta_ads") or connected("instagram"), "route": "integrations"},
        {"key": "ga4", "label": "Conectar o Google Analytics 4", "done": connected("ga4"), "route": "integrations"},
        {"key": "google_ads", "label": "Conectar o Google Ads", "done": connected("google_ads"), "route": "integrations"},
        {"key": "remetente", "label": "Configurar o remetente de e-mail", "done": sender, "route": "email_marketing"},
        {"key": "whatsapp", "label": "Ligar o número de WhatsApp da marca", "done": await exists("whatsapp_numbers", {"status": "eq.active"}), "route": "whatsapp"},
        {"key": "jornada", "label": "Montar a jornada do cliente", "done": await exists("customer_journey_runs", {}), "route": "customers"},
        {"key": "fluxo", "label": "Ligar o primeiro fluxo automático", "done": await exists("commercial_flows", {"enabled": "is.true"}), "route": "email_marketing"},
        {"key": "concorrente", "label": "Cadastrar um concorrente no benchmarking", "done": await exists("benchmark_competitors", {"active": "is.true"}), "route": "benchmark"},
    ]
    return steps


async def overview(client_id: str) -> Dict[str, Any]:
    sub = await get_subscription(client_id)
    used = await usage(client_id)
    limits = ((sub or {}).get("plan") or {}).get("limits") or {}
    meters = [{"key": k, "label": LIMIT_LABEL[k], "used": used.get(k, 0), "limit": limits.get(k) if sub else None,
               "remaining": remaining_from(sub, used, k)} for k in LIMIT_KEYS]
    invoices = await sb_select(INVOICES, select="id,period,plan_id,amount_cents,status,due_date,paid_at,payment_url",
                               filters={"client_id": f"eq.{client_id}"}, order="period.desc", limit=24) if sub else []
    return {"subscription": sub, "meters": meters, "invoices": invoices, "onboarding": await onboarding(client_id), "plans": await list_plans()}


async def admin_overview() -> Dict[str, Any]:
    from .integration_center import _companies
    companies = await _companies()
    subs = {s["client_id"]: s for s in await sb_select(SUBS, select="client_id,plan_id,status,trial_ends_at,billing_day", limit=2000)}
    open_invoices = await sb_select(INVOICES, select="client_id,status,amount_cents,due_date", filters={"status": "in.(aberta,vencida)"}, limit=2000)
    plans = {p["id"]: p for p in await list_plans(True)}
    rows = []
    for c in companies:
        sub = subs.get(c["id"])
        owed = [i for i in open_invoices if i["client_id"] == c["id"]]
        rows.append({"client_id": c["id"], "name": c.get("name") or c["id"], "subscription": sub,
                     "plan_name": (plans.get(sub["plan_id"]) or {}).get("name") if sub else None,
                     "mrr_cents": (plans.get(sub["plan_id"]) or {}).get("price_month_cents", 0) if sub and sub["status"] in ("ativa", "atrasada") else 0,
                     "open_cents": sum(i["amount_cents"] for i in owed), "overdue": any(i["status"] == "vencida" for i in owed)})
    return {"companies": rows, "plans": list(plans.values()), "mrr_cents": sum(r["mrr_cents"] for r in rows)}


# ---------------------------------------------------------------- faturas

def invoice_due(sub: Dict[str, Any], today: date) -> Optional[Dict[str, Any]]:
    """Função pura: a fatura do mês que deve existir hoje (ou None)."""
    if sub.get("status") not in ("ativa", "atrasada"):
        return None
    day = int(sub.get("billing_day") or 5)
    if today.day < day:
        return None
    return {"period": f"{today.year:04d}-{today.month:02d}", "due_date": date(today.year, today.month, day).isoformat()}


async def mark_paid(client_id: str, invoice_id: str) -> Dict[str, Any]:
    rows = await sb_update(INVOICES, filters={"client_id": f"eq.{client_id}", "id": f"eq.{invoice_id}"},
                           patch={"status": "paga", "paid_at": _now().isoformat()})
    if not rows:
        raise QuotaError("NOT_FOUND", "Fatura não encontrada.", 404)
    still = await sb_select(INVOICES, select="id", filters={"client_id": f"eq.{client_id}", "status": "eq.vencida"}, limit=1)
    if not still:
        await sb_update(SUBS, filters={"client_id": f"eq.{client_id}", "status": "eq.atrasada"}, patch={"status": "ativa"}, returning="minimal")
    return rows[0]


async def run_billing(today: Optional[date] = None) -> Dict[str, Any]:
    """Cron diário: fim de teste vira ativa, gera fatura do mês, marca vencida e atrasa assinatura após a carência."""
    today = today or _now().date()
    subs = await sb_select(SUBS, select="client_id,plan_id,status,trial_ends_at,billing_day", limit=2000)
    plans = {p["id"]: p for p in await list_plans(True)}
    total = {"activated": 0, "invoices": 0, "overdue": 0}
    for sub in subs:
        cid = sub["client_id"]
        trial_end = sub.get("trial_ends_at")
        if sub["status"] == "teste" and trial_end and datetime.fromisoformat(str(trial_end).replace("Z", "+00:00")).date() <= today:
            await sb_update(SUBS, filters={"client_id": f"eq.{cid}"}, patch={"status": "ativa"}, returning="minimal")
            sub["status"] = "ativa"
            total["activated"] += 1
        due = invoice_due(sub, today)
        if due:
            amount = (plans.get(sub["plan_id"]) or {}).get("price_month_cents", 0)
            # fatura do mês já existente (paga ou não) nunca é sobrescrita
            await _request("POST", f"/{INVOICES}", params={"on_conflict": "client_id,period"},
                           json=[{"client_id": cid, "plan_id": sub["plan_id"], "amount_cents": amount, **due}],
                           headers={"Prefer": "resolution=ignore-duplicates,return=minimal"})
            total["invoices"] += 1
    overdue = await sb_select(INVOICES, select="id,client_id,due_date", filters={"status": "eq.aberta", "due_date": f"lt.{today.isoformat()}"}, limit=2000)
    for inv in overdue:
        await sb_update(INVOICES, filters={"id": f"eq.{inv['id']}"}, patch={"status": "vencida"}, returning="minimal")
        total["overdue"] += 1
    late = await sb_select(INVOICES, select="client_id", filters={"status": "eq.vencida",
                                                                  "due_date": f"lt.{(today - timedelta(days=OVERDUE_GRACE_DAYS)).isoformat()}"}, limit=2000)
    for cid in {r["client_id"] for r in late}:
        await sb_update(SUBS, filters={"client_id": f"eq.{cid}", "status": "eq.ativa"}, patch={"status": "atrasada"}, returning="minimal")
    return total
