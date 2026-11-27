"""WhatsApp nativo do MUGOVERSO: números ligados ao app da Mugô na Meta.

Cadastro (só agência): recebe waba_id, phone_number_id e o token de acesso; confere na Meta que o número
existe, que pertence àquela WABA e que o token funciona; assina o app da Mugô na WABA (webhook) e só então
grava. O token fica só no banco (service role) e nunca volta para a tela.

Leitura: mesmo contrato das outras fontes (`whatsapp_sources`), a partir das tabelas que a função
`whatsapp-webhook` preenche. O telefone nunca sai daqui inteiro: só mascarado e a chave `phone_key`.
"""
from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from .ig_supabase import sb_insert, sb_select, sb_update, sb_upsert

GRAPH_TIMEOUT = 20
_DIGITS = re.compile(r"^[0-9]{5,30}$")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
NUMBER_PUBLIC_FIELDS = "id,client_id,waba_id,phone_number_id,meta_app_id,display_phone_number,verified_name,status,subscribed_at,created_at"


class WhatsAppNativeError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(code)
        self.code = code
        self.message = message


def _graph_base() -> str:
    version = (os.getenv("WHATSAPP_GRAPH_VERSION") or "v23.0").strip()
    if not re.fullmatch(r"v[0-9]{2}\.[0-9]", version):
        version = "v23.0"
    return f"https://graph.facebook.com/{version}"


def mask_phone(value: Any) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    return f"•••• {digits[-4:]}" if len(digits) >= 4 else "••••"


def _safe_meta_operation_diagnostic(error: Dict[str, Any]) -> tuple[str, str]:
    """Only expose an allowlisted interpretation and validated Meta trace ID.

    Graph error.message / error_data can include account, phone, OTP and other PII:
    NEVER return or log these fields verbatim.
    """
    detail = str(error.get("message") or "").lower()
    if "unsupported post request" in detail or "does not support this operation" in detail:
        reason = "operacao_nao_suportada"
    elif "permission" in detail or "access token" in detail or "authorization" in detail:
        reason = "permissao_ou_acesso"
    elif "locale" in detail or "language" in detail:
        reason = "idioma_ou_locale"
    elif "parameter" in detail or "parametro" in detail or "param\u00e2metro" in detail:
        reason = "parametro_invalido"
    elif "rate limit" in detail or "too many" in detail:
        reason = "limite_de_tentativas"
    elif "verification" in detail or "verified" in detail:
        reason = "estado_de_verificacao"
    else:
        reason = "indeterminado"
    trace = str(error.get("fbtrace_id") or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,128}", trace):
        trace = ""
    return reason, trace


async def _graph(method: str, path: str, token: str, params: Optional[Dict[str, Any]] = None,
                 json_body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=GRAPH_TIMEOUT) as client:
            resp = await client.request(method, f"{_graph_base()}/{path}", params=params, json=json_body,
                                        headers={"Authorization": f"Bearer {token}"})
        body = resp.json() if resp.content else {}
    except (httpx.HTTPError, ValueError):
        raise WhatsAppNativeError("META_UNREACHABLE", "A Meta não respondeu agora. Tente de novo em instantes.") from None
    if resp.status_code >= 400 or (isinstance(body, dict) and body.get("error")):
        error = (body or {}).get("error") or {}
        code = str(error.get("code") or resp.status_code)
        subcode = str(error.get("error_subcode") or "")
        operation = path.rsplit("/", 1)[-1]
        # Classifica a mensagem em categorias fixas; nunca registra texto bruto, PIN, OTP ou token.
        reason, trace = _safe_meta_operation_diagnostic(error)
        print(
            f"[whatsapp_native] graph operation={operation} status={resp.status_code} "
            f"code={code} subcode={subcode or '-'} reason={reason} trace={trace or '-'}"
        )
        if operation in {"request_code", "verify_code", "register"}:
            diagnostic = (
                f"(Meta #{code}" + (f", subcódigo {subcode}" if subcode else "") +
                f"; motivo={reason}" + (f"; trace={trace}" if trace else "") + ")"
            )
            if code in {"190", "102"} or resp.status_code == 401:
                raise WhatsAppNativeError("TOKEN_INVALID", f"Credencial Meta inválida ou expirada {diagnostic}.")
            if code in {"10", "200", "294"} or resp.status_code == 403:
                raise WhatsAppNativeError("PERMISSION", f"Permissão insuficiente para {operation} {diagnostic}.")
            if code in {"100", "803"} or resp.status_code == 404:
                raise WhatsAppNativeError(
                    "META_REQUEST_INVALID",
                    f"A Meta recusou a operação {operation} {diagnostic}. Pode ser parâmetro, recurso indisponível ou ID; "
                    "não conclua que o número está errado. Não repita o pedido antes de analisar o código.",
                )
            raise WhatsAppNativeError(
                "META_FAILED", f"A Meta recusou a operação {operation} {diagnostic}. "
                "Consulte o código oficial do erro antes de tentar novamente.",
            )
        if code in {"190", "102"} or resp.status_code == 401:
            raise WhatsAppNativeError("TOKEN_INVALID", "A Meta recusou o token. Gere um token do usuário do sistema com acesso a esta WABA.")
        if code in {"100", "803"} or resp.status_code == 404:
            raise WhatsAppNativeError("NOT_FOUND", "A Meta não encontrou esse ID. Confira o ID da WABA e o ID do número.")
        if code in {"131008", "131009"} and ((json_body or {}).get("interactive") or {}).get("type") == "cta_url":
            raise WhatsAppNativeError("CTA_REJECTED", "A Meta recusou o botão de link.")
        if code == "131047":
            raise WhatsAppNativeError("OUTSIDE_WINDOW", "Passaram 24 horas desde a última mensagem da pessoa: o WhatsApp só aceita resposta livre dentro desse prazo.")
        if code in {"10", "200", "294"} or resp.status_code == 403:
            raise WhatsAppNativeError("PERMISSION", "O token não tem permissão nesta WABA (whatsapp_business_management e whatsapp_business_messaging).")
        raise WhatsAppNativeError("META_FAILED", "A Meta recusou o pedido. Tente de novo ou confira as permissões.")
    return body if isinstance(body, dict) else {}


def public_number(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row.get("id"),
        "waba_id": row.get("waba_id"),
        "phone_number_id": row.get("phone_number_id"),
        "meta_app_id": row.get("meta_app_id"),
        "display_phone_number": row.get("display_phone_number"),
        "verified_name": row.get("verified_name"),
        "status": row.get("status"),
        "subscribed_at": row.get("subscribed_at"),
        "created_at": row.get("created_at"),
    }


async def list_numbers(client_id: str) -> List[Dict[str, Any]]:
    rows = await sb_select("whatsapp_numbers", select=NUMBER_PUBLIC_FIELDS,
                           filters={"client_id": f"eq.{client_id}"}, order="created_at.asc", limit=20)
    return [public_number(r) for r in rows]


async def active_number_ids(client_id: str) -> List[str]:
    rows = await sb_select("whatsapp_numbers", select="id",
                           filters={"client_id": f"eq.{client_id}", "status": "eq.active"}, limit=20)
    return [str(r["id"]) for r in rows if r.get("id")]


async def register_number(client_id: str, *, waba_id: str, phone_number_id: str, access_token: str,
                          user_id: Optional[str] = None, meta_app_id: Optional[str] = None) -> Dict[str, Any]:
    waba_id, phone_number_id, token = str(waba_id).strip(), str(phone_number_id).strip(), str(access_token).strip()
    meta_app_id = str(meta_app_id or "").strip() or None
    if meta_app_id and not _DIGITS.match(meta_app_id):
        raise WhatsAppNativeError("META_APP_ID_INVALID", "ID do aplicativo Meta inválido.")
    if not _DIGITS.match(waba_id) or not _DIGITS.match(phone_number_id):
        raise WhatsAppNativeError("IDS_INVALID", "O ID da WABA e o ID do número são só números (copie do gerenciador da Meta).")
    if not 20 <= len(token) <= 2000 or re.search(r"\s", token):
        raise WhatsAppNativeError("TOKEN_INVALID", "Cole o token de acesso inteiro, sem espaços.")

    existing = await sb_select("whatsapp_numbers", select="id,client_id,status",
                               filters={"phone_number_id": f"eq.{phone_number_id}"}, limit=1)
    # Um número pertence a uma empresa só, para sempre: as conversas antigas ficam presas a ele. Mesmo
    # desligado, ele não pode ir para outra empresa (as conversas de uma apareceriam na outra).
    if existing and str(existing[0].get("client_id")) != client_id:
        raise WhatsAppNativeError("NUMBER_IN_USE", "Este número já foi ligado a outra empresa do MUGOVERSO.")

    # Identidade do aplicativo que emitiu o token: impede vincular um numero Roove
    # ao callback de outro app e perder os eventos.
    if meta_app_id:
        token_app = await _graph("GET", "app", token, {"fields": "id"})
        if str(token_app.get("id") or "") != meta_app_id:
            raise WhatsAppNativeError("META_APP_MISMATCH", "O token pertence a outro aplicativo Meta.")
    phone = await _graph("GET", phone_number_id, token, {"fields": "display_phone_number,verified_name"})
    numbers = await _graph("GET", f"{waba_id}/phone_numbers", token, {"fields": "id", "limit": 100})
    if phone_number_id not in {str(n.get("id")) for n in numbers.get("data") or []}:
        raise WhatsAppNativeError("NOT_IN_WABA", "Este número não pertence a essa WABA.")
    subscribed = await _graph("POST", f"{waba_id}/subscribed_apps", token)
    if subscribed.get("success") is False:
        raise WhatsAppNativeError("SUBSCRIBE_FAILED", "A Meta não assinou o webhook nesta WABA.")

    now = datetime.now(timezone.utc).isoformat()
    row = {
        "client_id": client_id, "waba_id": waba_id, "phone_number_id": phone_number_id,
        "meta_app_id": meta_app_id,
        "display_phone_number": str(phone.get("display_phone_number") or "")[:40] or None,
        "verified_name": str(phone.get("verified_name") or "")[:120] or None,
        "access_token": token, "status": "active", "subscribed_at": now, "updated_at": now,
    }
    if existing:
        saved = await sb_update("whatsapp_numbers", filters={"id": f"eq.{existing[0]['id']}"}, patch=row)
        saved_row = saved[0] if saved else {**row, "id": existing[0]["id"]}
    else:
        saved_row = await sb_insert("whatsapp_numbers", {**row, "created_by": user_id}) or row
    print(f"[whatsapp_native] number_registered client_id={client_id} number={mask_phone(row['display_phone_number'])}")
    return public_number(saved_row)


# Registro operacional do número secundário ROOVE: opt-in explícito do administrador.
# Nunca executar no cadastro, na leitura de status, em cron ou em resposta a webhook.
ROOVE_REGISTRATION = {
    "client_id": "roove",
    "waba_id": "1491824329400600",
    "phone_number_id": "1063683626819387",
    "meta_app_id": "1161210926623351",
}
REGISTERABLE_STATUSES = {"OFFLINE", "DISCONNECTED", "PENDING"}
_CONNECTED_STATUSES = {"CONNECTED"}


async def _roove_registration_number(client_id: str, number_id: str) -> Dict[str, Any]:
    """Credencial somente server-side, valida tenant, número e Meta App exatos."""
    if client_id != ROOVE_REGISTRATION["client_id"] or not _UUID.fullmatch(str(number_id)):
        raise WhatsAppNativeError("NOT_FOUND", "Este registro está disponível somente para o número secundário da Roove.")
    rows = await sb_select(
        "whatsapp_numbers",
        select="id,client_id,waba_id,phone_number_id,meta_app_id,status,access_token",
        filters={"id": f"eq.{number_id}", "client_id": f"eq.{client_id}", "status": "eq.active"},
        limit=1,
    )
    if not rows:
        raise WhatsAppNativeError("NOT_FOUND", "Número da Roove não encontrado ou desconectado.")
    number = rows[0]
    if str(number.get("id") or "") != str(number_id):
        raise WhatsAppNativeError("NOT_FOUND", "Número da Roove não encontrado.")
    for field in ("client_id", "waba_id", "phone_number_id", "meta_app_id"):
        if str(number.get(field) or "") != ROOVE_REGISTRATION[field]:
            raise WhatsAppNativeError("NOT_FOUND", "Identidade do número não corresponde à Roove.")
    if not str(number.get("access_token") or "").strip():
        raise WhatsAppNativeError("TOKEN_INVALID", "A credencial deste número não está disponível.")
    return number


async def _meta_roove_status(number: Dict[str, Any]) -> Dict[str, Any]:
    # Consulta na WABA (não confiar em public.whatsapp_numbers.status, que é local).
    payload = await _graph(
        "GET", f"{number['waba_id']}/phone_numbers", number["access_token"],
        params={"fields": "id,display_phone_number,status,code_verification_status", "limit": 100},
    )
    matched = next(
        (item for item in payload.get("data") or []
         if str(item.get("id") or "") == str(number["phone_number_id"])), None,
    )
    if not matched:
        raise WhatsAppNativeError("NOT_IN_WABA", "A Meta não retornou este número na WABA da Roove.")
    meta_status = str(matched.get("status") or "").upper().strip()
    if not meta_status:
        raise WhatsAppNativeError("STATUS_UNKNOWN", "A Meta não informou o status de registro. Não é seguro registrar.")
    return {
        "phone_number_id": str(number["phone_number_id"]),
        "display_phone_number": str(matched.get("display_phone_number") or ""),
        "status": meta_status,
        "code_verification_status": str(matched.get("code_verification_status") or ""),
        "registered": meta_status in _CONNECTED_STATUSES,
        "can_register": meta_status in REGISTERABLE_STATUSES and str(matched.get("code_verification_status") or "").upper() == "VERIFIED",
    }


async def get_roove_registration_status(client_id: str, number_id: str) -> Dict[str, Any]:
    """GET: somente leitura, não registra, não expõe PIN ou token."""
    number = await _roove_registration_number(client_id, number_id)
    status = await _meta_roove_status(number)
    return {**status, "requires_confirmation": True, "registered_by_this_request": False}


async def request_roove_verification_code(client_id: str, number_id: str, *,
                                          method: str, confirmed: bool) -> Dict[str, Any]:
    """Solicita um OTP somente ao telefone secundário Roove, após consentimento explícito."""
    if confirmed is not True:
        raise WhatsAppNativeError("CONFIRMATION_REQUIRED", "Confirme o envio de código ao número secundário da Roove.")
    if method not in ("SMS", "VOICE"):
        raise WhatsAppNativeError("METHOD_INVALID", "Escolha SMS ou ligação.")
    number = await _roove_registration_number(client_id, number_id)
    state = await _meta_roove_status(number)
    verification = state["code_verification_status"].upper()
    if state["registered"] or verification == "VERIFIED":
        raise WhatsAppNativeError("ALREADY_VERIFIED", "A Meta já informa verificação concluída. Não solicite outro código.")
    if verification not in ("EXPIRED", "NOT_VERIFIED", "PENDING", "UNVERIFIED"):
        raise WhatsAppNativeError("REGISTRATION_UNSAFE", "Estado de verificação desconhecido. Solicitação bloqueada.")
    response = await _graph(
        "POST", f"{number['phone_number_id']}/request_code", number["access_token"],
        json_body={"code_method": method, "locale": "pt_BR"},
    )
    if response.get("success") is not True:
        raise WhatsAppNativeError("META_FAILED", "A Meta não confirmou o envio do código.")
    return {"requested": True, "method": method, "phone_number_id": number["phone_number_id"]}


async def verify_roove_verification_code(client_id: str, number_id: str, *,
                                         code: str, confirmed: bool) -> Dict[str, Any]:
    """Valida OTP em chamada explícita, nunca persiste nem retorna o código."""
    if confirmed is not True:
        raise WhatsAppNativeError("CONFIRMATION_REQUIRED", "Confirme a validação do código recebido.")
    if not isinstance(code, str) or not re.fullmatch(r"[0-9]{4,8}", code):
        raise WhatsAppNativeError("CODE_INVALID", "O código recebido deve conter de 4 a 8 dígitos.")
    number = await _roove_registration_number(client_id, number_id)
    state = await _meta_roove_status(number)
    if state["registered"] or state["code_verification_status"].upper() == "VERIFIED":
        return {"verified": True, "already_verified": True}
    if state["code_verification_status"].upper() not in ("EXPIRED", "NOT_VERIFIED", "PENDING", "UNVERIFIED"):
        raise WhatsAppNativeError("REGISTRATION_UNSAFE", "Estado de verificação desconhecido. Validação bloqueada.")
    result = await _graph(
        "POST", f"{number['phone_number_id']}/verify_code", number["access_token"],
        json_body={"code": code},
    )
    if result.get("success") is not True:
        raise WhatsAppNativeError("META_FAILED", "A Meta não confirmou a verificação do telefone.")
    return {"verified": True, "phone_number_id": number["phone_number_id"]}


async def register_roove_cloud_number(client_id: str, number_id: str, *,
                                      pin: str, confirmed: bool) -> Dict[str, Any]:
    """POST: registro somente após confirmação explícita e PIN válido, sem armazenamento de PIN."""
    if confirmed is not True:
        raise WhatsAppNativeError("CONFIRMATION_REQUIRED", "Confirme explicitamente o registro do número da Roove.")
    if not isinstance(pin, str) or not re.fullmatch(r"[0-9]{6}", pin):
        raise WhatsAppNativeError("PIN_INVALID", "O PIN deve conter exatamente seis dígitos.")
    number = await _roove_registration_number(client_id, number_id)
    status = await _meta_roove_status(number)
    if status["registered"]:
        return {**status, "registered_by_this_request": False, "already_connected": True}
    if status["status"] not in REGISTERABLE_STATUSES:
        raise WhatsAppNativeError("REGISTRATION_UNSAFE", "Estado Meta não permite registro automático.")
    if status["code_verification_status"].upper() != "VERIFIED":
        raise WhatsAppNativeError("VERIFICATION_REQUIRED", "Verifique o número por SMS ou ligação antes de registrar.")
    if not status["can_register"]:
        raise WhatsAppNativeError(
            "REGISTRATION_UNSAFE",
            f"Estado Meta {status['status']}: registro automático bloqueado para proteger o número.",
        )
    # Única operação de mutação: nunca logar PIN/token nem persistir segredo.
    result = await _graph(
        "POST", f"{number['phone_number_id']}/register", number["access_token"],
        json_body={"messaging_product": "whatsapp", "pin": pin},
    )
    if result.get("success") is not True:
        raise WhatsAppNativeError("META_FAILED", "A Meta não confirmou o registro do número.")
    return {
        "phone_number_id": number["phone_number_id"],
        "registration_requested": True,
        "registered_by_this_request": True,
        "note": "A Meta confirmou o registro. Atualize o status para verificar CONNECTED.",
    }


async def disconnect_number(client_id: str, number_id: str) -> bool:
    if not _UUID.match(str(number_id)):
        return False
    rows = await sb_update("whatsapp_numbers", filters={"id": f"eq.{number_id}", "client_id": f"eq.{client_id}"},
                           patch={"status": "disconnected", "updated_at": datetime.now(timezone.utc).isoformat()})
    return bool(rows)


# ---------------------------------------------------------------- leitura (contrato de whatsapp_sources)

def _in_list(ids: List[str]) -> str:
    return f"in.({','.join(ids)})"


async def _touches(client_id: str, thread_ids: List[str], *, first: bool) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for offset in range(0, len(thread_ids), 80):
        part = thread_ids[offset: offset + 80]
        rows = await sb_select("whatsapp_origin_touches", select="thread_id,source,ad_id,headline,entry_code,occurred_at",
                               filters={"client_id": f"eq.{client_id}", "thread_id": _in_list(part)},
                               order=f"occurred_at.{'asc' if first else 'desc'}", limit=5000)
        for row in rows:
            out.setdefault(str(row["thread_id"]), row)
    return out


def _origin(touch: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    touch = touch or {}
    return {"source": touch.get("source"), "ad_id": touch.get("ad_id"),
            "ad_headline": (str(touch.get("headline") or "")[:160] or None),
            "entry_code": touch.get("entry_code"), "at": touch.get("occurred_at")}


async def leads(client_id: str, start: str, end: str) -> Dict[str, Any]:
    if not await active_number_ids(client_id):
        return {"available": True, "connected": False, "leads": [], "truncated": False}
    lo = (datetime.fromisoformat(start[:10]) - timedelta(days=1)).date().isoformat()
    hi = (datetime.fromisoformat(end[:10]) + timedelta(days=2)).date().isoformat()
    rows: List[Dict[str, Any]] = []
    truncated = False
    for offset in range(0, 5000, 1000):
        page = await sb_select("whatsapp_threads", select="id,phone_key,first_seen_at",
                               filters={"client_id": f"eq.{client_id}", "and": f"(first_seen_at.gte.{lo},first_seen_at.lt.{hi})"},
                               order="first_seen_at.asc,id.asc", limit=1000, offset=offset)
        rows.extend(page)
        if len(page) < 1000:
            break
        truncated = offset + 1000 >= 5000
    touches = await _touches(client_id, [str(r["id"]) for r in rows], first=True)
    return {"available": True, "connected": True, "truncated": truncated,
            "leads": [{"phone_key": r["phone_key"], "first_seen_at": r["first_seen_at"], "origin": _origin(touches.get(str(r["id"])))}
                      for r in rows]}


def _paused(row: Dict[str, Any]) -> bool:
    until = row.get("ai_paused_until")
    try:
        return bool(until) and datetime.fromisoformat(str(until).replace("Z", "+00:00")) > datetime.now(timezone.utc)
    except ValueError:
        return False


def _attendance(mode: str, row: Dict[str, Any]) -> str:
    """'bot' = a IA responde sozinha esta conversa; 'suggest' = a IA sugere; 'human' = equipe."""
    if mode == "auto" and not _paused(row):
        return "bot"
    if mode == "suggest" and not _paused(row):
        return "suggest"
    return "human"


def _insight(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not row.get("ai_stage"):
        return None
    return {"stage": row["ai_stage"], "interests": row.get("ai_interests") or [], "objections": row.get("ai_objections") or [],
            "next_step": row.get("ai_next_step"), "summary": row.get("ai_summary"), "updated_at": row.get("ai_updated_at")}


async def conversations(client_id: str, limit: int = 60) -> Dict[str, Any]:
    if not await active_number_ids(client_id):
        return {"available": True, "connected": False, "conversations": []}
    base_fields = "id,wa_id,phone_key,profile_name,first_seen_at,last_message_at,last_inbound_at,last_preview,last_direction,unread_count"
    ai_fields = ",ai_paused_until,ai_handoff_reason,ai_stage,ai_interests,ai_objections,ai_summary,ai_next_step,ai_updated_at,ai_suggestion"
    query = {"filters": {"client_id": f"eq.{client_id}"}, "order": "last_message_at.desc", "limit": max(1, min(int(limit), 200))}
    try:
        fields = base_fields + ai_fields + ",has_campaign"
        rows = await sb_select("whatsapp_threads", select=fields, **{
            **query, "filters": {**query["filters"], "or": "(has_campaign.eq.false,last_inbound_at.not.is.null)"},
        })
        campaign_rows = await sb_select("whatsapp_threads", select=fields, **{
            **query, "filters": {**query["filters"], "has_campaign": "eq.true"},
        })
        seen = {r["id"] for r in rows}
        rows.extend(r for r in campaign_rows if r["id"] not in seen)
        rows.sort(key=lambda r: r.get("last_message_at") or "", reverse=True)
    except Exception:  # noqa: BLE001 — preserve inbox during migration rollout
        try:
            rows = await sb_select("whatsapp_threads", select=base_fields + ai_fields, **query)
        except Exception:  # noqa: BLE001
            rows = await sb_select("whatsapp_threads", select=base_fields, **query)
    ai_mode = "off"
    try:
        from .whatsapp_ai import get_settings as ai_settings
        ai_mode = (await ai_settings(client_id))["mode"]
    except Exception:  # noqa: BLE001
        pass
    touches = await _touches(client_id, [str(r["id"]) for r in rows], first=False)
    out = []
    for r in rows:
        inbound = r.get("last_inbound_at")
        window = (datetime.fromisoformat(str(inbound).replace("Z", "+00:00")) + timedelta(hours=24)).isoformat() if inbound else None
        out.append({
            "id": r["id"], "status": None, "has_campaign": bool(r.get("has_campaign")), "attendance_mode": _attendance(ai_mode, r), "unread_count": r.get("unread_count") or 0,
            "last_message_at": r.get("last_message_at"), "service_window_expires_at": window,
            "contact": {"name": (r.get("profile_name") or None), "phone_masked": mask_phone(r.get("wa_id")),
                        "phone_key": r.get("phone_key"), "first_seen_at": r.get("first_seen_at")},
            "origin": _origin(touches.get(str(r["id"]))),
            "last_message": {"direction": r.get("last_direction") or "in", "at": r.get("last_message_at"),
                             "text": str(r.get("last_preview") or "")[:160]} if r.get("last_preview") else None,
            "insight": _insight(r), "ai_suggestion": r.get("ai_suggestion") or None,
            "ai_handoff_reason": r.get("ai_handoff_reason") if _paused(r) else None,
        })
    return {"available": True, "connected": True, "conversations": out}


async def messages(client_id: str, thread_id: str, limit: int = 100) -> Dict[str, Any]:
    if not _UUID.match(str(thread_id)):
        return {"available": True, "messages": [], "found": False}
    thread = await sb_select("whatsapp_threads", select="id", filters={"id": f"eq.{thread_id}", "client_id": f"eq.{client_id}"}, limit=1)
    if not thread:
        return {"available": True, "messages": [], "found": False}
    query = {"filters": {"thread_id": f"eq.{thread_id}", "client_id": f"eq.{client_id}"},
             "order": "sent_at.desc", "limit": max(1, min(int(limit), 300))}
    fields = "id,direction,type,text,status,error_code,sent_at,read_at"
    try:
        rows = await sb_select("whatsapp_messages", select=fields + ",by_ai,payload", **query)
    except Exception:  # noqa: BLE001 — migration 000131 ainda não aplicada
        rows = await sb_select("whatsapp_messages", select=fields, **query)
    out = [{"id": r["id"], "direction": r["direction"], "type": r.get("type") or "text", "status": r.get("status"),
            "text": r.get("text"), "template_name": None, "at": r.get("sent_at"), "read_at": r.get("read_at"),
            "failed": r.get("status") == "failed", "error_code": r.get("error_code"),
            "by_ai": bool(r.get("by_ai")), "payload": r.get("payload") or None} for r in reversed(rows)]
    return {"available": True, "messages": out, "found": True}


async def send_text(client_id: str, thread_id: str, text: str) -> Dict[str, Any]:
    """Equipe responde pelo MUGOVERSO, pelo número da marca (Cloud API), dentro da janela de 24 h."""
    body = re.sub(r"[ \t]+", " ", str(text or "")).strip()[:4096]
    if not body:
        raise WhatsAppNativeError("EMPTY", "Escreva a mensagem.")
    if not _UUID.match(str(thread_id)):
        raise WhatsAppNativeError("NOT_FOUND", "Conversa não encontrada.")
    threads = await sb_select("whatsapp_threads", select="id,number_id,wa_id,last_inbound_at",
                              filters={"id": f"eq.{thread_id}", "client_id": f"eq.{client_id}"}, limit=1)
    if not threads:
        raise WhatsAppNativeError("NOT_FOUND", "Conversa não encontrada.")
    thread = threads[0]
    inbound = thread.get("last_inbound_at")
    now = datetime.now(timezone.utc)
    if not inbound or datetime.fromisoformat(str(inbound).replace("Z", "+00:00")) + timedelta(hours=24) <= now:
        raise WhatsAppNativeError("OUTSIDE_WINDOW", "Passaram 24 horas desde a última mensagem da pessoa: o WhatsApp só aceita resposta livre dentro desse prazo.")
    numbers = await sb_select("whatsapp_numbers", select="id,phone_number_id,access_token,status",
                              filters={"id": f"eq.{thread['number_id']}", "client_id": f"eq.{client_id}", "status": "eq.active"}, limit=1)
    if not numbers:
        raise WhatsAppNativeError("NOT_FOUND", "O número desta conversa foi desligado do MUGOVERSO.")
    number = numbers[0]
    out = await _graph("POST", f"{number['phone_number_id']}/messages", number["access_token"],
                       json_body={"messaging_product": "whatsapp", "to": thread["wa_id"], "type": "text",
                                  "text": {"body": body, "preview_url": False}})
    provider_id = str(((out.get("messages") or [{}])[0] or {}).get("id") or f"mugoverso:{uuid.uuid4()}")
    stamp = now.isoformat()
    await sb_upsert("whatsapp_messages", [{"client_id": client_id, "thread_id": thread["id"], "number_id": number["id"],
                                           "provider_message_id": provider_id, "direction": "out", "type": "text", "text": body,
                                           "status": "sent", "sent_at": stamp}], on_conflict="number_id,provider_message_id")
    await sb_update("whatsapp_threads", filters={"id": f"eq.{thread['id']}", "client_id": f"eq.{client_id}"},
                    patch={"last_message_at": stamp, "last_preview": body[:160], "last_direction": "out", "unread_count": 0},
                    returning="minimal")
    paused = None
    try:  # equipe respondeu: a IA fica quieta nesta conversa pelo tempo configurado
        from .whatsapp_ai import pause_after_team_reply
        paused = await pause_after_team_reply(client_id, thread["id"])
    except Exception as exc:  # noqa: BLE001 — a mensagem já saiu; a pausa não pode derrubar o envio
        print(f"[whatsapp_native] ai_pause_failed client_id={client_id} {type(exc).__name__}")
    return {"status": "sent", "at": stamp, **({"ai_paused_minutes": paused} if paused else {})}


# ---------------------------------------------------------------- templates (mensagem iniciada pela marca)

async def _active_number(client_id: str, number_id: Optional[str]) -> Dict[str, Any]:
    filters = {"client_id": f"eq.{client_id}", "status": "eq.active"}
    if number_id:
        if not _UUID.match(str(number_id)):
            raise WhatsAppNativeError("NOT_FOUND", "Número não encontrado.")
        filters["id"] = f"eq.{number_id}"
    rows = await sb_select("whatsapp_numbers", select="id,waba_id,phone_number_id,access_token,display_phone_number",
                           filters=filters, order="created_at.asc", limit=1)
    if not rows:
        raise WhatsAppNativeError("NOT_FOUND", "Esta empresa não tem número de WhatsApp ativo no MUGOVERSO.")
    return rows[0]


async def list_templates(client_id: str, number_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Templates da WABA da marca (só leitura). A aprovação é sempre da Meta."""
    number = await _active_number(client_id, number_id)
    body = await _graph("GET", f"{number['waba_id']}/message_templates", number["access_token"],
                        params={"fields": "name,language,status,category,components", "limit": 200})
    out = []
    for t in body.get("data") or []:
        text = next((str(c.get("text") or "") for c in t.get("components") or [] if str(c.get("type") or "").upper() == "BODY"), "")
        header = next((c for c in t.get("components") or [] if str(c.get("type") or "").upper() == "HEADER"), None) or {}
        header_format = str(header.get("format") or "").upper() or None
        out.append({"name": t.get("name"), "language": t.get("language"), "status": t.get("status"),
                    "category": t.get("category"), "body": text[:1024],
                    "variables": len(set(re.findall(r"\{\{\s*([^}\s]+)\s*\}\}", text))),
                    # Topo do modelo: IMAGE/VIDEO/DOCUMENT exigem o arquivo no envio; TEXT com {{1}} exige o texto.
                    "header": header_format,
                    "header_variables": len(set(re.findall(r"\{\{\s*([^}\s]+)\s*\}\}", str(header.get("text") or ""))))})
    return out


async def send_template(client_id: str, *, number_id: Optional[str], to: str, template: str, language: str,
                        params: List[str], header_media: Optional[Dict[str, str]] = None,
                        receipt: Optional[Dict[str, str]] = None) -> str:
    """Envia um template aprovado para um número (fora da janela de 24 h). Devolve o id da mensagem na Meta.
    ``header_media`` = {"type": "image"|"video"|"document", "link": "https://..."} para modelo com mídia no topo."""
    digits = re.sub(r"\D", "", str(to or ""))
    if len(digits) < 10:
        raise WhatsAppNativeError("INVALID_PHONE", "Telefone inválido.")
    number = await _active_number(client_id, number_id)
    components: List[Dict[str, Any]] = []
    if header_media and header_media.get("link"):
        kind = header_media.get("type") if header_media.get("type") in ("image", "video", "document") else "image"
        components.append({"type": "header", "parameters": [{"type": kind, kind: {"link": header_media["link"]}}]})
    if params:
        components.append({"type": "body", "parameters": [{"type": "text", "text": str(p)[:1000] or "-"} for p in params]})
    out = await _graph("POST", f"{number['phone_number_id']}/messages", number["access_token"],
                       json_body={"messaging_product": "whatsapp", "to": digits, "type": "template",
                                  "template": {"name": template, "language": {"code": language or "pt_BR"}, "components": components}})
    if receipt is not None:
        recipient = str(((out.get("contacts") or [{}])[0] or {}).get("wa_id") or "")
        receipt.update(number_id=str(number["id"]), wa_id=recipient if recipient.isdigit() else digits)
    return str(((out.get("messages") or [{}])[0] or {}).get("id") or "")


# ---------------------------------------------------------------- brand-owned message-template creation
_TEMPLATE_NAME = re.compile(r"^[a-z][a-z0-9_]{2,80}$")
_TEMPLATE_PARAM = re.compile(r"\{\{(\d+)\}\}")


def validate_template_input(*, name: str, category: str, language: str, body: str,
                            examples: List[str], footer: str = "", buttons: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Whitelisted v1 template builder: body + optional footer, positional variables only.
    Sending or campaign automation is not triggered by creating a template.
    """
    name, category, language, body, footer = (str(value or "").strip()
                                              for value in (name, category, language, body, footer))
    if not _TEMPLATE_NAME.fullmatch(name):
        raise WhatsAppNativeError("TEMPLATE_INVALID", "Nome: de 3 a 81 caracteres, iniciando com letra minúscula; use letras, números e _.")
    if category not in {"MARKETING", "UTILITY"}:
        raise WhatsAppNativeError("TEMPLATE_INVALID", "Escolha Marketing ou Utilidade.")
    if language not in {"pt_BR", "en_US", "es_ES"}:
        raise WhatsAppNativeError("TEMPLATE_INVALID", "Idioma não disponível para esta versão.")
    if not (1 <= len(body) <= 1024) or len(footer) > 60 or "\n\n\n" in body:
        raise WhatsAppNativeError("TEMPLATE_INVALID", "Corpo obrigatório com até 1024 caracteres, rodapé com até 60.")
    used = [int(n) for n in _TEMPLATE_PARAM.findall(body)]
    if re.search(r"\{\{|\}\}", _TEMPLATE_PARAM.sub("", body)):
        raise WhatsAppNativeError("TEMPLATE_INVALID", "Use apenas variáveis numeradas como {{1}}, {{2}}.")
    max_var = max(used, default=0)
    if max_var > 5 or set(used) != set(range(1, max_var + 1)):
        raise WhatsAppNativeError("TEMPLATE_INVALID", "Use até cinco variáveis consecutivas: {{1}}, {{2}} ...")
    if len(examples) != max_var or any(not isinstance(v, str) or not v.strip() or len(v) > 100 for v in examples):
        raise WhatsAppNativeError("TEMPLATE_INVALID", "Informe um exemplo de até 100 caracteres para cada variável.")
    component: Dict[str, Any] = {"type": "BODY", "text": body}
    if max_var:
        component["example"] = {"body_text": [[v.strip() for v in examples]]}
    components: List[Dict[str, Any]] = [component]
    if footer:
        components.append({"type": "FOOTER", "text": footer})
    # Botões de link (ex.: "Entrar no grupo"): até 2, texto até 25 caracteres, só https e sem variável no link.
    clean_buttons = []
    for button in (buttons or [])[:2]:
        text, url = str((button or {}).get("text") or "").strip(), str((button or {}).get("url") or "").strip()
        if not text and not url:
            continue
        if not (1 <= len(text) <= 25) or not re.match(r"^https://[^\s{}]{4,1990}$", url):
            raise WhatsAppNativeError("TEMPLATE_INVALID", "Botão: texto de até 25 caracteres e um link completo começando com https://.")
        clean_buttons.append({"type": "URL", "text": text, "url": url})
    if clean_buttons:
        components.append({"type": "BUTTONS", "buttons": clean_buttons})
    return {"name": name, "category": category, "language": language,
            "allow_category_change": True, "components": components}


async def create_template(client_id: str, *, number_id: Optional[str], name: str, category: str,
                          language: str, body: str, examples: List[str], footer: str = "",
                          buttons: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Submits to this tenant's own WABA; Meta decides approval state."""
    number = await _active_number(client_id, number_id)
    payload = validate_template_input(name=name, category=category, language=language,
                                      body=body, examples=examples, footer=footer, buttons=buttons)
    result = await _graph("POST", f"{number['waba_id']}/message_templates", number["access_token"],
                          json_body=payload)
    return {"id": str(result.get("id") or ""), "name": payload["name"],
            "category": str(result.get("category") or payload["category"]),
            "language": payload["language"], "status": str(result.get("status") or "PENDING").upper(),
            "waba_id": str(number["waba_id"])}
