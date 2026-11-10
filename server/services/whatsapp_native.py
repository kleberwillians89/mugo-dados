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
NUMBER_PUBLIC_FIELDS = "id,client_id,waba_id,phone_number_id,display_phone_number,verified_name,status,subscribed_at,created_at"


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
        print(f"[whatsapp_native] graph path={path.split('/')[-1] or path} status={resp.status_code} code={code}")
        if code in {"190", "102"} or resp.status_code == 401:
            raise WhatsAppNativeError("TOKEN_INVALID", "A Meta recusou o token. Gere um token do usuário do sistema com acesso a esta WABA.")
        if code in {"100", "803"} or resp.status_code == 404:
            raise WhatsAppNativeError("NOT_FOUND", "A Meta não encontrou esse ID. Confira o ID da WABA e o ID do número.")
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
                          user_id: Optional[str] = None) -> Dict[str, Any]:
    waba_id, phone_number_id, token = str(waba_id).strip(), str(phone_number_id).strip(), str(access_token).strip()
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


async def conversations(client_id: str, limit: int = 60) -> Dict[str, Any]:
    if not await active_number_ids(client_id):
        return {"available": True, "connected": False, "conversations": []}
    rows = await sb_select("whatsapp_threads",
                           select="id,wa_id,phone_key,profile_name,first_seen_at,last_message_at,last_inbound_at,last_preview,last_direction,unread_count",
                           filters={"client_id": f"eq.{client_id}"}, order="last_message_at.desc", limit=max(1, min(int(limit), 200)))
    touches = await _touches(client_id, [str(r["id"]) for r in rows], first=False)
    out = []
    for r in rows:
        inbound = r.get("last_inbound_at")
        window = (datetime.fromisoformat(str(inbound).replace("Z", "+00:00")) + timedelta(hours=24)).isoformat() if inbound else None
        out.append({
            "id": r["id"], "status": None, "attendance_mode": "human", "unread_count": r.get("unread_count") or 0,
            "last_message_at": r.get("last_message_at"), "service_window_expires_at": window,
            "contact": {"name": (r.get("profile_name") or None), "phone_masked": mask_phone(r.get("wa_id")),
                        "phone_key": r.get("phone_key"), "first_seen_at": r.get("first_seen_at")},
            "origin": _origin(touches.get(str(r["id"]))),
            "last_message": {"direction": r.get("last_direction") or "in", "at": r.get("last_message_at"),
                             "text": str(r.get("last_preview") or "")[:160]} if r.get("last_preview") else None,
        })
    return {"available": True, "connected": True, "conversations": out}


async def messages(client_id: str, thread_id: str, limit: int = 100) -> Dict[str, Any]:
    if not _UUID.match(str(thread_id)):
        return {"available": True, "messages": [], "found": False}
    thread = await sb_select("whatsapp_threads", select="id", filters={"id": f"eq.{thread_id}", "client_id": f"eq.{client_id}"}, limit=1)
    if not thread:
        return {"available": True, "messages": [], "found": False}
    rows = await sb_select("whatsapp_messages", select="id,direction,type,text,status,error_code,sent_at,read_at",
                           filters={"thread_id": f"eq.{thread_id}", "client_id": f"eq.{client_id}"},
                           order="sent_at.desc", limit=max(1, min(int(limit), 300)))
    out = [{"id": r["id"], "direction": r["direction"], "type": r.get("type") or "text", "status": r.get("status"),
            "text": r.get("text"), "template_name": None, "at": r.get("sent_at"), "read_at": r.get("read_at"),
            "failed": r.get("status") == "failed", "error_code": r.get("error_code")} for r in reversed(rows)]
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
    return {"status": "sent", "at": stamp}
