from __future__ import annotations

import time
from typing import Any, Dict

from fastapi import APIRouter, Header, HTTPException, Query

from api_support import get_request_id
from services.intelligence import (
    LOG_STAGE_AUTHORIZATION,
    STAGE_CONTEXT,
    analysis_history,
    ask_intelligence,
    calculate_intelligence_snapshot,
    conversation_messages,
    generate_analysis,
    latest_analysis,
    log_request_started,
    log_stage_completed,
    log_stage_failed,
)
from services.business_context import load_business_context, save_business_context
from services.tenant import require_client_role, require_user_id, resolve_client_id

router = APIRouter(prefix="/api/intelligence", tags=["intelligence"])


async def _context(
    client_id: str | None,
    x_client_id: str | None,
    authorization: str | None,
) -> tuple[str, str]:
    """Leitura: qualquer membro da empresa, inclusive viewer."""
    user_id = await require_user_id(authorization)
    resolved_client_id = await resolve_client_id(client_id or x_client_id, authorization)
    return resolved_client_id, user_id


async def _mutation_context(
    client_id: str | None,
    x_client_id: str | None,
    authorization: str | None,
) -> tuple[str, str]:
    """Mutação: gerar análise e perguntar gravam linha e consomem o provedor
    de IA, então exigem papel de gestão. Viewer é recusado por
    require_client_role, a mesma regra que já protege o contexto de negócio.
    """
    resolved_client_id = await require_client_role(client_id or x_client_id, authorization)
    user_id = await require_user_id(authorization)
    return resolved_client_id, user_id


def _log_stage_error(*, endpoint: str, client_id: str, stage: str, exc: BaseException) -> None:
    """Etapa e tipo do erro no log do servidor; nada sensível, nada ao cliente."""
    print(
        f"[intelligence][route] endpoint={endpoint} client_id={client_id} stage={stage} "
        f"status=error error_type={exc.__class__.__name__} code={str(exc)[:80]}"
    )


def _raise_service_error(exc: RuntimeError) -> None:
    code = str(exc or "INTELLIGENCE_ERROR")
    if code == "AI_PROVIDER_NOT_CONFIGURED":
        raise HTTPException(
            status_code=503,
            detail="O provedor de IA ainda não está configurado no backend.",
        ) from exc
    if code == "CONVERSATION_NOT_FOUND":
        raise HTTPException(status_code=404, detail="Conversa não encontrada para este usuário e empresa.") from exc
    if code in {"QUESTION_INVALID", "CONVERSATION_CREATE_FAILED"} or "Período inválido" in code:
        raise HTTPException(status_code=400, detail=code) from exc
    raise HTTPException(
        status_code=502,
        detail="A análise não pôde ser concluída agora. Os demais dados continuam disponíveis.",
    ) from exc


@router.get("/business-context")
async def intelligence_business_context(
    client_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    # Contexto da empresa: qualquer membro lê, inclusive viewer.
    cid, _ = await _context(client_id, x_client_id, authorization)
    return {"ok": True, "client_id": cid, **await load_business_context(cid)}


@router.put("/business-context")
async def intelligence_save_business_context(
    payload: Dict[str, Any],
    client_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    # Escrever é mutação: viewer é recusado por require_client_role.
    cid = await require_client_role(client_id or x_client_id, authorization)
    user_id = await require_user_id(authorization)
    try:
        saved = await save_business_context(client_id=cid, user_id=user_id, payload=payload)
    except RuntimeError as exc:
        _raise_service_error(exc)
    return {"ok": True, "client_id": cid, **saved}


@router.get("/context")
async def intelligence_context(
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=366),
    client_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    cid, _ = await _context(client_id, x_client_id, authorization)
    try:
        snapshot = await calculate_intelligence_snapshot(
            client_id=cid, start=start, end=end, days=days,
        )
    except RuntimeError as exc:
        _log_stage_error(endpoint="/api/intelligence/context", client_id=cid, stage=STAGE_CONTEXT, exc=exc)
        _raise_service_error(exc)
    except Exception as exc:
        # Erro não previsto na montagem do contexto: etapa identificada no log,
        # mensagem genérica para o cliente.
        _log_stage_error(endpoint="/api/intelligence/context", client_id=cid, stage=STAGE_CONTEXT, exc=exc)
        raise HTTPException(
            status_code=502,
            detail="A leitura dos dados não pôde ser concluída agora. Tente novamente em instantes.",
        ) from exc
    return {"ok": True, "snapshot": snapshot}


@router.get("/latest")
async def intelligence_latest(
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    client_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    cid, _ = await _context(client_id, x_client_id, authorization)
    try:
        return await latest_analysis(cid, start, end)
    except RuntimeError as exc:
        _raise_service_error(exc)


@router.post("/analyses")
async def intelligence_generate(
    payload: Dict[str, Any],
    client_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    # request_id é o mesmo que o middleware [http] imprime e devolve no
    # header X-Request-ID: liga a linha do HTTP às etapas da análise.
    request_id = get_request_id()
    start = str(payload.get("start") or "") or None
    end = str(payload.get("end") or "") or None
    log_request_started(
        request_id=request_id,
        client_id=(client_id or x_client_id or "-"),
        period_start=start,
        period_end=end,
    )
    authorization_started = time.monotonic()
    try:
        cid, user_id = await _mutation_context(client_id, x_client_id, authorization)
    except BaseException as exc:
        log_stage_failed(
            stage=LOG_STAGE_AUTHORIZATION,
            request_id=request_id,
            elapsed_ms=int((time.monotonic() - authorization_started) * 1000),
            exc=exc,
        )
        raise
    log_stage_completed(
        stage=LOG_STAGE_AUTHORIZATION,
        request_id=request_id,
        elapsed_ms=int((time.monotonic() - authorization_started) * 1000),
        client_id=cid,
    )
    try:
        return await generate_analysis(
            client_id=cid,
            user_id=user_id,
            start=start,
            end=end,
            days=int(payload.get("days") or 30),
            request_id=request_id,
        )
    except RuntimeError as exc:
        _raise_service_error(exc)


@router.get("/history")
async def intelligence_history(
    limit: int = Query(default=20, ge=1, le=100),
    client_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    cid, _ = await _context(client_id, x_client_id, authorization)
    return await analysis_history(cid, limit)


@router.post("/ask")
async def intelligence_ask(
    payload: Dict[str, Any],
    client_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    cid, user_id = await _mutation_context(client_id, x_client_id, authorization)
    try:
        return await ask_intelligence(
            client_id=cid,
            user_id=user_id,
            question=str(payload.get("question") or ""),
            conversation_id=str(payload.get("conversation_id") or "") or None,
            start=str(payload.get("start") or "") or None,
            end=str(payload.get("end") or "") or None,
        )
    except RuntimeError as exc:
        _raise_service_error(exc)


@router.get("/conversations/{conversation_id}/messages")
async def intelligence_messages(
    conversation_id: str,
    client_id: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    authorization: str | None = Header(default=None),
):
    cid, user_id = await _context(client_id, x_client_id, authorization)
    try:
        return await conversation_messages(cid, user_id, conversation_id)
    except RuntimeError as exc:
        _raise_service_error(exc)
