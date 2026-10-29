"""Mensagens de conteúdo e tráfego pelo WhatsApp oficial da Mugô (MugôZap, no CRM).

O envio NÃO é duplicado aqui: o Dados chama o ``mugozap-api`` do CRM pelo
caminho interno já existente (``X-Task-Command-Worker-Key`` + membro da equipe),
e o CRM valida template aprovado, destinatário cadastrado, idempotência e
grava o histórico canônico. Sem essa configuração, o Dados gera o link wa.me
com o mesmo texto (como já fazia na aprovação).

Todo conteúdo nasce dos dados: números vêm do read model (nunca da IA) e a IA
só escreve a frase curta de destaque/atenção a partir desses números. A equipe
vê a prévia e pode editar a frase antes de enviar.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

from .ig_supabase import sb_delete, sb_insert, sb_select, sb_update
from .studio_calendar import ITEMS_TABLE, StudioError

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
CONTACTS = "studio_client_contacts"
MESSAGES = "studio_messages"
RECEIVES = ("conteudo", "trafego", "resultados")
MONTHS = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro",
          "outubro", "novembro", "dezembro")

# Os mesmos textos estão em docs/WHATSAPP_TEMPLATES.md, prontos para cadastrar na Meta.
# Corpo: variáveis numeradas na ordem de "params". Botão URL: sufixo dinâmico {{1}}.
TEMPLATES: Dict[str, Dict[str, Any]] = {
    "mugo_conteudo_aprovacao": {
        "kind": "aprovacao", "header": None,
        "params": ["nome", "quantidade", "mes", "marca", "validade"],
        "body": "Olá, {{1}}! A equipe Mugô preparou {{2}} conteúdo(s) de {{3}} para a {{4}}. "
                "Toque no botão abaixo para ver as artes e aprovar ou pedir ajuste em cada um. O link vale até {{5}} e não precisa de login.",
        "button": {"text": "Ver e aprovar", "path": "/aprovar/"},
    },
    "mugo_conteudo_aprovacao_arte": {
        "kind": "aprovacao", "header": "image",
        "params": ["nome", "quantidade", "mes", "marca", "validade"],
        "body": "Olá, {{1}}! A equipe Mugô preparou {{2}} conteúdo(s) de {{3}} para a {{4}}. "
                "Esta é uma das artes. Toque no botão abaixo para ver todas e aprovar ou pedir ajuste. O link vale até {{5}} e não precisa de login.",
        "button": {"text": "Ver e aprovar", "path": "/aprovar/"},
    },
    "mugo_lembrete_aprovacao": {
        "kind": "lembrete", "header": None,
        "params": ["nome", "pendentes", "marca", "validade"],
        "body": "Olá, {{1}}! Ainda faltam {{2}} conteúdo(s) da {{3}} esperando sua aprovação. "
                "Para manter o calendário em dia, responda até {{4}} pelo botão abaixo.",
        "button": {"text": "Ver e aprovar", "path": "/aprovar/"},
    },
    "mugo_agenda_semana": {
        "kind": "agenda", "header": None,
        "params": ["nome", "marca", "semana", "quantidade", "destaque"],
        "body": "Olá, {{1}}! Agenda de conteúdo da {{2}} para a semana de {{3}}: {{4}} publicação(ões) aprovada(s). "
                "Destaque: {{5}}. Qualquer ajuste, é só responder esta mensagem.",
        "button": None,
    },
    "mugo_relatorio_trafego": {
        "kind": "trafego", "header": None,
        "params": ["nome", "marca", "periodo", "investimento", "receita", "roas", "destaque"],
        "body": "Olá, {{1}}! Resumo do tráfego pago da {{2}} em {{3}}: investimento de {{4}}, faturamento da loja de {{5}} "
                "no mesmo período e retorno de {{6}} para cada R$ 1 investido. Destaque: {{7}}. Os detalhes estão no painel Mugô Dados.",
        "button": None,
    },
    "mugo_resultados_mes": {
        "kind": "resultados", "header": None,
        "params": ["nome", "mes", "marca", "faturamento", "variacao", "pedidos", "investimento", "atencao"],
        "body": "Olá, {{1}}! Fechamos {{2}} da {{3}}: faturamento de {{4}} ({{5}} em relação ao mês anterior), "
                "{{6}} pedidos e {{7}} investidos em mídia. Ponto de atenção: {{8}}. Vamos conversar sobre os próximos passos?",
        "button": None,
    },
}
KIND_RECEIVES = {"aprovacao": "conteudo", "lembrete": "conteudo", "agenda": "conteudo",
                 "trafego": "trafego", "resultados": "resultados"}
EDITABLE_PARAMS = {"destaque", "atencao"}


# --------------------------------------------------------------------------
# Formatação
# --------------------------------------------------------------------------

def param(value: Any, limit: int = 160) -> str:
    """A Meta recusa variável vazia, com quebra de linha, tab ou 4+ espaços seguidos."""
    text = re.sub(r"\s+", " ", str(value if value is not None else "")).strip()[:limit]
    return text or "—"


def brl(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    text = f"{number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {text}"


def pct(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    sign = "+" if number > 0 else ""
    return f"{sign}{number:.1f}%".replace(".", ",")


def ratio(value: Any) -> str:
    try:
        return f"{float(value):.2f}".replace(".", ",")
    except (TypeError, ValueError):
        return "—"


def mask_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    return f"{digits[:4]}…{digits[-4:]}" if len(digits) >= 8 else "***"


def render(template_name: str, params: Dict[str, str]) -> str:
    template = TEMPLATES[template_name]
    text = template["body"]
    for index, key in enumerate(template["params"], start=1):
        text = text.replace("{{%d}}" % index, params.get(key) or "—")
    return text


def first_name(name: Optional[str]) -> str:
    return (name or "").strip().split(" ")[0] or "tudo bem"


def br_date(value: Any) -> str:
    try:
        d = value if isinstance(value, date) else datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(SAO_PAULO).date()
    except ValueError:
        return "—"
    return d.strftime("%d/%m")


# --------------------------------------------------------------------------
# Contatos
# --------------------------------------------------------------------------

def normalize_phone(raw: Optional[str]) -> str:
    from .studio_approvals import normalize_phone as base
    phone = base(raw)
    if not phone:
        raise StudioError("PHONE_INVALID")
    return phone


async def list_contacts(client_id: str) -> List[Dict[str, Any]]:
    rows = await sb_select(CONTACTS, select="id,name,phone,role,receives,is_primary,active,updated_at",
                           filters={"client_id": f"eq.{client_id}", "active": "eq.true"}, order="is_primary.desc,name.asc", limit=100)
    return rows


async def save_contact(client_id: str, data: Dict[str, Any], *, user_id: str, contact_id: Optional[str] = None) -> Dict[str, Any]:
    row = {
        "name": param(data.get("name"), 120), "phone": normalize_phone(data.get("phone")),
        "role": (str(data.get("role") or "").strip()[:80] or None),
        "receives": [r for r in RECEIVES if r in (data.get("receives") or ["conteudo"])] or ["conteudo"],
        "is_primary": bool(data.get("is_primary")),
    }
    if row["name"] == "—":
        raise StudioError("NAME_INVALID")
    if row["is_primary"]:
        await sb_update(CONTACTS, filters={"client_id": f"eq.{client_id}", "is_primary": "eq.true"}, patch={"is_primary": False})
    if contact_id:
        rows = await sb_update(CONTACTS, filters={"client_id": f"eq.{client_id}", "id": f"eq.{contact_id}"}, patch=row)
        if not rows:
            raise StudioError("CONTACT_NOT_FOUND")
        return rows[0]
    created = await sb_insert(CONTACTS, {**row, "client_id": client_id, "created_by": user_id})
    if not created:
        raise StudioError("CREATE_FAILED")
    return created


async def delete_contact(client_id: str, contact_id: str) -> None:
    rows = await sb_delete(CONTACTS, filters={"client_id": f"eq.{client_id}", "id": f"eq.{contact_id}"})
    if not rows:
        raise StudioError("CONTACT_NOT_FOUND")


async def _contact(client_id: str, contact_id: Optional[str], kind: str) -> Dict[str, Any]:
    contacts = await list_contacts(client_id)
    if contact_id:
        found = next((c for c in contacts if str(c["id"]) == str(contact_id)), None)
    else:
        wants = KIND_RECEIVES[kind]
        found = next((c for c in contacts if c.get("is_primary") and wants in (c.get("receives") or [])), None) \
            or next((c for c in contacts if wants in (c.get("receives") or [])), None)
    if not found:
        raise StudioError("CONTACT_REQUIRED")
    return found


async def list_messages(client_id: str) -> List[Dict[str, Any]]:
    return await sb_select(MESSAGES, select="id,contact_name,phone_masked,kind,template_name,channel,status,error_code,preview,created_at",
                           filters={"client_id": f"eq.{client_id}"}, order="created_at.desc", limit=100)


# --------------------------------------------------------------------------
# MugôZap (CRM)
# --------------------------------------------------------------------------

def mugozap_config() -> Optional[Dict[str, str]]:
    cfg = {k: (os.getenv(env) or "").strip() for k, env in (
        ("url", "MUGOZAP_FUNCTION_URL"), ("anon", "MUGOZAP_ANON_KEY"),
        ("worker_key", "MUGOZAP_WORKER_KEY"), ("team_member_id", "MUGOZAP_TEAM_MEMBER_ID"))}
    if not all(cfg.values()) or not cfg["url"].startswith("https://"):
        return None
    return cfg


def components_for(template_name: str, params: Dict[str, str], *, button_suffix: Optional[str],
                   header_image: Optional[str]) -> List[Dict[str, Any]]:
    template = TEMPLATES[template_name]
    components: List[Dict[str, Any]] = []
    if template["header"] == "image":
        if not header_image or not header_image.startswith("https://"):
            raise StudioError("HEADER_IMAGE_REQUIRED")
        components.append({"type": "header", "parameters": [{"type": "image", "image": {"link": header_image}}]})
    components.append({"type": "body", "parameters": [{"type": "text", "text": params[k]} for k in template["params"]]})
    if template["button"]:
        if not button_suffix:
            raise StudioError("BUTTON_PARAM_REQUIRED")
        components.append({"type": "button", "sub_type": "url", "index": "0",
                           "parameters": [{"type": "text", "text": button_suffix}]})
    return components


MUGOZAP_ERRORS = {
    "TEMPLATE_NOT_APPROVED": "TEMPLATE_NOT_APPROVED",
    "TEMPLATE_RECIPIENT_NOT_REGISTERED": "RECIPIENT_NOT_IN_CRM",
    "PHONE_MISMATCH": "RECIPIENT_NOT_IN_CRM",
    "INVALID_PHONE": "PHONE_INVALID",
    "SEND_OUTCOME_UNKNOWN": "SEND_OUTCOME_UNKNOWN",
}


async def mugozap_send(cfg: Dict[str, str], *, phone: str, template_name: str, components: List[Dict[str, Any]],
                       idempotency_key: str) -> Dict[str, Any]:
    body = {"operation": "send_template_message", "payload": {
        "recipient": phone, "template_name": template_name, "language": "pt_BR", "components": components,
        "idempotency_key": idempotency_key, "contract_mode": "media" if components[0]["type"] == "header" else "body_multiple",
        "team_member_id": cfg["team_member_id"],
    }}
    headers = {"Authorization": f"Bearer {cfg['anon']}", "apikey": cfg["anon"], "Content-Type": "application/json",
               "X-Task-Command-Worker-Key": cfg["worker_key"]}
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            response = await client.post(cfg["url"], headers=headers, json=body)
        data = response.json() if response.content else {}
    except (httpx.HTTPError, ValueError):
        return {"ok": False, "code": "MUGOZAP_UNAVAILABLE"}
    if response.status_code < 400 and data.get("ok"):
        inner = data.get("data") or {}
        return {"ok": True, "provider_message_id": str(inner.get("provider_message_id") or inner.get("message_id") or "")[:200] or None}
    code = str(data.get("code") or f"HTTP_{response.status_code}")[:80]
    return {"ok": False, "code": MUGOZAP_ERRORS.get(code, code)}


def idempotency(*parts: Any) -> str:
    raw = "|".join(str(p) for p in parts)
    return "dados-" + hashlib.sha256(raw.encode()).hexdigest()[:40]


async def deliver(client_id: str, *, contact: Dict[str, Any], template_name: str, params: Dict[str, str],
                  button_suffix: Optional[str], header_image: Optional[str], request_id: Optional[str],
                  user_id: str, key: str) -> Dict[str, Any]:
    """Envia pelo MugôZap (ou gera wa.me) e registra no histórico."""
    template = TEMPLATES[template_name]
    params = {k: param(params.get(k), 300 if k in EDITABLE_PARAMS else 160) for k in template["params"]}
    text = render(template_name, params)
    base = {"client_id": client_id, "contact_id": contact.get("id"), "contact_name": param(contact.get("name"), 120),
            "phone_masked": mask_phone(contact["phone"]), "kind": template["kind"], "template_name": template_name,
            "request_id": request_id, "idempotency_key": key, "sent_by": user_id,
            "preview": {"text": text, "params": params, "has_image": bool(header_image)}}
    cfg = mugozap_config()
    if not cfg:
        link_text = text + (f"\n{button_link(button_suffix)}" if template["button"] and button_suffix else "")
        url = f"https://wa.me/{contact['phone']}?text={quote(link_text)}"
        await _log({**base, "channel": "wa_link", "status": "link_gerado", "idempotency_key": key + "-l" + _stamp()})
        return {"status": "link_gerado", "channel": "wa_link", "whatsapp_url": url, "text": text}
    prior = await sb_select(MESSAGES, select="status,provider_message_id", filters={"idempotency_key": f"eq.{key}"}, limit=1)
    if prior and prior[0].get("status") == "enviado":
        return {"status": "enviado", "channel": "mugozap", "already_sent": True, "text": text}
    result = await mugozap_send(cfg, phone=contact["phone"], template_name=template_name, idempotency_key=key,
                                components=components_for(template_name, params, button_suffix=button_suffix, header_image=header_image))
    status = "enviado" if result["ok"] else "falhou"
    row = {**base, "channel": "mugozap", "status": status, "error_code": None if result["ok"] else result["code"],
           "provider_message_id": result.get("provider_message_id")}
    if prior:  # falha anterior com a mesma chave: o CRM permite nova tentativa
        await sb_update(MESSAGES, filters={"idempotency_key": f"eq.{key}"}, patch=row)
    else:
        await _log(row)
    if not result["ok"]:
        raise StudioError(result["code"] if result["code"] in SEND_ERRORS else "SEND_FAILED")
    return {"status": "enviado", "channel": "mugozap", "text": text}


SEND_ERRORS = {"TEMPLATE_NOT_APPROVED", "RECIPIENT_NOT_IN_CRM", "PHONE_INVALID", "SEND_OUTCOME_UNKNOWN", "MUGOZAP_UNAVAILABLE"}


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")


async def _log(row: Dict[str, Any]) -> None:
    try:
        await sb_insert(MESSAGES, row)
    except Exception as exc:  # histórico não pode esconder o resultado do envio
        print(f"[studio][messages] log_falhou erro={exc.__class__.__name__}")


def button_link(suffix: Optional[str]) -> str:
    from .studio_approvals import frontend_base_url
    return f"{frontend_base_url()}/aprovar/{suffix}" if suffix else ""


async def _client_name(client_id: str) -> str:
    from .studio_approvals import _client_name as name
    return await name(client_id)


# --------------------------------------------------------------------------
# Mensagens montadas a partir dos dados
# --------------------------------------------------------------------------

async def build_message(client_id: str, kind: str, *, contact_id: Optional[str] = None,
                        request_id: Optional[str] = None, overrides: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Prévia: template, variáveis e texto final. Nada é enviado."""
    if kind not in KIND_RECEIVES:
        raise StudioError("KIND_INVALID")
    contact = await _contact(client_id, contact_id, kind)
    brand = await _client_name(client_id)
    extra: Dict[str, Any] = {"button_suffix": None, "header_image": None, "request_id": None, "key_parts": []}
    if kind in ("aprovacao", "lembrete"):
        params, extra = await _approval_params(client_id, kind, request_id, contact, brand)
    elif kind == "agenda":
        params = await _agenda_params(client_id, contact, brand)
    elif kind == "trafego":
        params = await _traffic_params(client_id, contact, brand)
    else:
        params = await _results_params(client_id, contact, brand)
    for key, value in (overrides or {}).items():
        if key in EDITABLE_PARAMS and key in params and str(value or "").strip():
            params[key] = param(value, 300)
    template_name = params.pop("_template")
    clean = {k: param(params.get(k), 300 if k in EDITABLE_PARAMS else 160) for k in TEMPLATES[template_name]["params"]}
    return {"kind": kind, "template_name": template_name, "params": clean, "text": render(template_name, clean),
            "editable": [k for k in clean if k in EDITABLE_PARAMS], "contact": {k: contact.get(k) for k in ("id", "name", "role")},
            "phone_masked": mask_phone(contact["phone"]), "header_image": extra.get("header_image"),
            "channel": "mugozap" if mugozap_config() else "wa_link", "_contact": contact, "_extra": extra}


async def send_message(client_id: str, kind: str, *, user_id: str, contact_id: Optional[str] = None,
                       request_id: Optional[str] = None, overrides: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    built = await build_message(client_id, kind, contact_id=contact_id, request_id=request_id, overrides=overrides)
    extra, contact = built["_extra"], built["_contact"]
    today = datetime.now(SAO_PAULO).date().isoformat()
    key = idempotency(client_id, kind, built["template_name"], contact["phone"], *(extra.get("key_parts") or [today]),
                      json.dumps(built["params"], sort_keys=True, ensure_ascii=False))
    result = await deliver(client_id, contact=contact, template_name=built["template_name"], params=built["params"],
                           button_suffix=extra.get("button_suffix"), header_image=extra.get("header_image"),
                           request_id=extra.get("request_id"), user_id=user_id, key=key)
    if kind == "lembrete" and extra.get("request_id"):
        await sb_update("studio_approval_requests", filters={"id": f"eq.{extra['request_id']}"},
                        patch={"last_reminded_at": datetime.now(timezone.utc).isoformat()})
    return result


def public_preview(built: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in built.items() if not k.startswith("_")}


async def _approval_params(client_id: str, kind: str, request_id: Optional[str], contact: Dict[str, Any], brand: str):
    from .crypto import decrypt_secret
    filters = {"client_id": f"eq.{client_id}", "status": "eq.aberto"}
    if request_id:
        filters["id"] = f"eq.{request_id}"
    rows = await sb_select("studio_approval_requests", select="id,month,item_ids,expires_at,token_ciphertext",
                           filters=filters, order="created_at.desc", limit=1)
    request = rows[0] if rows else None
    if not request or datetime.fromisoformat(str(request["expires_at"]).replace("Z", "+00:00")) < datetime.now(timezone.utc):
        raise StudioError("REQUEST_NOT_FOUND")
    if not request.get("token_ciphertext"):
        raise StudioError("LINK_NOT_RESENDABLE")
    try:
        token = decrypt_secret(request["token_ciphertext"])
    except Exception:
        raise StudioError("LINK_NOT_RESENDABLE") from None
    ids = [str(i) for i in request.get("item_ids") or []]
    events = await sb_select("studio_approval_events", select="item_id", filters={"request_id": f"eq.{request['id']}"}, limit=500)
    decided = {str(e["item_id"]) for e in events}
    pending = [i for i in ids if i not in decided]
    if kind == "lembrete" and not pending:
        raise StudioError("NOTHING_PENDING")
    month = date.fromisoformat(str(request["month"])[:10])
    header_image = None
    template = "mugo_lembrete_aprovacao"
    if kind == "aprovacao":
        template = "mugo_conteudo_aprovacao"
        from .studio_assets import item_assets
        try:
            arts = await item_assets(client_id, ids[:20], public=True)
        except StudioError:
            arts = {}
        cover = next((a for i in ids for a in arts.get(i, []) if a.get("kind") == "imagem" and a.get("url")), None)
        if cover:
            template, header_image = "mugo_conteudo_aprovacao_arte", cover["url"]
    params = {"_template": template, "nome": first_name(contact.get("name")), "marca": brand,
              "quantidade": str(len(ids)), "pendentes": str(len(pending)), "mes": MONTHS[month.month - 1],
              "validade": br_date(request["expires_at"])}
    key_parts = [request["id"]] if kind == "aprovacao" else [request["id"], datetime.now(SAO_PAULO).date().isoformat()]
    return params, {"button_suffix": token, "header_image": header_image, "request_id": request["id"], "key_parts": key_parts}


async def _agenda_params(client_id: str, contact: Dict[str, Any], brand: str) -> Dict[str, str]:
    today = datetime.now(SAO_PAULO).date()
    # De sexta a domingo a "semana" já é a próxima.
    monday = today + timedelta(days=7 - today.weekday()) if today.weekday() >= 4 else today - timedelta(days=today.weekday())
    end = monday + timedelta(days=6)
    rows = await sb_select(ITEMS_TABLE, select="scheduled_at,format,title,status", order="scheduled_at.asc", limit=50,
                           filters={"client_id": f"eq.{client_id}", "status": "in.(aprovado,publicado)",
                                    "and": f"(scheduled_at.gte.{monday.isoformat()}T00:00:00-03:00,scheduled_at.lte.{end.isoformat()}T23:59:59-03:00)"})
    if not rows:
        raise StudioError("NOTHING_SCHEDULED")
    first = rows[0]
    highlight = f"{first.get('title')} ({br_date(first.get('scheduled_at'))})"
    return {"_template": "mugo_agenda_semana", "nome": first_name(contact.get("name")), "marca": brand,
            "semana": f"{monday.strftime('%d/%m')} a {end.strftime('%d/%m')}", "quantidade": str(len(rows)), "destaque": highlight}


async def _snapshot(client_id: str, start: date, end: date) -> Dict[str, Any]:
    from .intelligence import calculate_intelligence_snapshot
    snap = await calculate_intelligence_snapshot(client_id=client_id, start=start.isoformat(), end=end.isoformat(),
                                                 include_commerce_details=False, include_external_research=False)
    metrics = {m.get("id"): m for m in snap.get("metrics") or [] if m.get("id")}
    return {"metrics": metrics, "campaigns": snap.get("top_campaigns") or []}


def _value(metrics: Dict[str, Any], key: str) -> Optional[float]:
    try:
        return float((metrics.get(key) or {}).get("value"))
    except (TypeError, ValueError):
        return None


async def _sentence(task: str, data: Dict[str, Any], fallback: str) -> str:
    """Frase curta escrita pela IA a partir dos números; sem IA, a frase determinística."""
    from .studio_llm import STR, llm_json, obj
    try:
        out = await llm_json(
            instructions=("Você escreve UMA frase curta (até 140 caracteres, sem quebra de linha, sem emoji) para uma "
                          "mensagem de WhatsApp a um cliente de agência. Use só os números dados; não invente nada."),
            prompt=f"{task}\nDADOS: {json.dumps(data, ensure_ascii=False, default=str)}",
            schema_name="studio_message_sentence", schema=obj({"sentence": STR}), temperature=0.3, timeout=30)
        sentence = param(out.get("sentence"), 160)
        return sentence if sentence != "—" else fallback
    except StudioError:
        return fallback


async def _traffic_params(client_id: str, contact: Dict[str, Any], brand: str) -> Dict[str, str]:
    today = datetime.now(SAO_PAULO).date()
    end = today - timedelta(days=1)
    start = end - timedelta(days=6)
    snap = await _snapshot(client_id, start, end)
    spend, revenue = _value(snap["metrics"], "investment"), _value(snap["metrics"], "revenue")
    roas = _value(snap["metrics"], "roas")
    if not spend:
        raise StudioError("NO_PAID_DATA")
    campaigns = [{"campanha": c.get("name"), "investimento": c.get("spend"), "receita": c.get("revenue"),
                  "conversoes": c.get("conversions")} for c in snap["campaigns"][:5]]
    best = max(campaigns, key=lambda c: (float(c["receita"] or 0) / float(c["investimento"] or 1)), default=None)
    fallback = f"melhor retorno em {best['campanha']}" if best and best.get("campanha") else "veja as campanhas no painel"
    highlight = await _sentence("Diga o principal destaque da semana do tráfego pago (melhor campanha ou variação relevante).",
                                {"investimento": spend, "receita": revenue, "roas": roas, "campanhas": campaigns,
                                 "variacao_investimento_pct": (snap["metrics"].get("investment") or {}).get("variation_percent")}, fallback)
    return {"_template": "mugo_relatorio_trafego", "nome": first_name(contact.get("name")), "marca": brand,
            "periodo": f"{start.strftime('%d/%m')} a {end.strftime('%d/%m')}", "investimento": brl(spend),
            "receita": brl(revenue) if revenue is not None else "—",
            "roas": brl(roas if roas is not None else (revenue or 0) / spend),
            "destaque": highlight}


async def _results_params(client_id: str, contact: Dict[str, Any], brand: str) -> Dict[str, str]:
    today = datetime.now(SAO_PAULO).date()
    end = today.replace(day=1) - timedelta(days=1)
    start = end.replace(day=1)
    snap = await _snapshot(client_id, start, end)
    metrics = snap["metrics"]
    revenue = _value(metrics, "revenue")
    if revenue is None:
        raise StudioError("NO_RESULTS_DATA")
    variation = (metrics.get("revenue") or {}).get("variation_percent")
    data = {k: {"valor": _value(metrics, k), "variacao_pct": (metrics.get(k) or {}).get("variation_percent")}
            for k in ("revenue", "orders", "average_ticket", "investment", "roas", "sessions", "conversion_rate") if k in metrics}
    attention = await _sentence("Aponte o principal ponto de atenção do mês (a métrica que mais piorou ou o risco mais claro).",
                                data, "vamos revisar juntos os canais no painel")
    return {"_template": "mugo_resultados_mes", "nome": first_name(contact.get("name")), "mes": MONTHS[start.month - 1],
            "marca": brand, "faturamento": brl(revenue), "variacao": pct(variation),
            "pedidos": str(int(_value(metrics, "orders") or 0)), "investimento": brl(_value(metrics, "investment") or 0),
            "atencao": attention}
