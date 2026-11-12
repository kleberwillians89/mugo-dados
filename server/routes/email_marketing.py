"""E-mail marketing (Resend) e recuperação de carrinho. Ler: membros da empresa. Alterar/enviar: equipe Mugô e
admin do cliente. Descadastro e webhook do Resend são públicos (token assinado / assinatura Svix)."""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response

from services import cart_recovery, email_marketing, email_resend
from services.tenant import require_client_read, require_client_role, require_user_id

router = APIRouter(tags=["email"])
WRITERS = ("agency_admin", "client_admin")


def _fail(exc: Exception) -> HTTPException:
    if isinstance(exc, (email_marketing.EmailError, cart_recovery.CartError)):
        return HTTPException(status_code=exc.status, detail=exc.message)
    if isinstance(exc, email_resend.ResendError):
        return HTTPException(status_code=502 if exc.retryable else 400, detail=exc.message)
    from services.whatsapp_native import WhatsAppNativeError
    if isinstance(exc, WhatsAppNativeError):
        return HTTPException(status_code=400, detail=exc.message)
    print(f"[email_routes] unexpected {type(exc).__name__}")
    return HTTPException(status_code=502, detail="Não foi possível concluir agora. Tente de novo.")


# ---------------------------------------------------------------- remetente

@router.get("/api/email/settings")
async def email_settings(client_id: str | None = Query(default=None), x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
                         authorization: str | None = Header(default=None)):
    cid = await require_client_read(client_id or x_client_id, authorization)
    try:
        return {"ok": True, "settings": await email_marketing.get_settings(cid), "status": await email_marketing.sender_status(cid)}
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc


@router.put("/api/email/settings")
async def email_save_settings(payload: Dict[str, Any] = Body(...), client_id: str | None = Query(default=None),
                              x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
                              authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id or x_client_id, authorization, allowed_roles=WRITERS)
    user_id = await require_user_id(authorization)
    try:
        settings = await email_marketing.save_settings(cid, payload, user_id=user_id)
        return {"ok": True, "settings": settings, "status": await email_marketing.sender_status(cid)}
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc


@router.post("/api/email/audience")
async def email_audience(payload: Dict[str, Any] = Body(default={}), client_id: str | None = Query(default=None),
                         x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
                         authorization: str | None = Header(default=None)):
    """Quantas pessoas recebem com esse público (só números, nenhum e-mail sai daqui)."""
    cid = await require_client_role(client_id or x_client_id, authorization, allowed_roles=WRITERS)
    try:
        return {"ok": True, **(await email_marketing.audience_preview(cid, payload.get("audience")))}
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc


@router.post("/api/email/preview")
async def email_preview(payload: Dict[str, Any] = Body(...), client_id: str | None = Query(default=None),
                        x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
                        authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id or x_client_id, authorization, allowed_roles=WRITERS)
    try:
        return {"ok": True, **(await email_marketing.preview(cid, payload))}
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc


# ---------------------------------------------------------------- campanhas

@router.get("/api/email/campaigns")
async def email_campaigns(client_id: str | None = Query(default=None), x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
                          authorization: str | None = Header(default=None)):
    cid = await require_client_read(client_id or x_client_id, authorization)
    try:
        return {"ok": True, "campaigns": await email_marketing.list_campaigns(cid)}
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc


@router.post("/api/email/campaigns")
async def email_create_campaign(payload: Dict[str, Any] = Body(default={}), client_id: str | None = Query(default=None),
                                x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
                                authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id or x_client_id, authorization, allowed_roles=WRITERS)
    user_id = await require_user_id(authorization)
    try:
        return {"ok": True, "campaign": await email_marketing.save_campaign(cid, payload, user_id=user_id)}
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc


@router.get("/api/email/campaigns/{campaign_id}")
async def email_campaign(campaign_id: str, client_id: str | None = Query(default=None),
                         x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
                         authorization: str | None = Header(default=None)):
    cid = await require_client_read(client_id or x_client_id, authorization)
    try:
        campaign = await email_marketing.get_campaign(cid, campaign_id)
        live = campaign["status"] in ("enviando", "enviada")
        return {"ok": True, "campaign": campaign, "stats": await email_marketing.campaign_stats(cid, campaign_id) if live else None}
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc


@router.put("/api/email/campaigns/{campaign_id}")
async def email_update_campaign(campaign_id: str, payload: Dict[str, Any] = Body(...), client_id: str | None = Query(default=None),
                                x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
                                authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id or x_client_id, authorization, allowed_roles=WRITERS)
    user_id = await require_user_id(authorization)
    try:
        return {"ok": True, "campaign": await email_marketing.save_campaign(cid, payload, user_id=user_id, campaign_id=campaign_id)}
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc


@router.delete("/api/email/campaigns/{campaign_id}")
async def email_delete_campaign(campaign_id: str, client_id: str | None = Query(default=None),
                                x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
                                authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id or x_client_id, authorization, allowed_roles=WRITERS)
    try:
        await email_marketing.delete_campaign(cid, campaign_id)
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc


@router.post("/api/email/campaigns/{campaign_id}/test")
async def email_test(campaign_id: str, payload: Dict[str, Any] = Body(...), client_id: str | None = Query(default=None),
                     x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
                     authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id or x_client_id, authorization, allowed_roles=WRITERS)
    try:
        campaign = await email_marketing.get_campaign(cid, campaign_id)
        return {"ok": True, **(await email_marketing.send_test(cid, campaign, str(payload.get("to") or "")))}
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc


@router.post("/api/email/campaigns/{campaign_id}/schedule")
async def email_schedule(campaign_id: str, payload: Dict[str, Any] = Body(default={}), client_id: str | None = Query(default=None),
                         x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
                         authorization: str | None = Header(default=None)):
    """Agenda (ou envia já, sem data). O envio sai pelo job a cada 5 minutos."""
    cid = await require_client_role(client_id or x_client_id, authorization, allowed_roles=WRITERS)
    try:
        return {"ok": True, "campaign": await email_marketing.schedule(cid, campaign_id, payload.get("at"))}
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc


@router.post("/api/email/campaigns/{campaign_id}/cancel")
async def email_cancel(campaign_id: str, client_id: str | None = Query(default=None),
                       x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
                       authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id or x_client_id, authorization, allowed_roles=WRITERS)
    try:
        return {"ok": True, "campaign": await email_marketing.cancel(cid, campaign_id)}
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc


# ---------------------------------------------------------------- público: descadastro e webhook

_PAGE = ('<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
         '<title>E-mails</title></head><body style="margin:0;background:#f4f2ee;font-family:Helvetica,Arial,sans-serif">'
         '<div style="max-width:440px;margin:12vh auto;background:#fff;border-radius:16px;padding:32px;text-align:center">'
         '<h1 style="font-size:20px;margin:0 0 8px">{title}</h1><p style="color:#4d565d;line-height:1.5;margin:0">{text}</p></div></body></html>')


@router.get("/api/email/unsubscribe", response_class=HTMLResponse)
async def email_unsubscribe_page(t: str = Query(default="")):
    parsed = email_marketing.parse_unsubscribe_token(t)
    if not parsed:
        return HTMLResponse(_PAGE.format(title="Link inválido", text="Este link de descadastro não é válido."), status_code=400)
    await email_marketing.suppress(parsed[0], parsed[1], "descadastro")
    return HTMLResponse(_PAGE.format(title="Pronto", text="Você não vai mais receber e-mails desta marca."))


@router.post("/api/email/unsubscribe")
async def email_unsubscribe_one_click(t: str = Query(default="")):
    """Descadastro em 1 clique (RFC 8058): o provedor de e-mail faz POST no mesmo link."""
    parsed = email_marketing.parse_unsubscribe_token(t)
    if not parsed:
        return Response(status_code=400)
    await email_marketing.suppress(parsed[0], parsed[1], "descadastro")
    return Response(status_code=200)


@router.post("/api/webhooks/resend")
async def resend_webhook(request: Request):
    body = await request.body()
    if not email_resend.verify_webhook(body, {k.lower(): v for k, v in request.headers.items()}):
        raise HTTPException(status_code=401, detail="Assinatura inválida.")
    try:
        event = json.loads(body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Corpo inválido.") from exc
    result = await email_marketing.handle_event(event if isinstance(event, dict) else {})
    return {"ok": True, **result}


# ---------------------------------------------------------------- recuperação de carrinho

@router.get("/api/cart-recovery")
async def cart_overview(days: int = Query(default=30, ge=1, le=180), client_id: str | None = Query(default=None),
                        x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
                        authorization: str | None = Header(default=None)):
    cid = await require_client_read(client_id or x_client_id, authorization)
    try:
        return {"ok": True, **(await cart_recovery.overview(cid, days))}
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc


@router.put("/api/cart-recovery/settings")
async def cart_save_settings(payload: Dict[str, Any] = Body(...), client_id: str | None = Query(default=None),
                             x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
                             authorization: str | None = Header(default=None)):
    cid = await require_client_role(client_id or x_client_id, authorization, allowed_roles=WRITERS)
    user_id = await require_user_id(authorization)
    try:
        return {"ok": True, "settings": await cart_recovery.save_settings(cid, payload, user_id=user_id)}
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc


@router.post("/api/cart-recovery/webhooks")
async def cart_register_webhooks(client_id: str | None = Query(default=None), x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
                                 authorization: str | None = Header(default=None)):
    """Liga o aviso de checkout da Shopify nesta loja (lojas conectadas antes da recuperação de carrinho)."""
    cid = await require_client_role(client_id or x_client_id, authorization, allowed_roles=WRITERS)
    try:
        return {"ok": True, **(await cart_recovery.register_webhooks(cid))}
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc


@router.get("/api/cart-recovery/whatsapp-templates")
async def cart_templates(client_id: str | None = Query(default=None), x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
                         authorization: str | None = Header(default=None)):
    from services import whatsapp_native
    cid = await require_client_read(client_id or x_client_id, authorization)
    try:
        numbers = await whatsapp_native.list_numbers(cid)
        templates = await whatsapp_native.list_templates(cid) if any(n.get("status") == "active" for n in numbers) else []
        return {"ok": True, "numbers": numbers, "templates": templates}
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc


@router.post("/api/cart-recovery/preview")
async def cart_preview(payload: Dict[str, Any] = Body(default={}), client_id: str | None = Query(default=None),
                       x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
                       authorization: str | None = Header(default=None)):
    """Prévia do e-mail de carrinho com um carrinho de exemplo."""
    from services import email_builder
    cid = await require_client_role(client_id or x_client_id, authorization, allowed_roles=WRITERS)
    try:
        sender = await email_marketing.get_settings(cid)
        design = email_builder.normalize_design(payload.get("email_design")) if payload.get("email_design") else (await cart_recovery.get_settings(cid))["email_design"]
        items = [{"title": "Legging Move Preta", "quantity": 1, "price": 189.9}, {"title": "Top Essencial", "quantity": 2, "price": 99.9}]
        variables = {"nome": "Ana", "primeiro_nome": "Ana", "marca": sender.get("from_name") or "", "link_carrinho": "https://loja.exemplo.com/carrinho",
                     "valor_carrinho": "R$ 389,70", "link_loja": sender.get("store_url") or "", "descadastro": "https://exemplo.com/descadastro"}
        html, _ = email_builder.render(design, sender, variables, items=items)
        subject = email_builder.fill(str(payload.get("email_subject") or "Você esqueceu alguns itens no carrinho"), variables)
        return {"ok": True, "subject": subject, "html": html}
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc
