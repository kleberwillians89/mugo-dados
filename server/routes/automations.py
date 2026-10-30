"""
Central de Automações (Configurações → WhatsApp → Automações) e Google Calendar da Mugô.

Tudo aqui é da equipe Mugô (platform_admin/agency_admin), exceto:
- GET /api/clients/{client_id}/meetings: reuniões da própria empresa para a agenda (qualquer membro);
- POST /api/automations/google-calendar/webhook: chamado pelo Google, autenticado pelo token do canal.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from services import automation_triggers, automations, google_calendar
from services.ig_supabase import sb_delete, sb_insert, sb_select, sb_update, sb_upsert
from services.tenant import is_agency_user, require_client_read, require_user_id

router = APIRouter(prefix="/api/automations", tags=["automations"])
client_router = APIRouter(prefix="/api/clients/{client_id}", tags=["automations"])

FIELD = re.compile(r"^[a-z_]{1,40}$")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DefinitionPatch(Strict):
    automation_enabled: Optional[bool] = None
    schedule: Optional[Dict[str, Any]] = None
    lead_minutes: Optional[int] = Field(default=None, ge=0, le=20160)
    recipients: Optional[Dict[str, Any]] = None
    variable_map: Optional[List[str]] = Field(default=None, max_length=12)


class SimulateInput(Strict):
    params: Dict[str, str] = Field(default_factory=dict)
    phone: Optional[str] = Field(default=None, max_length=20)
    button_suffix: Optional[str] = Field(default=None, max_length=200)


class EmitInput(Strict):
    client_id: str = Field(min_length=1, max_length=120)
    source_id: str = Field(min_length=1, max_length=120)
    params: Dict[str, str] = Field(default_factory=dict)


class TeamMemberInput(Strict):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=200)
    phone: Optional[str] = Field(default=None, max_length=20)
    active: bool = True
    receives_internal: bool = True
    receives_campaign_alerts: bool = False


class PrefsInput(Strict):
    opted_out: Optional[bool] = None
    marketing_opt_in: Optional[bool] = None
    source: Optional[str] = Field(default=None, max_length=120)


class CalendarSelect(Strict):
    calendar_id: str = Field(min_length=1, max_length=300)


async def agency(authorization: Optional[str]) -> str:
    user_id = await require_user_id(authorization)
    if not await is_agency_user(authorization):
        raise HTTPException(403, "Central de Automações é exclusiva da equipe Mugô.")
    return user_id


def _fail(exc: Exception) -> HTTPException:
    code = getattr(exc, "code", "AUTOMATION_ERROR")
    status = {"NOT_CONFIGURED": 503, "CATALOG_NOT_CONFIGURED": 503, "NOT_CONNECTED": 409, "REAUTH_REQUIRED": 409,
              "CALENDAR_NOT_SELECTED": 409, "AUTOMATION_UNKNOWN": 404, "CALENDAR_NOT_ALLOWED": 403, "TEAM_ONLY": 403,
              "TENANT_MISMATCH": 403}.get(code, 422 if code.isupper() else 502)
    return HTTPException(status, {"code": code, "message": str(exc) if str(exc) != code else "Não foi possível concluir."})


def _phone(raw: Optional[str]) -> Optional[str]:
    digits = re.sub(r"\D", "", raw or "")
    if raw and not re.fullmatch(r"[0-9]{10,15}", digits):
        raise HTTPException(422, "Telefone inválido (DDI + DDD + número).")
    return digits or None


# ---------------------------------------------------------------- central


@router.get("")
async def overview(authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    from services.studio_messages import mugozap_config

    await agency(authorization)
    definitions, catalog = await automations.load_definitions(), await automations.load_catalog()
    calendar = await google_calendar.connection()
    flags = {"send_enabled": automations.send_enabled(), "mugozap_configured": mugozap_config() is not None,
             "catalog_configured": automations.catalog_config() is not None,
             "catalog_synced_at": max((t.get("synced_at") or "" for t in catalog.values()), default=None) or None,
             "calendar": google_calendar.public_status(calendar)}
    items = []
    for definition in definitions.values():
        template = catalog.get((definition["template_name"], definition.get("language") or "pt_BR"))
        state = automations.readiness(definition, template, mugozap_ready=flags["mugozap_configured"],
                                      calendar_ready=calendar.get("status") == "ativo", catalog_ready=bool(catalog))
        items.append({**definition, "template": template and {k: template.get(k) for k in (
            "category", "language", "status", "rejected_reason", "body_param_count", "button_url_dynamic", "quick_replies", "synced_at")},
            "state": state})
    known = {(d["template_name"], d.get("language") or "pt_BR") for d in definitions.values()}
    others = [{k: t.get(k) for k in ("name", "language", "category", "status")} for key, t in catalog.items() if key not in known]
    return {"flags": flags, "automations": items, "other_templates": others}


@router.patch("/{key}")
async def update_definition(key: str, body: DefinitionPatch, authorization: Optional[str] = Header(default=None)):
    user_id = await agency(authorization)
    definition = (await automations.load_definitions()).get(key)
    if not definition:
        raise HTTPException(404, "Automação não encontrada.")
    patch = body.model_dump(exclude_unset=True)
    if definition["owner"] == "tecnico" and patch.get("automation_enabled"):
        raise HTTPException(409, "hello_world é técnico e não tem disparo automático.")
    if definition["owner"] == "crm":
        # Ligar/desligar aqui não pararia o CRM: a configuração fica onde o disparo acontece.
        raise HTTPException(409, "Configuração desta automação fica no CRM, que é quem dispara.")
    if "variable_map" in patch and not all(FIELD.fullmatch(v) for v in patch["variable_map"] or []):
        raise HTTPException(422, "Variáveis: use nomes simples (ex.: nome, data).")
    rows = await sb_update(automations.DEFINITIONS, filters={"key": f"eq.{key}"}, patch={**patch, "updated_by": user_id})
    return rows[0] if rows else definition


@router.post("/catalog/sync")
async def sync_catalog(authorization: Optional[str] = Header(default=None)):
    await agency(authorization)
    try:
        return await automations.sync_catalog()
    except automations.AutomationError as exc:
        raise _fail(exc) from None


@router.get("/outbox")
async def outbox(status: Optional[str] = Query(default=None, max_length=20), key: Optional[str] = Query(default=None, max_length=80),
                 client_id: Optional[str] = Query(default=None, max_length=120), limit: int = Query(default=100, ge=1, le=500),
                 authorization: Optional[str] = Header(default=None)):
    await agency(authorization)
    filters: Dict[str, str] = {}
    if status:
        filters["status"] = f"eq.{status}"
    if key:
        filters["automation_key"] = f"eq.{key}"
    if client_id:
        filters["client_id"] = f"eq.{client_id}"
    rows = await sb_select(automations.OUTBOX, filters=filters, order="created_at.desc", limit=limit, select=(
        "id,automation_key,template_name,client_id,audience,recipient_name,recipient_phone,source_type,source_id,scheduled_for,"
        "status,attempts,next_attempt_at,last_error,delivery_status,delivery_updated_at,sent_at,cancelled_reason,created_at"))
    for row in rows:  # histórico nunca devolve telefone completo
        row["recipient_phone"] = automations.mask_phone(row.get("recipient_phone") or "")
    return {"items": rows}


@router.get("/responses")
async def responses(limit: int = Query(default=100, ge=1, le=500), authorization: Optional[str] = Header(default=None)):
    await agency(authorization)
    return {"items": await sb_select(automations.RESPONSES, order="received_at.desc", limit=limit)}


@router.get("/usage")
async def usage(authorization: Optional[str] = Header(default=None)):
    await agency(authorization)
    return await automations.usage_summary()


@router.post("/process")
async def process(authorization: Optional[str] = Header(default=None)):
    await agency(authorization)
    return {"send_enabled": automations.send_enabled(), **await automations.process_due()}


@router.post("/events/{key}")
async def emit(key: str, body: EmitInput, authorization: Optional[str] = Header(default=None)):
    await agency(authorization)
    try:
        return await automation_triggers.emit(key, client_id=body.client_id, params=body.params, source_id=body.source_id)
    except automations.AutomationError as exc:
        raise _fail(exc) from None


@router.post("/{key}/simulate")
async def simulate(key: str, body: SimulateInput, authorization: Optional[str] = Header(default=None)):
    await agency(authorization)
    try:
        return await automations.simulate(key, params=body.params, phone=_phone(body.phone), button_suffix=body.button_suffix)
    except automations.AutomationError as exc:
        raise _fail(exc) from None


# ---------------------------------------------------------------- equipe e preferências


@router.get("/team")
async def list_team(authorization: Optional[str] = Header(default=None)):
    await agency(authorization)
    return {"items": await sb_select(automations.TEAM, order="name.asc", limit=500)}


@router.post("/team", status_code=201)
async def create_team_member(body: TeamMemberInput, authorization: Optional[str] = Header(default=None)):
    await agency(authorization)
    return await sb_insert(automations.TEAM, {**body.model_dump(), "email": body.email.lower(), "phone": _phone(body.phone)})


@router.patch("/team/{member_id}")
async def update_team_member(member_id: UUID, body: TeamMemberInput, authorization: Optional[str] = Header(default=None)):
    await agency(authorization)
    rows = await sb_update(automations.TEAM, filters={"id": f"eq.{member_id}"},
                           patch={**body.model_dump(), "email": body.email.lower(), "phone": _phone(body.phone)})
    if not rows:
        raise HTTPException(404, "Pessoa não encontrada.")
    return rows[0]


@router.delete("/team/{member_id}", status_code=204)
async def delete_team_member(member_id: UUID, authorization: Optional[str] = Header(default=None)):
    await agency(authorization)
    await sb_delete(automations.TEAM, filters={"id": f"eq.{member_id}"})


@router.put("/prefs/{phone}")
async def set_prefs(phone: str, body: PrefsInput, authorization: Optional[str] = Header(default=None)):
    await agency(authorization)
    digits = _phone(phone)
    patch: Dict[str, Any] = {"phone": digits, **body.model_dump(exclude_unset=True), "updated_at": datetime.now(timezone.utc).isoformat()}
    if body.marketing_opt_in:
        patch["marketing_opt_in_at"] = patch["updated_at"]
    await sb_upsert(automations.PREFS, [patch], on_conflict="phone")
    return await automations.prefs_for(digits)


# ---------------------------------------------------------------- Google Calendar


def _frontend(params: Dict[str, str]) -> str:
    base = (os.getenv("FRONTEND_URL") or "http://localhost:5173").strip().rstrip("/")
    return f"{base}/automacoes?{urlencode(params)}"


@router.get("/google-calendar")
async def calendar_status(authorization: Optional[str] = Header(default=None)):
    await agency(authorization)
    return google_calendar.public_status(await google_calendar.connection())


@router.get("/google-calendar/start")
async def calendar_start(authorization: Optional[str] = Header(default=None)):
    user_id = await agency(authorization)
    try:
        return {"url": await google_calendar.authorization_url(user_id)}
    except (google_calendar.CalendarError, RuntimeError) as exc:
        raise _fail(exc) from None


@router.get("/google-calendar/callback")
async def calendar_callback(code: Optional[str] = Query(default=None), state: Optional[str] = Query(default=None),
                            error: Optional[str] = Query(default=None)):
    if error or not code or not state:
        return RedirectResponse(_frontend({"calendar": "error", "error": "Autorização cancelada no Google."}), status_code=302)
    try:
        await google_calendar.complete_authorization(code, state)
    except Exception as exc:  # noqa: BLE001 — a tela mostra a mensagem pública, nunca o detalhe técnico
        message = str(exc) if isinstance(exc, google_calendar.CalendarError) else "Não foi possível concluir a autorização."
        return RedirectResponse(_frontend({"calendar": "error", "error": message[:160]}), status_code=302)
    return RedirectResponse(_frontend({"calendar": "connected"}), status_code=302)


@router.get("/google-calendar/calendars")
async def calendar_list(authorization: Optional[str] = Header(default=None)):
    await agency(authorization)
    try:
        return {"items": await google_calendar.list_calendars()}
    except google_calendar.CalendarError as exc:
        raise _fail(exc) from None


@router.post("/google-calendar/select")
async def calendar_select(body: CalendarSelect, authorization: Optional[str] = Header(default=None)):
    await agency(authorization)
    try:
        return await google_calendar.select_calendar(body.calendar_id)
    except google_calendar.CalendarError as exc:
        raise _fail(exc) from None


@router.post("/google-calendar/sync")
async def calendar_sync(full: bool = False, authorization: Optional[str] = Header(default=None)):
    await agency(authorization)
    try:
        return await google_calendar.sync(full=full)
    except google_calendar.CalendarError as exc:
        raise _fail(exc) from None


@router.post("/google-calendar/webhook")
async def calendar_webhook(x_goog_channel_id: Optional[str] = Header(default=None), x_goog_channel_token: Optional[str] = Header(default=None),
                           x_goog_resource_state: Optional[str] = Header(default=None)):
    try:
        return await google_calendar.handle_webhook(x_goog_channel_id, x_goog_channel_token, x_goog_resource_state)
    except google_calendar.CalendarError as exc:
        if exc.code == "WEBHOOK_INVALID":
            raise HTTPException(401, "Canal inválido.") from None
        raise HTTPException(502, "Sincronização indisponível.") from None


@router.get("/meetings")
async def all_meetings(start: str = Query(..., max_length=40), end: str = Query(..., max_length=40),
                       authorization: Optional[str] = Header(default=None)):
    await agency(authorization)
    return {"items": await google_calendar.meetings(_iso(start), _iso(end), client_id=None)}


@client_router.get("/meetings")
async def client_meetings(client_id: str, start: str = Query(..., max_length=40), end: str = Query(..., max_length=40),
                          authorization: Optional[str] = Header(default=None)):
    cid = await require_client_read(client_id, authorization)
    return {"items": await google_calendar.meetings(_iso(start), _iso(end), client_id=cid)}


def _iso(value: str) -> str:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
    except ValueError:
        raise HTTPException(422, "Data inválida.") from None
