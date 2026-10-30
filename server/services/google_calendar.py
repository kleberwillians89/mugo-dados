"""Google Calendar corporativo da Mugô → agenda do Mugô Dados e lembretes de reunião.

- OAuth 2.0 com autorização explícita da conta corporativa (somente leitura: calendar.readonly).
  Sincronização em um sentido só (Google → Dados): a agenda do Dados mostra, o Google continua a fonte,
  então não existe evento duplicado por ida e volta.
- Sincronização inicial (30 dias para trás) e incremental por syncToken; 410 = token expirado → ressincroniza.
- Mudanças chegam por webhook (events.watch) e o job periódico cobre o webhook perdido (Render dormindo).
- Deduplicação por (calendar_id, google_event_id).
- Lembretes: chave inclui o horário de início. Evento reagendado gera chave nova e cancela a antiga;
  evento cancelado cancela tudo que ainda não saiu.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

import httpx

from . import automations
from .crypto import decrypt_secret, encrypt_secret
from .google_oauth import GOOGLE_AUTH_URL, GOOGLE_TOKEN_URL, fetch_google_identity, settings as google_settings
from .ig_supabase import sb_get_one_by, sb_select, sb_upsert
from .oauth_state import consume_oauth_state, create_oauth_state

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
CONNECTION = "google_calendar_connection"
EVENTS = "calendar_events"
API = "https://www.googleapis.com/calendar/v3"
SCOPES = ("openid", "email", "https://www.googleapis.com/auth/calendar.readonly")
INITIAL_LOOKBACK_DAYS = 30
WATCH_TTL_SECONDS = 7 * 24 * 3600
MIN_NOTICE = timedelta(hours=1)


class CalendarError(RuntimeError):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def agency_client_id() -> str:
    return (os.getenv("MUGO_AGENCY_CLIENT_ID") or "mugo").strip()


def redirect_uri() -> str:
    uri = (os.getenv("GOOGLE_CALENDAR_REDIRECT_URI") or "").strip()
    if not uri.startswith("https://") and not uri.startswith("http://localhost"):
        raise CalendarError("NOT_CONFIGURED", "Defina GOOGLE_CALENDAR_REDIRECT_URI no backend.")
    return uri


def webhook_url() -> Optional[str]:
    url = (os.getenv("GOOGLE_CALENDAR_WEBHOOK_URL") or "").strip()
    return url if url.startswith("https://") else None


def team_domain() -> Optional[str]:
    return (os.getenv("MUGO_EMAIL_DOMAIN") or "").strip().lower().lstrip("@") or None


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


async def connection() -> Dict[str, Any]:
    return await sb_get_one_by(CONNECTION, filters={"id": "eq.mugo"}) or {"id": "mugo", "status": "desconectado"}


async def _save(patch: Dict[str, Any]) -> None:
    await sb_upsert(CONNECTION, [{"id": "mugo", **patch, "updated_at": _now().isoformat()}], on_conflict="id")


def public_status(conn: Dict[str, Any]) -> Dict[str, Any]:
    return {k: conn.get(k) for k in ("status", "account_email", "calendar_id", "calendar_summary", "last_sync_at",
                                     "last_error", "channel_expires_at")} | {"webhook": bool(conn.get("channel_id"))}


# ---------------------------------------------------------------- OAuth


async def authorization_url(user_id: str) -> str:
    config = google_settings()
    uri = redirect_uri()
    state = await create_oauth_state(provider="google_calendar", user_id=user_id, client_id=agency_client_id(), redirect_uri=uri)
    params = {"client_id": config["client_id"], "redirect_uri": uri, "response_type": "code", "scope": " ".join(SCOPES),
              "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true", "state": state}
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


async def complete_authorization(code: str, state: str) -> Dict[str, Any]:
    session = await consume_oauth_state(state, provider="google_calendar")
    config = google_settings()
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(GOOGLE_TOKEN_URL, data={
            "code": code, "client_id": config["client_id"], "client_secret": config["client_secret"],
            "redirect_uri": str(session.get("redirect_uri") or ""), "grant_type": "authorization_code"})
    if response.status_code >= 400:
        raise CalendarError("TOKEN_EXCHANGE_FAILED", "O Google recusou a autorização.")
    token = response.json()
    granted = str(token.get("scope") or "").split()
    if "https://www.googleapis.com/auth/calendar.readonly" not in granted:
        raise CalendarError("SCOPE_MISSING", "A permissão de leitura da agenda não foi concedida.")
    if not token.get("refresh_token"):
        raise CalendarError("REFRESH_TOKEN_MISSING", "O Google não devolveu acesso permanente. Remova o acesso do app na conta e autorize de novo.")
    identity = await fetch_google_identity(str(token["access_token"]))
    await _save({"account_email": identity.get("email"), "refresh_token_enc": encrypt_secret(token["refresh_token"]),
                 "access_token_enc": encrypt_secret(token["access_token"]),
                 "access_expires_at": (_now() + timedelta(seconds=int(token.get("expires_in") or 3600))).isoformat(),
                 "scopes": granted, "status": "aguardando_calendario", "sync_token": None, "last_error": None,
                 "connected_by": str(session.get("user_id") or "")})
    return {"account_email": identity.get("email")}


async def access_token() -> str:
    conn = await connection()
    if not conn.get("refresh_token_enc"):
        raise CalendarError("NOT_CONNECTED", "Conecte o Google Calendar da Mugô.")
    expires = conn.get("access_expires_at")
    if conn.get("access_token_enc") and expires and datetime.fromisoformat(str(expires).replace("Z", "+00:00")) > _now() + timedelta(minutes=2):
        return decrypt_secret(conn["access_token_enc"])
    config = google_settings()
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(GOOGLE_TOKEN_URL, data={
            "client_id": config["client_id"], "client_secret": config["client_secret"],
            "refresh_token": decrypt_secret(conn["refresh_token_enc"]), "grant_type": "refresh_token"})
    if response.status_code >= 400:
        error = (response.json() if response.content else {}).get("error")
        if error == "invalid_grant":
            await _save({"status": "reautorizar", "last_error": "Autorização revogada ou expirada. Reconecte a conta."})
            raise CalendarError("REAUTH_REQUIRED", "Reconecte o Google Calendar da Mugô.")
        raise CalendarError("TOKEN_REFRESH_FAILED", "Não foi possível renovar o acesso ao Google Calendar.")
    token = response.json()
    await _save({"access_token_enc": encrypt_secret(token["access_token"]),
                 "access_expires_at": (_now() + timedelta(seconds=int(token.get("expires_in") or 3600))).isoformat()})
    return str(token["access_token"])


async def _google(method: str, path: str, *, params: Optional[Dict[str, Any]] = None, json: Any = None) -> httpx.Response:
    token = await access_token()
    async with httpx.AsyncClient(timeout=30) as client:
        return await client.request(method, f"{API}{path}", params=params, json=json, headers={"Authorization": f"Bearer {token}"})


async def list_calendars() -> List[Dict[str, Any]]:
    response = await _google("GET", "/users/me/calendarList", params={"minAccessRole": "reader", "maxResults": 250})
    if response.status_code >= 400:
        raise CalendarError("CALENDAR_LIST_FAILED", "Não foi possível listar as agendas da conta.")
    return [{"id": c.get("id"), "summary": c.get("summaryOverride") or c.get("summary"), "primary": bool(c.get("primary")),
             "timezone": c.get("timeZone")} for c in (response.json() or {}).get("items") or []]


async def select_calendar(calendar_id: str) -> Dict[str, Any]:
    calendars = {c["id"]: c for c in await list_calendars()}
    if calendar_id not in calendars:
        raise CalendarError("CALENDAR_NOT_ALLOWED", "Agenda não pertence à conta autorizada.")
    old = await connection()
    await _save({"calendar_id": calendar_id, "calendar_summary": calendars[calendar_id]["summary"], "sync_token": None,
                 "status": "ativo", "last_error": None})
    if old.get("channel_id") and old.get("calendar_id") != calendar_id:
        await stop_watch(old)
    result = await sync(full=True)
    if webhook_url():
        await start_watch()
    return result


# ---------------------------------------------------------------- classificação


def _event_time(value: Dict[str, Any]) -> Tuple[Optional[datetime], bool]:
    if not value:
        return None, False
    if value.get("dateTime"):
        moment = datetime.fromisoformat(str(value["dateTime"]).replace("Z", "+00:00"))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=ZoneInfo(value.get("timeZone") or "America/Sao_Paulo"))
        return moment.astimezone(timezone.utc), False
    if value.get("date"):
        day = datetime.fromisoformat(str(value["date"])).replace(tzinfo=SAO_PAULO)
        return day.astimezone(timezone.utc), True
    return None, False


def classify(attendees: List[Dict[str, Any]], team_emails: set, contacts_by_email: Dict[str, Dict[str, Any]]) -> Tuple[str, Optional[str]]:
    """interna: só equipe Mugô; cliente: tem contato de exatamente UMA empresa; senão outro (sem lembrete a cliente)."""
    domain = team_domain()
    people = [a for a in attendees if not a.get("resource")]
    client_ids = {contacts_by_email[a["email"]]["client_id"] for a in people if a.get("email") in contacts_by_email}
    if len(client_ids) == 1:
        return "cliente", next(iter(client_ids))
    if len(client_ids) > 1:
        return "outro", None
    is_team = [a.get("email") in team_emails or (domain and str(a.get("email") or "").endswith("@" + domain)) for a in people]
    if len(people) >= 2 and all(is_team):
        return "interna", None
    return "outro", None


def normalize_event(item: Dict[str, Any], calendar_id: str) -> Dict[str, Any]:
    start, all_day = _event_time(item.get("start") or {})
    end, _ = _event_time(item.get("end") or {})
    attendees = [{"email": str(a.get("email") or "").lower(), "name": a.get("displayName"),
                  "response": a.get("responseStatus"), "organizer": bool(a.get("organizer")), "self": bool(a.get("self")),
                  "resource": bool(a.get("resource"))} for a in item.get("attendees") or [] if a.get("email")]
    return {
        "calendar_id": calendar_id, "google_event_id": str(item.get("id")), "status": item.get("status") or "confirmed",
        "summary": (str(item.get("summary") or "")[:300] or None), "start_at": start.isoformat() if start else None,
        "end_at": end.isoformat() if end else None, "all_day": all_day,
        "timezone": (item.get("start") or {}).get("timeZone") or "America/Sao_Paulo",
        "organizer_email": str((item.get("organizer") or {}).get("email") or "").lower() or None,
        "attendees": attendees, "html_link": item.get("htmlLink"), "etag": item.get("etag"),
        "google_updated_at": item.get("updated"),
    }


# ---------------------------------------------------------------- sincronização


async def _directory() -> Tuple[set, Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    team = await sb_select(automations.TEAM, select="id,name,email,phone,active,receives_internal", filters={"active": "eq.true"}, limit=500)
    contacts = await sb_select(automations.CONTACTS, select="id,client_id,name,phone,email,active",
                               filters={"active": "eq.true", "email": "not.is.null"}, limit=2000)
    return ({t["email"] for t in team}, {c["email"]: c for c in contacts}, {t["email"]: t for t in team})


async def sync(*, full: bool = False) -> Dict[str, Any]:
    conn = await connection()
    calendar_id = conn.get("calendar_id")
    if not calendar_id:
        raise CalendarError("CALENDAR_NOT_SELECTED", "Escolha a agenda da Mugô.")
    params: Dict[str, Any] = {"singleEvents": "true", "showDeleted": "true", "maxResults": 250}
    if conn.get("sync_token") and not full:
        params["syncToken"] = conn["sync_token"]
    else:
        params["timeMin"] = (_now() - timedelta(days=INITIAL_LOOKBACK_DAYS)).isoformat()
    team_emails, contacts_by_email, team_by_email = await _directory()
    changed, next_token = 0, None
    path = f"/calendars/{quote(calendar_id, safe='')}/events"
    for _ in range(40):
        response = await _google("GET", path, params=params)
        if response.status_code == 410:
            await _save({"sync_token": None})
            return await sync(full=True)
        if response.status_code >= 400:
            await _save({"status": "erro", "last_error": f"Sincronização falhou (HTTP {response.status_code})."})
            raise CalendarError("SYNC_FAILED", "O Google não devolveu os eventos.")
        data = response.json() or {}
        for item in data.get("items") or []:
            row = normalize_event(item, calendar_id)
            row["kind"], row["client_id"] = classify(row["attendees"], team_emails, contacts_by_email)
            await sb_upsert(EVENTS, [row], on_conflict="calendar_id,google_event_id")
            await schedule_reminders(row, contacts_by_email, team_by_email)
            changed += 1
        if data.get("nextPageToken"):
            params = {k: v for k, v in params.items() if k in {"singleEvents", "showDeleted", "maxResults", "syncToken", "timeMin"}}
            params["pageToken"] = data["nextPageToken"]
            continue
        next_token = data.get("nextSyncToken")
        break
    await _save({"sync_token": next_token, "last_sync_at": _now().isoformat(), "status": "ativo", "last_error": None})
    return {"changed": changed, "full": full or not conn.get("sync_token")}


# ---------------------------------------------------------------- lembretes


def _local(moment: datetime) -> datetime:
    return moment.astimezone(SAO_PAULO)


def _title(summary: Optional[str]) -> str:
    return re.sub(r"\s+", " ", str(summary or "Reunião")).strip()[:60] or "Reunião"


def _reminder_time(start: datetime, lead_minutes: int) -> Optional[datetime]:
    """24h antes; evento marcado em cima da hora recebe o lembrete já, se ainda faltar pelo menos 1h."""
    now = _now()
    if start - now < MIN_NOTICE:
        return None
    return max(start - timedelta(minutes=lead_minutes), now)


async def _client_brand(client_id: str) -> str:
    from .studio_approvals import _client_name
    return await _client_name(client_id)


async def schedule_reminders(event: Dict[str, Any], contacts_by_email: Dict[str, Dict[str, Any]],
                             team_by_email: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
    source_id = event["google_event_id"]
    if event["status"] == "cancelled" or not event.get("start_at") or event.get("all_day"):
        reason = "evento cancelado" if event["status"] == "cancelled" else "evento sem horário"
        return {"cancelled": await automations.cancel_pending("calendar_event", source_id, reason=reason)}
    definitions = await automations.load_definitions()
    start = datetime.fromisoformat(str(event["start_at"]).replace("Z", "+00:00"))
    local = _local(start)
    title = _title(event.get("summary"))
    keep: List[str] = []
    queued = 0
    attending = [a for a in event["attendees"] if a.get("response") != "declined"]

    async def put(definition: Dict[str, Any], *, client_id: Optional[str], recipient: Dict[str, Any], params: Dict[str, str],
                  when: datetime, source_type: str, extra: str) -> None:
        nonlocal queued
        key = automations.idempotency_key(definition["key"], client_id or "-", re.sub(r"\D", "", recipient["phone"]), source_type,
                                          source_id, start.isoformat(), extra)
        if source_type == "calendar_event":
            keep.append(key)
        row = await automations.enqueue(definition, client_id=client_id, recipient=recipient, params=params, source_type=source_type,
                                        source_id=source_id, scheduled_for=when, key_parts=(start.isoformat(), extra))
        queued += 1 if row else 0

    if event["kind"] == "interna":
        definition = definitions.get("reuniao_interna")
        if definition and definition.get("automation_enabled") and definition["owner"] == "dados":
            when = _reminder_time(start, int(definition.get("lead_minutes") or 1440))
            for attendee in attending:
                member = team_by_email.get(attendee["email"])
                if when and member and member.get("phone") and member.get("receives_internal"):
                    await put(definition, client_id=None, recipient={**member, "team_member": True},
                              params={"nome": str(member["name"]).split()[0], "titulo": title, "data": local.strftime("%d/%m"),
                                      "hora": local.strftime("%H:%M")}, when=when, source_type="calendar_event", extra="interna")
    elif event["kind"] == "cliente" and event.get("client_id"):
        client_id = event["client_id"]
        brand = await _client_brand(client_id)
        reminder = definitions.get("reuniao_lembrete")
        confirmed = definitions.get("agendamento_confirmado")
        for attendee in attending:
            contact = contacts_by_email.get(attendee["email"])
            if not contact or contact.get("client_id") != client_id:
                continue
            first = str(contact["name"]).split()[0]
            recipient = {**contact, "client_id": client_id}
            if reminder and reminder.get("automation_enabled") and reminder["owner"] == "dados":
                when = _reminder_time(start, int(reminder.get("lead_minutes") or 1440))
                if when:
                    await put(reminder, client_id=client_id, recipient=recipient, when=when, source_type="calendar_event", extra="cliente",
                              params={"nome": first, "marca": brand, "titulo": title, "data": local.strftime("%d/%m"), "hora": local.strftime("%H:%M")})
            # "Confirmado" só quando o próprio participante aceitou no Google (confirmação real).
            if (confirmed and confirmed.get("automation_enabled") and confirmed["owner"] == "dados"
                    and attendee.get("response") == "accepted" and start > _now()):
                await put(confirmed, client_id=client_id, recipient=recipient, when=_now(), source_type="calendar_confirmation",
                          extra="confirmado", params={"nome": first, "dia": str(local.day), "hora": local.strftime("%H:%M")})
    cancelled = await automations.cancel_pending("calendar_event", source_id, keep_keys=keep, reason="evento alterado ou reagendado")
    return {"queued": queued, "cancelled": cancelled}


# ---------------------------------------------------------------- webhook (events.watch)


async def start_watch() -> Dict[str, Any]:
    url = webhook_url()
    if not url:
        raise CalendarError("WEBHOOK_NOT_CONFIGURED", "Defina GOOGLE_CALENDAR_WEBHOOK_URL (https).")
    conn = await connection()
    channel_id, channel_token = str(uuid.uuid4()), secrets.token_urlsafe(32)
    response = await _google("POST", f"/calendars/{quote(conn['calendar_id'], safe='')}/events/watch", json={
        "id": channel_id, "type": "web_hook", "address": url, "token": channel_token, "params": {"ttl": str(WATCH_TTL_SECONDS)}})
    if response.status_code >= 400:
        raise CalendarError("WATCH_FAILED", "O Google recusou o webhook (o domínio precisa estar verificado).")
    data = response.json() or {}
    expires = datetime.fromtimestamp(int(data.get("expiration", 0)) / 1000, tz=timezone.utc) if data.get("expiration") else _now() + timedelta(seconds=WATCH_TTL_SECONDS)
    if conn.get("channel_id"):
        await stop_watch(conn)
    await _save({"channel_id": channel_id, "channel_resource_id": data.get("resourceId"), "channel_token_hash": _hash(channel_token),
                 "channel_expires_at": expires.isoformat()})
    return {"channel_expires_at": expires.isoformat()}


async def stop_watch(conn: Dict[str, Any]) -> None:
    if not conn.get("channel_id") or not conn.get("channel_resource_id"):
        return
    try:
        await _google("POST", "/channels/stop", json={"id": conn["channel_id"], "resourceId": conn["channel_resource_id"]})
    except Exception as exc:  # canal antigo expira sozinho; não bloqueia a renovação
        print(f"[google_calendar] stop_watch_failed {type(exc).__name__}")


async def renew_watch_if_needed() -> Dict[str, Any]:
    conn = await connection()
    if conn.get("status") != "ativo" or not webhook_url():
        return {"renewed": False, "reason": "inactive_or_no_webhook"}
    expires = conn.get("channel_expires_at")
    if expires and datetime.fromisoformat(str(expires).replace("Z", "+00:00")) > _now() + timedelta(hours=24):
        return {"renewed": False, "reason": "still_valid"}
    return {"renewed": True, **await start_watch()}


async def handle_webhook(channel_id: Optional[str], channel_token: Optional[str], resource_state: Optional[str]) -> Dict[str, Any]:
    conn = await connection()
    valid = (bool(channel_id) and channel_id == conn.get("channel_id") and bool(conn.get("channel_token_hash"))
             and hmac.compare_digest(_hash(channel_token or ""), str(conn["channel_token_hash"])))
    if not valid:
        raise CalendarError("WEBHOOK_INVALID")
    if resource_state == "sync":
        return {"ok": True, "state": "sync"}
    return {"ok": True, **await sync()}


# ---------------------------------------------------------------- leitura para a agenda


async def meetings(start: str, end: str, *, client_id: Optional[str]) -> List[Dict[str, Any]]:
    """Agência: todas as reuniões. Cliente: só as reuniões da própria empresa, sem lista de participantes."""
    filters = {"start_at": f"gte.{start}", "and": f"(start_at.lt.{end})", "status": "neq.cancelled"}
    if client_id:
        filters["client_id"] = f"eq.{client_id}"
        filters["kind"] = "eq.cliente"
    rows = await sb_select(EVENTS, select="google_event_id,summary,start_at,end_at,all_day,kind,client_id,html_link,attendees,status",
                           filters=filters, order="start_at.asc", limit=500)
    if client_id:
        return [{k: r.get(k) for k in ("google_event_id", "summary", "start_at", "end_at", "all_day", "kind")}
                for r in rows if r.get("client_id") == client_id]
    return rows
