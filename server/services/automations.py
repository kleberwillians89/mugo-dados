"""Central de Automações: catálogo da Meta, regras e fila persistente de disparos de WhatsApp.

Fluxo: evento → validação → destinatário → template → variáveis → fila → WhatsApp → webhook → histórico.

- Envio pelo número oficial da Mugô: o mesmo ``mugozap-api`` do CRM que o Studio já usa (WhatsApp Cloud API).
  O CRM confere de novo template aprovado e idempotência; aqui a chave de idempotência é a mesma em toda
  nova tentativa, então um retry nunca vira mensagem duplicada.
- Automações cujo dono é o CRM (tarefas, resumo diário, financeiro, leads) só aparecem aqui: o Dados nunca
  as dispara, para não duplicar o que o CRM já envia.
- ``AUTOMATIONS_SEND_ENABLED`` diferente de ``true`` = modo simulado: a fila roda inteira e grava
  "simulado", sem nenhuma chamada de envio. É o padrão.
- Status de aprovação vem só da Meta (sincronização do catálogo), nunca definido à mão.
"""
from __future__ import annotations

import hashlib
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo

import httpx

from .ig_supabase import _request, sb_delete, sb_rpc, sb_select, sb_update, sb_upsert
from .meta_config import META_GRAPH_BASE_URL

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
DEFINITIONS = "automation_definitions"
CATALOG = "whatsapp_template_catalog"
OUTBOX = "automation_outbox"
TEAM = "automation_team_members"
PREFS = "automation_recipient_prefs"
RESPONSES = "automation_responses"
CONTACTS = "studio_client_contacts"

BACKOFF_SECONDS = (60, 300, 1800, 7200, 21600)
MAX_ATTEMPTS = len(BACKOFF_SECONDS)
# Falhas passageiras: tentar de novo com a MESMA chave (o CRM deduplica).
RETRYABLE = {"MUGOZAP_UNAVAILABLE", "SEND_OUTCOME_UNKNOWN", "RATE_LIMITED", "HTTP_429", "HTTP_500", "HTTP_502", "HTTP_503", "HTTP_504"}
_PLACEHOLDER = re.compile(r"\{\{\s*(\d+)\s*\}\}")


class AutomationError(RuntimeError):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def send_enabled() -> bool:
    return (os.getenv("AUTOMATIONS_SEND_ENABLED") or "").strip().lower() == "true"


def mask_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    return f"{digits[:4]}•••••{digits[-2:]}" if len(digits) >= 8 else "•••"


def idempotency_key(*parts: Any) -> str:
    raw = "|".join(str(p) for p in parts)
    return "auto-" + hashlib.sha256(raw.encode()).hexdigest()[:48]


# ---------------------------------------------------------------- catálogo da Meta


def catalog_config() -> Optional[Dict[str, str]]:
    waba = (os.getenv("WHATSAPP_WABA_ID") or "").strip()
    token = (os.getenv("WHATSAPP_TEMPLATES_TOKEN") or "").strip()
    return {"waba_id": waba, "token": token} if waba.isdigit() and token else None


def parse_template(item: Dict[str, Any]) -> Dict[str, Any]:
    """Resume os componentes da Meta no que o motor precisa validar."""
    body_params, header_format, url_dynamic, quick = 0, None, False, []
    for comp in item.get("components") or []:
        kind = str(comp.get("type") or "").upper()
        if kind == "BODY":
            body_params = len(set(_PLACEHOLDER.findall(str(comp.get("text") or ""))))
        elif kind == "HEADER":
            header_format = str(comp.get("format") or "").upper() or None
        elif kind == "BUTTONS":
            for button in comp.get("buttons") or []:
                btype = str(button.get("type") or "").upper()
                if btype == "URL" and _PLACEHOLDER.search(str(button.get("url") or "")):
                    url_dynamic = True
                elif btype == "QUICK_REPLY" and button.get("text"):
                    quick.append(str(button["text"])[:60])
    return {
        "name": str(item.get("name") or ""), "language": str(item.get("language") or ""),
        "category": str(item.get("category") or "").upper() or None, "status": str(item.get("status") or "").upper() or "UNKNOWN",
        "rejected_reason": (str(item.get("rejected_reason")) if item.get("rejected_reason") not in (None, "NONE") else None),
        "body_param_count": body_params, "header_format": header_format, "button_url_dynamic": url_dynamic,
        "quick_replies": quick, "components": item.get("components") or [], "meta_template_id": str(item.get("id") or "") or None,
    }


async def sync_catalog() -> Dict[str, Any]:
    """Espelha os templates do WhatsApp Business da Mugô. Leitura apenas: nada é criado ou alterado na Meta."""
    cfg = catalog_config()
    if not cfg:
        raise AutomationError("CATALOG_NOT_CONFIGURED", "Defina WHATSAPP_WABA_ID e WHATSAPP_TEMPLATES_TOKEN no backend.")
    url = f"{META_GRAPH_BASE_URL}/{cfg['waba_id']}/message_templates"
    params: Optional[Dict[str, Any]] = {"fields": "id,name,language,status,category,components,rejected_reason", "limit": 200}
    found: List[Dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=30) as client:
        for _ in range(20):
            response = await client.get(url, params=params, headers={"Authorization": f"Bearer {cfg['token']}"})
            if response.status_code >= 400:
                raise AutomationError("CATALOG_SYNC_FAILED", f"A Meta recusou a leitura dos templates (HTTP {response.status_code}).")
            data = response.json() or {}
            found.extend(parse_template(item) for item in data.get("data") or [])
            nxt = ((data.get("paging") or {}).get("next"))
            if not nxt:
                break
            url, params = nxt, None
    now = _iso(_now())
    rows = [{**t, "synced_at": now} for t in found if t["name"] and t["language"]]
    if rows:
        await sb_upsert(CATALOG, rows, on_conflict="name,language")
    # O catálogo espelha a Meta: template apagado lá some daqui (assim nunca parece aprovado por engano).
    await sb_delete(CATALOG, filters={"synced_at": f"lt.{now}"}, returning="minimal")
    return {"templates": len(rows), "approved": sum(1 for r in rows if r["status"] == "APPROVED"), "synced_at": now}


async def load_catalog() -> Dict[tuple, Dict[str, Any]]:
    rows = await sb_select(CATALOG, limit=1000)
    return {(r["name"], r["language"]): r for r in rows}


async def is_enabled(key: str, default: bool = True) -> bool:
    """Chave liga/desliga da central para fluxos que já existiam (ex.: convite de sexta).
    Sem a migração aplicada, mantém o comportamento anterior (default)."""
    try:
        rows = await sb_select(DEFINITIONS, select="automation_enabled", filters={"key": f"eq.{key}"}, limit=1)
    except Exception:  # noqa: BLE001
        return default
    return bool(rows[0].get("automation_enabled")) if rows else default


async def load_definitions() -> Dict[str, Dict[str, Any]]:
    rows = await sb_select(DEFINITIONS, order="key.asc", limit=200)
    return {r["key"]: r for r in rows}


# ---------------------------------------------------------------- situação de cada automação


def integration_configured(definition: Dict[str, Any], *, mugozap_ready: bool, calendar_ready: bool) -> bool:
    if definition["owner"] != "dados":
        return False
    needs_calendar = (definition.get("recipients") or {}).get("from") == "calendar_attendees"
    return mugozap_ready and (calendar_ready or not needs_calendar)


def readiness(definition: Dict[str, Any], template: Optional[Dict[str, Any]], *, mugozap_ready: bool,
              calendar_ready: bool, catalog_ready: bool) -> Dict[str, Any]:
    """Os quatro estados que a central mostra separados."""
    approved = bool(template and template.get("status") == "APPROVED")
    variables_ok = bool(template) and int(template.get("body_param_count") or 0) == len(definition.get("variable_map") or [])
    category_ok = not template or not template.get("category") or template["category"] == definition["expected_category"]
    configured = integration_configured(definition, mugozap_ready=mugozap_ready, calendar_ready=calendar_ready)
    problems: List[str] = []
    if definition["owner"] == "crm":
        problems.append("Disparada pelo CRM; o Dados não envia para não duplicar.")
    elif definition["owner"] == "tecnico":
        problems.append("Template técnico, sem disparo automático.")
    if not catalog_ready:
        problems.append("Catálogo da Meta não sincronizado.")
    elif not template:
        problems.append("Template não encontrado na Meta.")
    elif not approved:
        problems.append(f"Meta: {template.get('status')}.")
    if template and definition["owner"] == "dados" and not variables_ok:
        problems.append(f"Variáveis: a Meta espera {template.get('body_param_count')}, a automação define {len(definition.get('variable_map') or [])}.")
    if template and not category_ok:
        problems.append(f"Categoria na Meta é {template.get('category')}, esperada {definition['expected_category']}.")
    if definition["owner"] == "dados" and not configured:
        problems.append("Integração pendente (MugôZap e/ou Google Calendar).")
    operational = (definition["owner"] == "dados" and bool(definition.get("automation_enabled")) and approved
                   and variables_ok and category_ok and configured and send_enabled())
    return {
        "automation_enabled": bool(definition.get("automation_enabled")),
        "template_approved": approved,
        "integration_configured": configured,
        "operational": operational,
        "simulated_only": definition["owner"] == "dados" and not send_enabled(),
        "problems": problems,
    }


# ---------------------------------------------------------------- destinatários


async def client_contacts(client_id: str, receives: Optional[str]) -> List[Dict[str, Any]]:
    """Contatos SÓ da empresa do evento. Nunca cruza empresas."""
    rows = await sb_select(CONTACTS, select="id,client_id,name,phone,email,receives,active",
                           filters={"client_id": f"eq.{client_id}", "active": "eq.true"}, limit=50)
    return [r for r in rows if r.get("client_id") == client_id and (not receives or receives in (r.get("receives") or []))]


async def team_members(flag: str = "receives_internal") -> List[Dict[str, Any]]:
    rows = await sb_select(TEAM, select="id,name,email,phone,active,receives_internal,receives_campaign_alerts",
                           filters={"active": "eq.true", flag: "eq.true"}, limit=200)
    return [r for r in rows if r.get("phone")]


async def prefs_for(phone: str) -> Dict[str, Any]:
    rows = await sb_select(PREFS, filters={"phone": f"eq.{phone}"}, limit=1)
    return rows[0] if rows else {"opted_out": False, "marketing_opt_in": False}


# ---------------------------------------------------------------- fila


async def enqueue(definition: Dict[str, Any], *, client_id: Optional[str], recipient: Dict[str, Any], params: Dict[str, Any],
                  source_type: str, source_id: str, scheduled_for: Optional[datetime] = None,
                  button_suffix: Optional[str] = None, key_parts: Iterable[Any] = ()) -> Optional[Dict[str, Any]]:
    """Coloca na fila. Mesma chave = mesma mensagem: a segunda tentativa de enfileirar é ignorada."""
    if definition["owner"] != "dados":
        raise AutomationError("NOT_DADOS_OWNED", "Esta automação é disparada pelo CRM.")
    audience = definition["audience"]
    if audience == "equipe" and not recipient.get("team_member"):
        # alerta de campanha e avisos técnicos nunca vão para contato de cliente
        raise AutomationError("TEAM_ONLY", "Automação exclusiva da equipe Mugô.")
    if audience == "cliente" and recipient.get("client_id") != client_id:
        raise AutomationError("TENANT_MISMATCH", "Destinatário não pertence a esta empresa.")
    phone = re.sub(r"\D", "", str(recipient.get("phone") or ""))
    if not re.fullmatch(r"[0-9]{10,15}", phone):
        raise AutomationError("PHONE_INVALID")
    key = idempotency_key(definition["key"], client_id or "-", phone, source_type, source_id, *key_parts)
    row = {
        "automation_key": definition["key"], "template_name": definition["template_name"], "language": definition.get("language") or "pt_BR",
        "client_id": client_id, "audience": audience, "recipient_ref": str(recipient.get("id") or "")[:200] or None,
        "recipient_name": str(recipient.get("name") or "")[:120] or None, "recipient_phone": phone,
        "params": {k: str(params.get(k) if params.get(k) is not None else "")[:300] for k in definition.get("variable_map") or []},
        "button_suffix": button_suffix, "source_type": source_type[:40], "source_id": str(source_id)[:200],
        "idempotency_key": key, "scheduled_for": _iso(scheduled_for or _now()), "status": "agendado",
    }
    data = await _request("POST", f"/{OUTBOX}", params={"on_conflict": "idempotency_key"}, json=[row],
                          headers={"Prefer": "resolution=ignore-duplicates,return=representation"})
    return data[0] if isinstance(data, list) and data else None


async def cancel_pending(source_type: str, source_id: str, *, keep_keys: Iterable[str] = (), reason: str) -> int:
    """Cancela lembretes ainda não enviados de um evento (alterado, reagendado ou cancelado)."""
    rows = await sb_select(OUTBOX, select="id,idempotency_key",
                           filters={"source_type": f"eq.{source_type}", "source_id": f"eq.{source_id}", "status": "eq.agendado"}, limit=200)
    keep = set(keep_keys)
    cancelled = 0
    for row in rows:
        if row["idempotency_key"] in keep:
            continue
        done = await sb_update(OUTBOX, filters={"id": f"eq.{row['id']}", "status": "eq.agendado"},
                               patch={"status": "cancelado", "cancelled_reason": reason[:200]})
        cancelled += len(done)
    return cancelled


def render_text(template: Optional[Dict[str, Any]], values: List[str]) -> str:
    body = next((str(c.get("text") or "") for c in (template or {}).get("components") or [] if str(c.get("type")).upper() == "BODY"), "")
    return _PLACEHOLDER.sub(lambda m: values[int(m.group(1)) - 1] if 0 < int(m.group(1)) <= len(values) else m.group(0), body)


def build_components(template: Dict[str, Any], values: List[str], button_suffix: Optional[str]) -> List[Dict[str, Any]]:
    if template.get("header_format") in {"IMAGE", "VIDEO", "DOCUMENT"}:
        raise AutomationError("HEADER_MEDIA_REQUIRED")
    components: List[Dict[str, Any]] = [{"type": "body", "parameters": [{"type": "text", "text": v} for v in values]}]
    if template.get("button_url_dynamic"):
        if not button_suffix:
            raise AutomationError("BUTTON_PARAM_REQUIRED")
        components.append({"type": "button", "sub_type": "url", "index": "0", "parameters": [{"type": "text", "text": button_suffix}]})
    return components


def _button_suffix(value: Optional[str]) -> Optional[str]:
    """Token do link de aprovação fica cifrado na fila; só é aberto na hora de montar o envio."""
    if value and value.startswith("enc:"):
        from .crypto import decrypt_secret
        try:
            return decrypt_secret(value[4:])
        except Exception:
            raise AutomationError("BUTTON_PARAM_UNREADABLE") from None
    return value


async def validate(row: Dict[str, Any], definition: Optional[Dict[str, Any]], template: Optional[Dict[str, Any]]) -> Optional[str]:
    """Motivo de bloqueio, ou None se pode seguir. Revalida na hora do envio (a Meta pode ter mudado)."""
    if not definition:
        return "AUTOMATION_UNKNOWN"
    if definition["owner"] != "dados":
        return "NOT_DADOS_OWNED"
    if not definition.get("automation_enabled"):
        return "AUTOMATION_DISABLED"
    if not template or template.get("status") != "APPROVED":
        return "TEMPLATE_NOT_APPROVED"
    values = [str((row.get("params") or {}).get(k) or "").strip() for k in definition.get("variable_map") or []]
    if int(template.get("body_param_count") or 0) != len(values):
        return "VARIABLES_MISMATCH"
    if any(not v or v == "—" for v in values):
        return "DATA_MISSING"
    prefs = await prefs_for(row["recipient_phone"])
    if prefs.get("opted_out"):
        return "RECIPIENT_OPTED_OUT"
    if (template.get("category") or definition["expected_category"]) == "MARKETING" and not prefs.get("marketing_opt_in"):
        return "MARKETING_CONSENT_REQUIRED"
    if row.get("audience") == "equipe":
        team = await sb_select(TEAM, select="phone", filters={"phone": f"eq.{row['recipient_phone']}", "active": "eq.true"}, limit=1)
        if not team:
            return "TEAM_ONLY"
    return None


async def _finish(row: Dict[str, Any], token: str, patch: Dict[str, Any]) -> None:
    await sb_update(OUTBOX, filters={"id": f"eq.{row['id']}", "claim_token": f"eq.{token}"}, patch=patch, returning="minimal")


async def process_due(limit: int = 50) -> Dict[str, int]:
    """Processa o que venceu. Cada linha é travada (claim) antes; só quem travou pode concluir."""
    from .studio_messages import mugozap_config, mugozap_send

    token = str(uuid.uuid4())
    rows = await sb_rpc("claim_automation_outbox", {"p_limit": limit, "p_token": token}) or []
    definitions, catalog = await load_definitions(), await load_catalog()
    cfg = mugozap_config()
    counts = {"claimed": len(rows), "enviado": 0, "simulado": 0, "bloqueado": 0, "falhou": 0, "reagendado": 0}
    for row in rows:
        definition = definitions.get(row["automation_key"])
        template = catalog.get((row["template_name"], row.get("language") or "pt_BR"))
        reason = await validate(row, definition, template)
        if reason:
            await _finish(row, token, {"status": "bloqueado", "last_error": reason, "claim_token": None})
            counts["bloqueado"] += 1
            continue
        values = [str(row["params"][k]) for k in definition["variable_map"]]
        try:
            components = build_components(template, values, _button_suffix(row.get("button_suffix")))
        except AutomationError as exc:
            await _finish(row, token, {"status": "bloqueado", "last_error": exc.code, "claim_token": None})
            counts["bloqueado"] += 1
            continue
        if not send_enabled():
            await _finish(row, token, {"status": "simulado", "last_error": None, "claim_token": None, "sent_at": _iso(_now())})
            counts["simulado"] += 1
            continue
        if not cfg:
            result = {"ok": False, "code": "MUGOZAP_UNAVAILABLE"}
        else:
            result = await mugozap_send(cfg, phone=row["recipient_phone"], template_name=row["template_name"],
                                        components=components, idempotency_key=row["idempotency_key"])
        attempts = int(row.get("attempts") or 0) + 1
        if result.get("ok"):
            await _finish(row, token, {"status": "enviado", "attempts": attempts, "provider_message_id": result.get("provider_message_id"),
                                       "delivery_status": "accepted", "delivery_updated_at": _iso(_now()), "sent_at": _iso(_now()),
                                       "last_error": None, "claim_token": None})
            counts["enviado"] += 1
        elif result.get("code") in RETRYABLE and attempts < MAX_ATTEMPTS:
            await _finish(row, token, {"status": "agendado", "attempts": attempts, "last_error": result.get("code"), "claim_token": None,
                                       "next_attempt_at": _iso(_now() + timedelta(seconds=BACKOFF_SECONDS[attempts - 1]))})
            counts["reagendado"] += 1
        else:
            await _finish(row, token, {"status": "falhou", "attempts": attempts, "last_error": str(result.get("code"))[:300], "claim_token": None})
            counts["falhou"] += 1
    return counts


# ---------------------------------------------------------------- webhook (status e respostas)

DELIVERY_ORDER = {"accepted": 0, "sent": 1, "delivered": 2, "read": 3, "failed": 4}


async def apply_status(provider_message_id: str, status: str, error: Optional[str] = None) -> Dict[str, Any]:
    """Status da Meta repassado pelo webhook do CRM. Nunca regride (lido não volta para entregue)."""
    status = (status or "").lower()
    if status not in DELIVERY_ORDER:
        return {"ok": True, "ignored": "unknown_status"}
    rows = await sb_select(OUTBOX, select="id,delivery_status", filters={"provider_message_id": f"eq.{provider_message_id}"}, limit=1)
    if not rows:
        return {"ok": True, "ignored": "unknown_message"}
    current = rows[0].get("delivery_status")
    if current and DELIVERY_ORDER.get(current, -1) >= DELIVERY_ORDER[status] and status != "failed":
        return {"ok": True, "ignored": "stale"}
    patch: Dict[str, Any] = {"delivery_status": status, "delivery_updated_at": _iso(_now())}
    if status == "failed":
        patch["last_error"] = (error or "META_DELIVERY_FAILED")[:300]
    await sb_update(OUTBOX, filters={"id": f"eq.{rows[0]['id']}"}, patch=patch, returning="minimal")
    return {"ok": True, "status": status}


# ---------------------------------------------------------------- simulação (nenhum envio)


async def simulate(key: str, *, params: Dict[str, Any], phone: Optional[str] = None, button_suffix: Optional[str] = None) -> Dict[str, Any]:
    definitions, catalog = await load_definitions(), await load_catalog()
    definition = definitions.get(key)
    if not definition:
        raise AutomationError("AUTOMATION_UNKNOWN")
    template = catalog.get((definition["template_name"], definition.get("language") or "pt_BR"))
    row = {"params": params, "recipient_phone": re.sub(r"\D", "", phone or "") or "5511900000000", "audience": definition["audience"]}
    reason = await validate(row, definition, template)
    values = [str(params.get(k) or "") for k in definition.get("variable_map") or []]
    components: Optional[List[Dict[str, Any]]] = None
    if template and not reason:
        try:
            components = build_components(template, values, button_suffix)
        except AutomationError as exc:
            reason = exc.code
    return {"automation": key, "template_name": definition["template_name"], "would_send": reason is None,
            "blocked_reason": reason, "text": render_text(template, values) if template else None,
            "components": components, "real_send": False}


# ---------------------------------------------------------------- consumo


def _rate(category: str) -> Optional[float]:
    raw = (os.getenv(f"AUTOMATIONS_COST_{category}_BRL") or "").strip().replace(",", ".")
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


async def usage_summary() -> Dict[str, Any]:
    since = _now().astimezone(SAO_PAULO).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    rows = await sb_select(OUTBOX, select="template_name,status,delivery_status",
                           filters={"created_at": f"gte.{_iso(since)}"}, limit=10000)
    catalog = await load_catalog()
    by_status: Dict[str, int] = {}
    by_category: Dict[str, int] = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        if r["status"] == "enviado":
            category = (catalog.get((r["template_name"], "pt_BR")) or {}).get("category") or "UTILITY"
            by_category[category] = by_category.get(category, 0) + 1
    rates = {c: _rate(c) for c in by_category}
    estimate = sum(n * rates[c] for c, n in by_category.items() if rates[c] is not None) if any(v is not None for v in rates.values()) else None
    return {"month_start": since.date().isoformat(), "by_status": by_status, "sent_by_category": by_category,
            "estimated_cost_brl": round(estimate, 2) if estimate is not None else None,
            "cost_note": "Estimativa com as tarifas configuradas (AUTOMATIONS_COST_<CATEGORIA>_BRL); a fatura oficial é a da Meta."}
