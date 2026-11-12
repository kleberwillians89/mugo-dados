"""Fluxos comerciais automáticos: boas-vindas, pós-venda, segunda compra e reativação.

Cada fluxo é uma mensagem (e-mail ou template de WhatsApp) que sai quando a pessoa cruza um marco:
- boas_vindas: primeira compra (mais N dias);
- pos_venda: N dias depois da última compra;
- segunda_compra: N dias depois da primeira compra, se ainda não voltou a comprar;
- reativacao: N dias sem comprar.

Regras:
- Janela de captura de 3 dias depois do marco: ligar um fluxo não dispara para a base inteira, só para quem
  está cruzando o marco agora.
- ``flow_sends`` (pessoa + fluxo + data de referência) garante um envio só; rodar de novo nunca duplica.
- Consentimento: "consentimento" = só quem aceitou marketing na loja; "todos" = e-mail para todos (com
  descadastro) e WhatsApp também para quem já conversou com a marca. Descadastro/bounce/spam nunca recebe.
- Resultado: compra da mesma pessoa (jornada da Etapa 3) até 7 dias depois do envio. Sem jornada montada, a tela avisa.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from . import email_builder, email_marketing, email_resend
from .ig_supabase import sb_select, sb_upsert

FLOWS = "commercial_flows"
SENDS = "flow_sends"
KINDS = ("boas_vindas", "pos_venda", "segunda_compra", "reativacao")
CATCH_DAYS = 3
ATTRIBUTION_DAYS = 7
PER_RUN = 500
WA_VARIABLES = ("nome", "marca", "link")

LABEL = {"boas_vindas": "Boas-vindas", "pos_venda": "Pós-venda", "segunda_compra": "Segunda compra", "reativacao": "Reativação"}
DEFAULTS: Dict[str, Dict[str, Any]] = {
    "boas_vindas": {"delay_days": 0, "consent": "todos", "subject": "Bem-vinda à {{marca}}, {{primeiro_nome}}",
                    "text": "Que bom ter você com a gente. Seu pedido já está sendo preparado — e qualquer dúvida é só responder este e-mail."},
    "pos_venda": {"delay_days": 7, "consent": "todos", "subject": "Como foi sua compra, {{primeiro_nome}}?",
                  "text": "Seu pedido já deve ter chegado. Conta pra gente o que achou? Sua opinião ajuda muito."},
    "segunda_compra": {"delay_days": 30, "consent": "consentimento", "subject": "{{primeiro_nome}}, separamos algo para você",
                       "text": "Faz um mês da sua primeira compra. Vem ver as novidades que chegaram desde então."},
    "reativacao": {"delay_days": 90, "consent": "consentimento", "subject": "Sentimos sua falta, {{primeiro_nome}}",
                   "text": "Faz um tempo que você não passa por aqui. Tem muita coisa nova esperando por você."},
}


class FlowError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(code)
        self.code = code
        self.message = message
        self.status = status


def _text(value: Any, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


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


def default_flow(kind: str) -> Dict[str, Any]:
    d = DEFAULTS[kind]
    return {
        "kind": kind, "enabled": False, "channel": "email", "delay_days": d["delay_days"], "consent": d["consent"],
        "subject": d["subject"], "preheader": "", "custom_html": None, "whatsapp_template": None, "whatsapp_language": "pt_BR",
        "whatsapp_variables": ["nome"],
        "design": {"blocks": [
            {"type": "logo", "align": "center"}, {"type": "titulo", "text": d["subject"], "align": "center"},
            {"type": "texto", "text": d["text"], "align": "center"},
            {"type": "botao", "label": "Ir para a loja", "href": "{{link_loja}}", "align": "center"},
        ]},
    }


FIELDS = ("kind,enabled,channel,delay_days,consent,subject,preheader,design,custom_html,whatsapp_template,whatsapp_language,"
          "whatsapp_variables,updated_at")


async def list_flows(client_id: str) -> List[Dict[str, Any]]:
    rows = {r["kind"]: r for r in await sb_select(FLOWS, select=FIELDS, filters={"client_id": f"eq.{client_id}"}, limit=10)}
    return [{**default_flow(k), **rows.get(k, {}), "label": LABEL[k]} for k in KINDS]


def clean_flow(patch: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if "enabled" in patch:
        out["enabled"] = bool(patch["enabled"])
    if "channel" in patch:
        if patch["channel"] not in ("email", "whatsapp"):
            raise FlowError("INVALID_CHANNEL", "O canal precisa ser e-mail ou WhatsApp.")
        out["channel"] = patch["channel"]
    if "delay_days" in patch:
        try:
            days = int(patch["delay_days"])
        except (TypeError, ValueError):
            raise FlowError("INVALID_DELAY", "Informe os dias em número.") from None
        if not 0 <= days <= 365:
            raise FlowError("INVALID_DELAY", "Os dias vão de 0 a 365.")
        out["delay_days"] = days
    if "consent" in patch:
        out["consent"] = patch["consent"] if patch["consent"] in ("consentimento", "todos") else "consentimento"
    for field in ("subject", "preheader"):
        if field in patch:
            out[field] = _text(patch.get(field), 200)
    if "design" in patch:
        out["design"] = email_builder.normalize_design(patch.get("design"))
    if "custom_html" in patch:
        out["custom_html"] = email_builder.sanitize_html(str(patch.get("custom_html") or "")) or None
    if "whatsapp_template" in patch:
        out["whatsapp_template"] = _text(patch.get("whatsapp_template"), 512) or None
    if "whatsapp_language" in patch:
        out["whatsapp_language"] = _text(patch.get("whatsapp_language"), 12) or "pt_BR"
    if "whatsapp_variables" in patch:
        out["whatsapp_variables"] = [v for v in (patch.get("whatsapp_variables") or []) if v in WA_VARIABLES][:3]
    return out


async def save_flow(client_id: str, kind: str, patch: Dict[str, Any], *, user_id: Optional[str]) -> Dict[str, Any]:
    if kind not in KINDS:
        raise FlowError("NOT_FOUND", "Fluxo não encontrado.", 404)
    clean = clean_flow(patch)
    current = next(f for f in await list_flows(client_id) if f["kind"] == kind)
    merged = {**current, **clean}
    if merged["enabled"]:
        if merged["channel"] == "whatsapp" and not merged.get("whatsapp_template"):
            raise FlowError("NO_TEMPLATE", "Escolha o template aprovado do WhatsApp.")
        if merged["channel"] == "email":
            email_marketing.sender(await email_marketing.get_settings(client_id))
            if not _text(merged.get("subject")):
                raise FlowError("NO_SUBJECT", "Escreva o assunto do e-mail.")
    row = {"client_id": client_id, "kind": kind, **{k: merged[k] for k in ("enabled", "channel", "delay_days", "consent", "subject", "preheader",
                                                                          "design", "custom_html", "whatsapp_template", "whatsapp_language",
                                                                          "whatsapp_variables")},
           "updated_by": user_id, "updated_at": _now().isoformat()}
    await sb_upsert(FLOWS, [row], on_conflict="client_id,kind")
    return next(f for f in await list_flows(client_id) if f["kind"] == kind)


# ---------------------------------------------------------------- quem recebe (função pura)

def milestone(kind: str, contact: Dict[str, Any]) -> Optional[str]:
    """A data de referência do fluxo para esta pessoa (ou None se o fluxo não se aplica)."""
    orders = int(contact.get("orders") or 0)
    if orders < 1:
        return None
    if kind == "boas_vindas":
        return contact.get("first_order_at") if orders == 1 else None
    if kind == "segunda_compra":
        return contact.get("first_order_at") if orders == 1 else None
    if kind in ("pos_venda", "reativacao"):
        return contact.get("last_order_at")
    return None


def due(kind: str, contact: Dict[str, Any], delay_days: int, now: datetime) -> Optional[str]:
    """Devolve a referência (AAAA-MM-DD do marco) se a pessoa cruzou o marco + N dias há no máximo 3 dias."""
    ref = _dt(milestone(kind, contact))
    if not ref:
        return None
    start = ref + timedelta(days=delay_days)
    if start <= now < start + timedelta(days=CATCH_DAYS):
        return ref.date().isoformat()
    return None


def allowed(flow: Dict[str, Any], contact: Dict[str, Any], *, blocked: set, talked: bool) -> Tuple[bool, str]:
    if flow["channel"] == "email":
        if contact["hash"] in blocked:
            return False, "descadastrado"
        if flow["consent"] == "consentimento" and contact.get("consent") is not True:
            return False, "sem consentimento de marketing"
        return True, ""
    if not contact.get("phone"):
        return False, "sem telefone"
    if contact.get("consent") is True or (flow["consent"] == "todos" and talked):
        return True, ""
    return False, "sem consentimento de marketing"


# ---------------------------------------------------------------- envio

def _variables(contact: Dict[str, Any], sender: Dict[str, Any], client_id: str) -> Dict[str, str]:
    first = _text(contact.get("first_name"), 80) or "Olá"
    return {"nome": _text(contact.get("name"), 160) or first, "primeiro_nome": first, "marca": _text(sender.get("from_name"), 80),
            "link_loja": _text(sender.get("store_url"), 300), "descadastro": email_marketing.unsubscribe_url(client_id, contact["hash"])}


async def _talked_keys(client_id: str) -> set:
    from .sales_by_origin import _paged
    rows, _ = await _paged("whatsapp_threads", select="phone_key", filters={"client_id": f"eq.{client_id}"}, order="phone_key.asc")
    return {r["phone_key"] for r in rows if r.get("phone_key")}


async def run_client(client_id: str, flows: List[Dict[str, Any]], *, now: Optional[datetime] = None) -> Dict[str, Any]:
    from .cart_recovery import whatsapp_to
    from .whatsapp_insights import phone_key
    now = now or _now()
    _, contacts = await email_marketing.load_contacts(client_id)
    blocked = await email_marketing.suppressed(client_id)
    since = (now - timedelta(days=400)).date().isoformat()
    from .sales_by_origin import _paged
    done_rows, _ = await _paged(SENDS, select="kind,email_hash,ref", filters={"client_id": f"eq.{client_id}", "ref": f"gte.{since}"},
                                order="ref.asc")
    done = {(r["kind"], r["email_hash"], r["ref"]) for r in done_rows}
    needs_talk = any(f["channel"] == "whatsapp" and f["consent"] == "todos" for f in flows)
    talked = await _talked_keys(client_id) if needs_talk else set()
    sender = await email_marketing.get_settings(client_id)
    wa_live = (os.getenv("WHATSAPP_MARKETING_SEND_ENABLED") or "").strip().lower() == "true"
    from . import saas
    quota = {"email": await saas.remaining(client_id, "email_sends_month"), "whatsapp": await saas.remaining(client_id, "whatsapp_month")}
    totals: Dict[str, Dict[str, int]] = {}
    for flow in flows:
        kind = flow["kind"]
        counts = totals.setdefault(kind, {"enviado": 0, "simulado": 0, "pulado": 0, "falhou": 0})
        batch: List[Tuple[Dict[str, Any], str]] = []
        for contact in contacts:
            ref = due(kind, contact, int(flow["delay_days"]), now)
            if not ref or (kind, contact["hash"], ref) in done:
                continue
            batch.append((contact, ref))
            if len(batch) >= PER_RUN:
                break
        rows: List[Dict[str, Any]] = []
        emails: List[Tuple[Dict[str, Any], str, Dict[str, Any]]] = []
        for contact, ref in batch:
            ok, reason = allowed(flow, contact, blocked=blocked, talked=phone_key(contact.get("phone")) in talked if contact.get("phone") else False)
            base = {"client_id": client_id, "kind": kind, "email_hash": contact["hash"], "ref": ref, "channel": flow["channel"], "at": now.isoformat()}
            if ok and quota[flow["channel"]] is not None:
                if quota[flow["channel"]] <= 0:
                    ok, reason = False, "limite do plano"
                else:
                    quota[flow["channel"]] -= 1
            if not ok:
                rows.append({**base, "status": "pulado", "reason": reason, "provider_id": None})
                continue
            if flow["channel"] == "email":
                variables = _variables(contact, sender, client_id)
                html, text = email_builder.render(flow["design"], sender, variables, preheader=flow.get("preheader") or "",
                                                  custom_html=flow.get("custom_html"))
                subject = email_builder.fill(_text(flow["subject"], 200), variables) or LABEL[kind]
                msg = email_marketing._message(sender, contact["email"], subject, html, text, variables["descadastro"],
                                               [{"name": "kind", "value": "fluxo"}, {"name": "flow", "value": kind}])
                emails.append((base, f"fluxo/{kind}/{contact['hash']}/{ref}", msg))
                continue
            status, provider_id, reason = "simulado", None, None
            if wa_live:
                from . import whatsapp_native
                values = {"nome": _text(contact.get("first_name"), 80) or "tudo bem", "marca": _text(sender.get("from_name"), 80),
                          "link": _text(sender.get("store_url"), 300)}
                try:
                    provider_id = await whatsapp_native.send_template(
                        client_id, number_id=None, to=whatsapp_to(contact.get("phone")) or "", template=flow["whatsapp_template"],
                        language=flow["whatsapp_language"], params=[values[v] for v in flow.get("whatsapp_variables") or []]) or None
                    status = "enviado"
                except Exception as exc:  # noqa: BLE001
                    status, reason = "falhou", getattr(exc, "code", type(exc).__name__)
            rows.append({**base, "status": status, "reason": reason, "provider_id": provider_id})
        for offset in range(0, len(emails), email_resend.BATCH_MAX):
            chunk = emails[offset:offset + email_resend.BATCH_MAX]
            try:
                ids = await email_resend.send_batch([m for _, _, m in chunk], idem=f"fluxo/{client_id}/{kind}/{chunk[0][1]}")
            except email_resend.ResendError as exc:
                if exc.retryable:
                    break  # fica para a próxima rodada (não grava, então não conta como feito)
                ids = None
                for base, _, _ in chunk:
                    rows.append({**base, "status": "falhou", "reason": exc.code, "provider_id": None})
                continue
            send_rows = []
            for (base, idem, _), rid in zip(chunk, ids):
                rows.append({**base, "status": "enviado" if rid else "simulado", "reason": None, "provider_id": rid})
                send_rows.append({"client_id": client_id, "kind": "fluxo", "email_hash": base["email_hash"], "idem_key": idem,
                                  "resend_id": rid, "status": "enviado" if rid else "simulado"})
            await email_marketing._insert_ignore(send_rows)
        if rows:
            await sb_upsert(SENDS, rows, on_conflict="client_id,kind,email_hash,ref")
        for r in rows:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
    return totals


async def run_all() -> Dict[str, Any]:
    """Cron de hora em hora: empresas com pelo menos um fluxo ligado. Uma falha não para as outras."""
    rows = await sb_select(FLOWS, select=FIELDS + ",client_id", filters={"enabled": "is.true"}, limit=2000)
    by_client: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        by_client.setdefault(r["client_id"], []).append(r)
    total = {"clients": 0, "errors": 0, "sent": 0}
    for cid, flows in by_client.items():
        try:
            result = await run_client(cid, flows)
            total["clients"] += 1
            total["sent"] += sum(c.get("enviado", 0) + c.get("simulado", 0) for c in result.values())
        except Exception as exc:  # noqa: BLE001
            total["errors"] += 1
            print(f"[commercial_flows] client_failed client_id={cid} {type(exc).__name__}")
    return total


# ---------------------------------------------------------------- resultado

def attribute(sends: List[Dict[str, Any]], person_of: Dict[str, str], purchases: Dict[str, List[Tuple[datetime, float]]]) -> Dict[str, Dict[str, Any]]:
    """Função pura: por fluxo, quantos compraram até 7 dias depois do envio e quanto. Cada pedido conta uma vez por fluxo."""
    out: Dict[str, Dict[str, Any]] = {}
    used: set = set()
    for s in sorted(sends, key=lambda r: r["at"]):
        slot = out.setdefault(s["kind"], {"sent": 0, "skipped": 0, "failed": 0, "buyers": 0, "revenue": 0.0})
        if s["status"] in ("enviado", "simulado"):
            slot["sent"] += 1
        elif s["status"] == "pulado":
            slot["skipped"] += 1
            continue
        else:
            slot["failed"] += 1
            continue
        person = person_of.get(s["email_hash"])
        at = _dt(s["at"])
        if not person or not at:
            continue
        bought = False
        for when, value in purchases.get(person, []):
            key = (s["kind"], person, when.isoformat())
            if at <= when <= at + timedelta(days=ATTRIBUTION_DAYS) and key not in used:
                used.add(key)
                slot["revenue"] += value
                bought = True
        if bought:
            slot["buyers"] += 1
    for slot in out.values():
        slot["revenue"] = round(slot["revenue"], 2)
        slot["conversion"] = round(slot["buyers"] / slot["sent"] * 100, 1) if slot["sent"] else None
    return out


async def overview(client_id: str, days: int = 30) -> Dict[str, Any]:
    from .sales_by_origin import _paged
    since = (_now() - timedelta(days=max(1, min(days, 180)))).isoformat()
    try:
        journey_ready = bool(await sb_select("customer_journey_runs", select="built_at", filters={"client_id": f"eq.{client_id}"}, limit=1))
    except Exception:  # noqa: BLE001
        journey_ready = False
    sends, _ = await _paged(SENDS, select="kind,email_hash,status,reason,at", filters={"client_id": f"eq.{client_id}", "at": f"gte.{since}"},
                            order="at.asc")
    person_of: Dict[str, str] = {}
    hashes = [] if not journey_ready else sorted({s["email_hash"] for s in sends if s["status"] in ("enviado", "simulado")})
    for offset in range(0, len(hashes), 150):
        part = hashes[offset:offset + 150]
        rows = await sb_select("customer_identities", select="value,person_id",
                               filters={"client_id": f"eq.{client_id}", "kind": "eq.email_hash", "value": f"in.({','.join(part)})"}, limit=1000)
        person_of.update({r["value"]: r["person_id"] for r in rows})
    purchases: Dict[str, List[Tuple[datetime, float]]] = {}
    if person_of:
        events, _ = await _paged("customer_events", select="person_id,at,value",
                                 filters={"client_id": f"eq.{client_id}", "kind": "in.(pedido,recompra)", "at": f"gte.{since}"}, order="at.asc")
        wanted = set(person_of.values())
        for e in events:
            if e["person_id"] in wanted and _dt(e["at"]):
                purchases.setdefault(e["person_id"], []).append((_dt(e["at"]), float(e.get("value") or 0)))
    try:
        journey = await sb_select("customer_journey_runs", select="built_at", filters={"client_id": f"eq.{client_id}"}, limit=1)
    except Exception:  # noqa: BLE001 — jornada (000107) ainda não aplicada: resultado aparece como "sem jornada"
        journey = []
    results = attribute(sends, person_of, purchases)
    flows = await list_flows(client_id)
    return {"days": days, "flows": [{**f, "result": results.get(f["kind"], {"sent": 0, "skipped": 0, "failed": 0, "buyers": 0, "revenue": 0.0,
                                                                          "conversion": None})} for f in flows],
            "journey_built_at": (journey[0] if journey else {}).get("built_at"),
            "simulated": {"email": not email_resend.send_enabled(),
                          "whatsapp": (os.getenv("WHATSAPP_MARKETING_SEND_ENABLED") or "").strip().lower() != "true"}}
