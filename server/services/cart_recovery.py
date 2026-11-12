"""Recuperação de carrinho abandonado: checkout da Shopify → sequência por e-mail e WhatsApp → compra medida.

Fluxo:
1. A Shopify avisa ``checkouts/create`` / ``checkouts/update``. Antes de gravar o evento, ``minimize`` tira o que é
   pessoal: e-mail, telefone e nome vão criptografados (``contact_enc``), mais o hash e a ``phone_key``.
2. ``process_due`` (cron a cada 5 min) envia o próximo passo da sequência quando vence o prazo, sempre conferindo
   antes se a pessoa já comprou (pelo checkout e pelo e-mail na loja) — quem comprou não recebe nada.
3. Pedido novo com o mesmo checkout (``orders/create``): se houve contato até N dias antes (padrão 7), o carrinho é
   "recuperado" com o valor do pedido; se não houve contato, "comprou sem contato". Cada checkout conta uma vez só.
4. Recuperou, comprou, expirou (7 dias sem compra depois do último passo) → o contato criptografado é apagado.

Consentimento:
- e-mail: "todos que deixaram o e-mail" (lembrete de carrinho, com descadastro em 1 clique) ou só quem aceitou
  marketing — escolha da marca;
- WhatsApp: só quem aceitou marketing no checkout, ou também quem já conversou com a marca no WhatsApp.
- ``WHATSAPP_MARKETING_SEND_ENABLED`` diferente de ``true`` = WhatsApp simulado (registra o passo, não envia).
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from . import email_builder, email_marketing, email_resend
from .ig_supabase import sb_select, sb_update, sb_upsert

SETTINGS = "cart_recovery_settings"
CARTS = "abandoned_carts"
TOUCHES = "cart_recovery_touches"
CHECKOUT_TOPICS = ("checkouts/create", "checkouts/update")
EXPIRE_DAYS = 7
MAX_STEPS = 5
DUE_LIMIT = 200
WA_VARIABLES = ("nome", "produto", "valor", "link")
SETTING_FIELDS = ("enabled", "steps", "email_subject", "email_design", "email_custom_html", "email_consent", "whatsapp_number_id", "whatsapp_template",
                  "whatsapp_language", "whatsapp_variables", "whatsapp_consent", "attribution_days", "webhooks_registered_at")
DEFAULTS: Dict[str, Any] = {
    "enabled": False, "steps": [{"channel": "email", "delay_minutes": 60}, {"channel": "whatsapp", "delay_minutes": 1440}],
    "email_subject": "Você esqueceu alguns itens no carrinho", "email_design": None, "email_custom_html": None, "email_consent": "todos",
    "whatsapp_number_id": None, "whatsapp_template": None, "whatsapp_language": "pt_BR", "whatsapp_variables": ["nome", "link"],
    "whatsapp_consent": "consentimento", "attribution_days": 7, "webhooks_registered_at": None,
}


class CartError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(code)
        self.code = code
        self.message = message
        self.status = status


def _text(value: Any, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dt(value: Any) -> Optional[datetime]:
    raw = _text(value, 40)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def whatsapp_to(phone: Any) -> Optional[str]:
    raw = _text(phone, 40)
    digits = re.sub(r"\D", "", raw)
    if not raw.startswith("+") and len(digits) in (10, 11):
        digits = f"55{digits}"
    return digits if 12 <= len(digits) <= 15 else None


# ---------------------------------------------------------------- webhook → carrinho

def minimize(payload: Dict[str, Any]) -> Dict[str, Any]:
    """O que fica gravado do checkout: sem e-mail/telefone/nome em claro."""
    from .crypto import encrypt_secret
    from .whatsapp_insights import phone_key
    customer = payload.get("customer") if isinstance(payload.get("customer"), dict) else {}
    shipping = payload.get("shipping_address") if isinstance(payload.get("shipping_address"), dict) else {}
    billing = payload.get("billing_address") if isinstance(payload.get("billing_address"), dict) else {}
    email = email_marketing.valid_email(payload.get("email") or customer.get("email"))
    phone = _text(payload.get("phone") or shipping.get("phone") or billing.get("phone") or customer.get("phone"), 40)
    first = _text(customer.get("first_name") or shipping.get("first_name") or billing.get("first_name"), 80)
    contact = {k: v for k, v in (("email", email), ("phone", phone), ("first_name", first)) if v}
    items = []
    for line in (payload.get("line_items") or [])[:20]:
        if isinstance(line, dict):
            items.append({"title": _text(line.get("title"), 160), "variant": _text(line.get("variant_title"), 120) or None,
                          "quantity": int(_num(line.get("quantity")) or 1), "price": round(_num(line.get("price")), 2),
                          "product_id": _text(line.get("product_id"), 40) or None})
    return {
        "minimized": True, "id": _text(payload.get("id"), 80), "token": _text(payload.get("token"), 80) or None,
        "cart_token": _text(payload.get("cart_token"), 80) or None, "created_at": payload.get("created_at"),
        "updated_at": payload.get("updated_at"), "completed_at": payload.get("completed_at"),
        "total_price": round(_num(payload.get("total_price")), 2), "currency": _text(payload.get("currency") or payload.get("presentment_currency"), 8) or None,
        "abandoned_checkout_url": _text(payload.get("abandoned_checkout_url"), 1000) or None, "line_items": items,
        "email_hash": email_marketing.email_hash(email) if email else None, "phone_key": phone_key(phone) if phone else None,
        "contact_enc": encrypt_secret(json.dumps(contact)) if contact else None,
        "accepts_marketing": bool(payload.get("buyer_accepts_marketing")),
    }


def _contact(cart: Dict[str, Any]) -> Dict[str, str]:
    from .crypto import decrypt_secret
    if not cart.get("contact_enc"):
        return {}
    try:
        return json.loads(decrypt_secret(cart["contact_enc"]))
    except (RuntimeError, ValueError):
        return {}


async def get_settings(client_id: str) -> Dict[str, Any]:
    rows = await sb_select(SETTINGS, select=",".join(SETTING_FIELDS), filters={"client_id": f"eq.{client_id}"}, limit=1)
    settings = {**DEFAULTS, **(rows[0] if rows else {})}
    settings["email_design"] = settings.get("email_design") if (settings.get("email_design") or {}).get("blocks") else email_builder.default_cart_design()
    return settings


def clean_settings(patch: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if "enabled" in patch:
        out["enabled"] = bool(patch["enabled"])
    if "steps" in patch:
        steps = []
        for step in (patch.get("steps") or [])[:MAX_STEPS]:
            channel = (step or {}).get("channel")
            if channel not in ("email", "whatsapp"):
                raise CartError("INVALID_STEP", "Cada passo precisa ser e-mail ou WhatsApp.")
            delay = int(_num((step or {}).get("delay_minutes")))
            if not 15 <= delay <= 60 * 24 * 7:
                raise CartError("INVALID_DELAY", "O tempo de cada passo vai de 15 minutos a 7 dias.")
            steps.append({"channel": channel, "delay_minutes": delay})
        if [s["delay_minutes"] for s in steps] != sorted(s["delay_minutes"] for s in steps):
            raise CartError("INVALID_ORDER", "Os passos precisam estar em ordem de tempo.")
        out["steps"] = steps
    if "email_subject" in patch:
        out["email_subject"] = _text(patch.get("email_subject"), 200) or DEFAULTS["email_subject"]
    if "email_design" in patch:
        out["email_design"] = email_builder.normalize_design(patch.get("email_design"))
    if "email_custom_html" in patch:
        out["email_custom_html"] = email_builder.sanitize_html(str(patch.get("email_custom_html") or "")) or None
    if "email_consent" in patch:
        out["email_consent"] = patch["email_consent"] if patch["email_consent"] in ("todos", "consentimento") else "todos"
    if "whatsapp_consent" in patch:
        out["whatsapp_consent"] = patch["whatsapp_consent"] if patch["whatsapp_consent"] in ("consentimento", "consentimento_ou_conversa") else "consentimento"
    if "whatsapp_number_id" in patch:
        out["whatsapp_number_id"] = _text(patch.get("whatsapp_number_id"), 40) or None
    if "whatsapp_template" in patch:
        out["whatsapp_template"] = _text(patch.get("whatsapp_template"), 512) or None
    if "whatsapp_language" in patch:
        out["whatsapp_language"] = _text(patch.get("whatsapp_language"), 12) or "pt_BR"
    if "whatsapp_variables" in patch:
        variables = [v for v in (patch.get("whatsapp_variables") or []) if v in WA_VARIABLES][:4]
        out["whatsapp_variables"] = variables
    if "attribution_days" in patch:
        out["attribution_days"] = max(1, min(int(_num(patch.get("attribution_days")) or 7), 30))
    return out


async def save_settings(client_id: str, patch: Dict[str, Any], *, user_id: Optional[str]) -> Dict[str, Any]:
    clean = clean_settings(patch)
    current = await get_settings(client_id)
    merged = {**current, **clean}
    if merged["enabled"]:
        channels = {s["channel"] for s in merged["steps"]}
        if not merged["steps"]:
            raise CartError("NO_STEPS", "Inclua pelo menos um passo na sequência.")
        if "whatsapp" in channels and not merged.get("whatsapp_template"):
            raise CartError("NO_TEMPLATE", "Escolha o template aprovado do WhatsApp para o passo de WhatsApp.")
        if "email" in channels:
            email_marketing.sender(await email_marketing.get_settings(client_id))
    await sb_upsert(SETTINGS, [{"client_id": client_id, **clean, "updated_by": user_id, "updated_at": _now().isoformat()}],
                    on_conflict="client_id")
    return await get_settings(client_id)


def first_due(created: Optional[datetime], steps: List[Dict[str, Any]], done: int) -> Optional[str]:
    if not created or done >= len(steps):
        return None
    return (created + timedelta(minutes=int(steps[done]["delay_minutes"]))).isoformat()


async def upsert_checkout(client_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Grava/atualiza o carrinho a partir do checkout minimizado. Nunca mexe no andamento da sequência."""
    if not data.get("minimized"):
        data = minimize(data)
    checkout_id = _text(data.get("id"), 80)
    if not checkout_id:
        return {"ignored": "sem_id"}
    rows = await sb_select(CARTS, select="checkout_id,status,steps_done,contact_enc",
                           filters={"client_id": f"eq.{client_id}", "checkout_id": f"eq.{checkout_id}"}, limit=1)
    content = {"checkout_token": data.get("token"), "cart_token": data.get("cart_token"), "created_at_shop": data.get("created_at"),
               "updated_at_shop": data.get("updated_at"), "completed_at": data.get("completed_at"), "value": data.get("total_price") or 0,
               "currency": data.get("currency"), "items": data.get("line_items") or [], "recovery_url": data.get("abandoned_checkout_url"),
               "accepts_marketing": bool(data.get("accepts_marketing")), "updated_at": _now().isoformat()}
    for key in ("email_hash", "phone_key", "contact_enc"):
        if data.get(key):
            content[key] = data[key]
    if rows:
        current = rows[0]
        if current["status"] != "aberto":
            content.pop("contact_enc", None)  # já encerrado: não volta a guardar contato
        await sb_update(CARTS, filters={"client_id": f"eq.{client_id}", "checkout_id": f"eq.{checkout_id}"}, patch=content, returning="minimal")
        return {"updated": True}
    has_contact = bool(data.get("email_hash") or data.get("phone_key"))
    if data.get("completed_at"):
        status = "comprou_sem_contato"
    else:
        status = "aberto" if has_contact else "sem_contato"
    settings = await get_settings(client_id)
    row = {"client_id": client_id, "checkout_id": checkout_id, **content, "status": status, "steps_done": 0,
           "next_step_at": first_due(_dt(data.get("created_at")) or _now(), settings["steps"], 0) if status == "aberto" else None}
    if status != "aberto":
        row["contact_enc"] = None
    await sb_upsert(CARTS, [row], on_conflict="client_id,checkout_id")
    return {"created": True, "status": status}


async def on_order(client_id: str, order: Dict[str, Any]) -> Dict[str, Any]:
    """Pedido novo: fecha o carrinho do mesmo checkout (recuperado se houve contato dentro da janela)."""
    token = _text(order.get("checkout_token"), 80)
    checkout_id = _text(order.get("checkout_id"), 80)
    if not token and not checkout_id:
        return {"ignored": True}
    filters = {"client_id": f"eq.{client_id}"}
    filters["or"] = f"(checkout_id.eq.{checkout_id or '-'},checkout_token.eq.{token or '-'})"
    rows = await sb_select(CARTS, select="checkout_id,status,steps_done,last_touch_at", filters=filters, limit=1)
    if not rows or rows[0]["status"] not in ("aberto", "expirado"):
        return {"ignored": True}
    settings = await get_settings(client_id)
    return await _close(client_id, rows[0], order_id=_text(order.get("id"), 40), value=_num(order.get("total_price")),
                        at=_dt(order.get("created_at")) or _now(), attribution_days=int(settings["attribution_days"]))


def outcome(cart: Dict[str, Any], *, at: datetime, attribution_days: int) -> str:
    last = _dt(cart.get("last_touch_at"))
    if int(cart.get("steps_done") or 0) > 0 and last and last <= at <= last + timedelta(days=attribution_days):
        return "recuperado"
    return "comprou_sem_contato"


async def _close(client_id: str, cart: Dict[str, Any], *, order_id: str, value: float, at: datetime, attribution_days: int) -> Dict[str, Any]:
    status = outcome(cart, at=at, attribution_days=attribution_days)
    patch = {"status": status, "next_step_at": None, "contact_enc": None, "updated_at": _now().isoformat(), "recovered_order_id": order_id or None}
    if status == "recuperado":
        patch.update({"recovered_value": round(value, 2), "recovered_at": at.isoformat()})
    await sb_update(CARTS, filters={"client_id": f"eq.{client_id}", "checkout_id": f"eq.{cart['checkout_id']}"}, patch=patch, returning="minimal")
    return {"status": status}


# ---------------------------------------------------------------- envio

async def _bought_since(client_id: str, email: Optional[str], since: str) -> Optional[Dict[str, Any]]:
    """Confere na loja se a pessoa comprou depois do abandono (mesmo sem o checkout ligado ao pedido)."""
    if not email:
        return None
    rows = await sb_select("shopify_orders", select="shopify_order_id,total_price,created_at_shopify",
                           filters={"client_id": f"eq.{client_id}", "email": f"ilike.{email}", "created_at_shopify": f"gte.{since}",
                                    "cancelled_at": "is.null"}, order="created_at_shopify.asc", limit=1)
    return rows[0] if rows else None


async def _talked_on_whatsapp(client_id: str, pkey: Optional[str]) -> bool:
    if not pkey:
        return False
    rows = await sb_select("whatsapp_threads", select="id", filters={"client_id": f"eq.{client_id}", "phone_key": f"eq.{pkey}"}, limit=1)
    return bool(rows)


def _money(value: Any) -> str:
    return f"R$ {_num(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def wa_params(names: List[str], *, first_name: str, cart: Dict[str, Any]) -> List[str]:
    items = cart.get("items") or []
    first_item = _text((items[0] or {}).get("title"), 60) if items else "seus itens"
    values = {"nome": first_name or "tudo bem", "produto": first_item + (f" e mais {len(items) - 1}" if len(items) > 1 else ""),
              "valor": _money(cart.get("value")), "link": _text(cart.get("recovery_url"), 1000)}
    return [values[n] for n in names]


async def _send_email(client_id: str, cart: Dict[str, Any], contact: Dict[str, str], settings: Dict[str, Any], step: int) -> Tuple[str, str, Optional[str]]:
    email = contact.get("email")
    if not email:
        return "pulado", "sem e-mail", None
    if settings["email_consent"] == "consentimento" and not cart.get("accepts_marketing"):
        return "pulado", "sem consentimento de marketing", None
    ehash = email_marketing.email_hash(email)
    if ehash in await email_marketing.suppressed(client_id):
        return "pulado", "descadastrado", None
    from . import saas
    if (await saas.remaining(client_id, "email_sends_month")) == 0:
        return "pulado", "limite do plano", None
    sender_settings = await email_marketing.get_settings(client_id)
    first = contact.get("first_name") or ""
    variables = {"nome": first or "Olá", "primeiro_nome": first or "Olá", "marca": _text(sender_settings.get("from_name"), 80),
                 "link_carrinho": _text(cart.get("recovery_url"), 1000), "valor_carrinho": _money(cart.get("value")),
                 "link_loja": _text(sender_settings.get("store_url"), 300), "descadastro": email_marketing.unsubscribe_url(client_id, ehash)}
    html, text = email_builder.render(settings["email_design"], sender_settings, variables, items=cart.get("items") or [],
                                      custom_html=settings.get("email_custom_html"))
    subject = email_builder.fill(_text(settings["email_subject"], 200), variables)
    msg = email_marketing._message(sender_settings, email, subject, html, text, variables["descadastro"],
                                   [{"name": "kind", "value": "carrinho"}])
    idem = f"carrinho/{cart['checkout_id']}/{step}"
    ids = await email_resend.send_batch([msg], idem=idem)
    await email_marketing._insert_ignore([{"client_id": client_id, "kind": "carrinho", "checkout_id": cart["checkout_id"],
                                           "email_hash": ehash, "idem_key": idem, "resend_id": ids[0],
                                           "status": "enviado" if ids[0] else "simulado"}])
    return ("enviado" if ids[0] else "simulado"), "", ids[0]


async def _send_whatsapp(client_id: str, cart: Dict[str, Any], contact: Dict[str, str], settings: Dict[str, Any]) -> Tuple[str, str, Optional[str]]:
    from . import whatsapp_native
    to = whatsapp_to(contact.get("phone"))
    if not to:
        return "pulado", "sem telefone", None
    allowed = bool(cart.get("accepts_marketing"))
    if not allowed and settings["whatsapp_consent"] == "consentimento_ou_conversa":
        allowed = await _talked_on_whatsapp(client_id, cart.get("phone_key"))
    if not allowed:
        return "pulado", "sem consentimento de marketing", None
    if not settings.get("whatsapp_template"):
        return "pulado", "template não escolhido", None
    from . import saas
    if (await saas.remaining(client_id, "whatsapp_month")) == 0:
        return "pulado", "limite do plano", None
    params = wa_params(list(settings.get("whatsapp_variables") or []), first_name=contact.get("first_name") or "", cart=cart)
    if (os.getenv("WHATSAPP_MARKETING_SEND_ENABLED") or "").strip().lower() != "true":
        return "simulado", "", None
    message_id = await whatsapp_native.send_template(client_id, number_id=settings.get("whatsapp_number_id"), to=to,
                                                     template=settings["whatsapp_template"], language=settings["whatsapp_language"], params=params)
    return "enviado", "", message_id or None


async def _advance(client_id: str, cart: Dict[str, Any], settings: Dict[str, Any]) -> str:
    created = _dt(cart.get("created_at_shop")) or _now()
    steps = settings["steps"]
    done = int(cart.get("steps_done") or 0)
    filters = {"client_id": f"eq.{client_id}", "checkout_id": f"eq.{cart['checkout_id']}"}
    if done >= len(steps):
        # Sequência terminou e a janela de atribuição passou sem compra.
        await sb_update(CARTS, filters=filters, patch={"status": "expirado", "next_step_at": None, "contact_enc": None,
                                                        "updated_at": _now().isoformat()}, returning="minimal")
        return "expirado"
    if _now() - created > timedelta(days=EXPIRE_DAYS):
        await sb_update(CARTS, filters=filters, patch={"status": "expirado", "next_step_at": None, "contact_enc": None,
                                                        "updated_at": _now().isoformat()}, returning="minimal")
        return "expirado"
    contact = _contact(cart)
    bought = await _bought_since(client_id, contact.get("email"), created.isoformat())
    if bought:
        result = await _close(client_id, cart, order_id=_text(bought.get("shopify_order_id"), 40), value=_num(bought.get("total_price")),
                              at=_dt(bought.get("created_at_shopify")) or _now(), attribution_days=int(settings["attribution_days"]))
        return result["status"]
    step = steps[done]
    try:
        if step["channel"] == "email":
            status, reason, provider_id = await _send_email(client_id, cart, contact, settings, done)
        else:
            status, reason, provider_id = await _send_whatsapp(client_id, cart, contact, settings)
    except Exception as exc:  # noqa: BLE001 — o passo fica registrado como falha e a sequência segue
        status, reason, provider_id = "falhou", getattr(exc, "code", type(exc).__name__), None
    await sb_upsert(TOUCHES, [{"client_id": client_id, "checkout_id": cart["checkout_id"], "step": done, "channel": step["channel"],
                               "status": status, "reason": reason or None, "provider_id": provider_id, "at": _now().isoformat()}],
                    on_conflict="client_id,checkout_id,step")
    touched = status in ("enviado", "simulado")
    next_at = first_due(created, steps, done + 1)
    if next_at is None:
        last = _now() if touched else (_dt(cart.get("last_touch_at")) or _now())
        next_at = (last + timedelta(days=int(settings["attribution_days"]))).isoformat()
    patch = {"steps_done": done + 1, "next_step_at": next_at, "updated_at": _now().isoformat()}
    if touched:
        patch["last_touch_at"] = _now().isoformat()
    await sb_update(CARTS, filters=filters, patch=patch, returning="minimal")
    return status


async def process_due() -> Dict[str, Any]:
    rows = await sb_select(CARTS, select="client_id,checkout_id,created_at_shop,value,items,recovery_url,email_hash,phone_key,contact_enc,"
                                         "accepts_marketing,steps_done,last_touch_at",
                           filters={"status": "eq.aberto", "next_step_at": f"lte.{_now().isoformat()}"}, order="next_step_at.asc", limit=DUE_LIMIT)
    cache: Dict[str, Dict[str, Any]] = {}
    total: Dict[str, int] = {"carts": 0, "errors": 0, "paused": 0}
    for cart in rows:
        cid = cart["client_id"]
        try:
            if cid not in cache:
                cache[cid] = await get_settings(cid)
            if not cache[cid]["enabled"]:
                total["paused"] += 1
                continue
            status = await _advance(cid, cart, cache[cid])
            total["carts"] += 1
            total[status] = total.get(status, 0) + 1
        except Exception as exc:  # noqa: BLE001
            total["errors"] += 1
            print(f"[cart_recovery] cart_failed client_id={cid} {type(exc).__name__}")
    return total


# ---------------------------------------------------------------- leitura

def summarize(carts: List[Dict[str, Any]], touches: List[Dict[str, Any]]) -> Dict[str, Any]:
    abandoned = [c for c in carts if c["status"] not in ("comprou_sem_contato",) or int(c.get("steps_done") or 0) > 0]
    recovered = [c for c in carts if c["status"] == "recuperado"]
    contacted = [c for c in carts if int(c.get("steps_done") or 0) > 0]
    by_channel: Dict[str, Dict[str, int]] = {}
    for t in touches:
        slot = by_channel.setdefault(t["channel"], {"enviado": 0, "simulado": 0, "pulado": 0, "falhou": 0})
        slot[t["status"]] = slot.get(t["status"], 0) + 1
    recovered_value = round(sum(_num(c.get("recovered_value")) for c in recovered), 2)
    return {"carts": len(abandoned), "abandoned_value": round(sum(_num(c.get("value")) for c in abandoned), 2),
            "contacted": len(contacted), "recovered": len(recovered), "recovered_value": recovered_value,
            "recovery_rate": round(len(recovered) / len(contacted) * 100, 1) if contacted else None,
            "bought_without_contact": sum(1 for c in carts if c["status"] == "comprou_sem_contato"),
            "open": sum(1 for c in carts if c["status"] == "aberto"), "by_channel": by_channel}


async def overview(client_id: str, days: int = 30) -> Dict[str, Any]:
    from .sales_by_origin import _paged
    since = (_now() - timedelta(days=max(1, min(days, 180)))).isoformat()
    carts, _ = await _paged(CARTS, select="checkout_id,created_at_shop,value,items,status,steps_done,last_touch_at,recovered_value,recovered_at",
                            filters={"client_id": f"eq.{client_id}", "created_at_shop": f"gte.{since}"}, order="created_at_shop.desc")
    touches, _ = await _paged(TOUCHES, select="checkout_id,step,channel,status,reason,at",
                              filters={"client_id": f"eq.{client_id}", "at": f"gte.{since}"}, order="at.desc")
    last_touch: Dict[str, Dict[str, Any]] = {}
    for t in touches:
        last_touch.setdefault(t["checkout_id"], t)
    recent = []
    for c in carts[:50]:
        items = c.get("items") or []
        touch = last_touch.get(c["checkout_id"])
        recent.append({"checkout_id": c["checkout_id"], "created_at": c.get("created_at_shop"), "value": _num(c.get("value")),
                       "items": len(items), "first_item": _text((items[0] or {}).get("title"), 80) if items else None,
                       "status": c["status"], "steps_done": int(c.get("steps_done") or 0),
                       "last_touch": {"channel": touch["channel"], "status": touch["status"], "reason": touch.get("reason"), "at": touch["at"]} if touch else None,
                       "recovered_value": _num(c.get("recovered_value")) or None})
    settings = await get_settings(client_id)
    from .commerce_context import resolve_commerce_provider
    provider = _text((await resolve_commerce_provider(client_id)).get("provider"), 20).lower() or None
    return {"days": days, "provider": provider, "summary": summarize(carts, touches), "recent": recent, "settings": settings,
            "simulated": {"email": not email_resend.send_enabled(),
                          "whatsapp": (os.getenv("WHATSAPP_MARKETING_SEND_ENABLED") or "").strip().lower() != "true"}}


async def register_webhooks(client_id: str) -> Dict[str, Any]:
    """Assina checkouts/create e checkouts/update na loja Shopify da empresa (lojas conectadas antes disto)."""
    import httpx
    from .shopify_config import shopify_admin_url
    from .shopify_oauth import resolve_shopify_connection_context
    ctx = await resolve_shopify_connection_context(client_id)
    callback = _text(os.getenv("SHOPIFY_WEBHOOK_URL"), 500)
    if not callback.startswith("https://"):
        raise CartError("NO_WEBHOOK_URL", "SHOPIFY_WEBHOOK_URL não está configurada no servidor.", 500)
    result: Dict[str, Any] = {"registered": [], "existing": [], "failed": []}
    async with httpx.AsyncClient(timeout=20) as client:
        for topic in CHECKOUT_TOPICS:
            resp = await client.post(shopify_admin_url(ctx.shop_domain, "webhooks.json"), headers={"X-Shopify-Access-Token": ctx.access_token},
                                     json={"webhook": {"topic": topic, "address": callback, "format": "json"}})
            if resp.status_code in (200, 201):
                result["registered"].append(topic)
            elif resp.status_code == 422:
                result["existing"].append(topic)
            else:
                result["failed"].append({"topic": topic, "status": resp.status_code})
    if not result["failed"]:
        await sb_upsert(SETTINGS, [{"client_id": client_id, "webhooks_registered_at": _now().isoformat()}], on_conflict="client_id")
    return result
