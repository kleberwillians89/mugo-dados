from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Header, HTTPException, Query

from services.intelligence import (
    analysis_history,
    ask_intelligence,
    calculate_intelligence_snapshot,
    conversation_messages,
    generate_analysis,
    latest_analysis,
)
from services.tenant import require_user_id, resolve_client_id

router = APIRouter(prefix="/api/intelligence", tags=["intelligence"])


async def _context(
    client_id: str | None,
    x_client_id: str | None,
    authorization: str | None,
) -> tuple[str, str]:
    user_id = await require_user_id(authorization)
    resolved_client_id = await resolve_client_id(client_id or x_client_id, authorization)
    return resolved_client_id, user_id


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
        _raise_service_error(exc)
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
    cid, user_id = await _context(client_id, x_client_id, authorization)
    try:
        return await generate_analysis(
            client_id=cid,
            user_id=user_id,
            start=str(payload.get("start") or "") or None,
            end=str(payload.get("end") or "") or None,
            days=int(payload.get("days") or 30),
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
    cid, user_id = await _context(client_id, x_client_id, authorization)
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
