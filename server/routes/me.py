"""Rotas da pessoa logada, entre empresas. A pessoa vem só da sessão (Authorization)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header, HTTPException

from services import my_tasks
from services.studio_calendar import StudioError
from services.tenant import require_user_id

router = APIRouter(prefix="/api/me", tags=["me"])


@router.get("/tasks")
async def me_tasks(client_id: Optional[str] = None, status: Optional[str] = None, q: Optional[str] = None,
                   authorization: Optional[str] = Header(None)):
    uid = await require_user_id(authorization)
    try:
        return await my_tasks.list_my_tasks(uid, client_id=(client_id or "").strip() or None, status=status, q=q)
    except StudioError as exc:
        if exc.code == "STATUS_INVALID":
            raise HTTPException(status_code=400, detail="Status de tarefa inválido.") from None
        raise HTTPException(status_code=403, detail="Sem acesso.") from None
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — erro de leitura nunca vira lista vazia
        print(f"[me_tasks] failed user_id={uid} {type(exc).__name__}")
        raise HTTPException(status_code=503, detail="Não foi possível carregar suas tarefas agora. Tente de novo.") from None
