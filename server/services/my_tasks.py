"""Minhas Tarefas: as tarefas em que a pessoa logada é RESPONSÁVEL, em todas as empresas que ela pode ver.

Regras (spec do Danilo, PR 2):
- A pessoa vem só da sessão (nunca de parâmetro). Casa por assignee_user_ids / assignee_user_id — não por quem criou,
  nem por nome ou e-mail.
- Empresas: as mesmas do seletor (list_clients_for_user). Equipe Mugô (admin da agência, plataforma ou gestora da
  conta) vê a tarefa inteira; membro de empresa precisa do módulo Tarefas ativo e, se só "vê como cliente"
  (tasks.all sem tasks.approve), vê apenas as tarefas visíveis ao cliente — igual ao quadro daquela empresa.
- Erro de leitura levanta (a tela mostra erro, nunca "nenhuma tarefa").
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Set

from .ig_supabase import sb_select
from .studio_calendar import StudioError
from .studio_tasks import MULTI_COLUMNS, OPEN_STATUSES, SCOPED_COLUMNS, STATUSES, TABLE, task_view

FULL_ROLES = {"agency_admin", "platform_admin", "account_manager"}
MAX_ROWS = 500
_UUID = re.compile(r"^[0-9a-fA-F-]{36}$")


def clean_search(q: Optional[str]) -> str:
    """Busca no título: só letras, números, espaço e hífen (nada que mude o filtro do PostgREST)."""
    return " ".join(re.sub(r"[^\w\s-]", " ", str(q or ""), flags=re.UNICODE).split())[:80]


async def _client_scope(user_id: str, clients: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """{client_id: {"name", "visible_only"}} das empresas onde a pessoa pode ver tarefas."""
    from .team_access import member_access
    out: Dict[str, Dict[str, Any]] = {}
    for c in clients:
        cid = str(c.get("client_id") or "").strip()
        if not cid:
            continue
        role = str(c.get("role") or "").strip()
        name = c.get("name") or "Sem nome"
        if role in FULL_ROLES:
            out[cid] = {"name": name, "visible_only": False}
            continue
        try:
            access = await member_access(cid, user_id, role=role)
        except Exception as exc:  # noqa: BLE001 — sem conseguir conferir, a empresa fica de fora (nunca abre a mais)
            print(f"[my_tasks] access_unavailable client_id={cid} {type(exc).__name__}")
            continue
        if not access or access.get("status") != "active":
            continue
        codes = set(access.get("codes") or [])
        if "tasks.view" not in codes and "tasks.edit" not in codes:
            continue
        out[cid] = {"name": name, "visible_only": "tasks.all" in codes and "tasks.approve" not in codes}
    return out


async def _rows(user_id: str, client_ids: List[str], filters: Dict[str, str]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for offset in range(0, len(client_ids), 100):
        batch = client_ids[offset:offset + 100]
        base = {**filters, "client_id": "in.(" + ",".join(json.dumps(cid) for cid in batch) + ")"}
        kwargs = dict(order="due_date.asc.nullslast,created_at.asc", limit=MAX_ROWS)
        try:
            rows += await sb_select(TABLE, select=MULTI_COLUMNS, filters={
                **base, "or": f"(assignee_user_ids.cs.{{{user_id}}},assignee_user_id.eq.{user_id})"}, **kwargs)
        except Exception:  # noqa: BLE001 — sem a migração 000116: só o responsável único
            rows += await sb_select(TABLE, select=SCOPED_COLUMNS,
                                    filters={**base, "assignee_user_id": f"eq.{user_id}"}, **kwargs)
    return rows


def _is_mine(row: Dict[str, Any], user_id: str) -> bool:
    return (str(row.get("assignee_user_id") or "") == user_id
            or user_id in {str(uid) for uid in (row.get("assignee_user_ids") or [])})


async def list_my_tasks(user_id: str, *, client_id: Optional[str] = None, status: Optional[str] = None,
                        q: Optional[str] = None) -> Dict[str, Any]:
    """status: None/"open" = abertas; "completed"/"cancelled"/etapa específica = só essa."""
    from .clients import list_clients_for_user
    uid = str(user_id or "").strip()
    if not _UUID.match(uid):
        raise StudioError("FORBIDDEN")
    if status and status != "open" and status not in STATUSES:
        raise StudioError("STATUS_INVALID")
    listed = (await list_clients_for_user(uid)).get("clients") or []
    scope = await _client_scope(uid, listed)
    clients = [{"client_id": cid, "name": info["name"]} for cid, info in scope.items()]
    wanted = [cid for cid in scope if not client_id or cid == client_id]
    if client_id and not wanted:
        # Empresa que a pessoa não pode ver: lista vazia, sem dizer se a empresa existe.
        return {"ok": True, "tasks": [], "clients": clients, "truncated": False}
    filters = {"status": f"eq.{status}" if status and status != "open" else f"in.({','.join(OPEN_STATUSES)})"}
    term = clean_search(q)
    if term:
        filters["title"] = f"ilike.*{term}*"
    rows = await _rows(uid, wanted, filters) if wanted else []
    tasks = []
    for row in rows:
        cid = str(row.get("client_id") or "")
        info = scope.get(cid)
        if not info or not _is_mine(row, uid):
            continue  # defesa extra: nada fora das empresas permitidas nem de outra pessoa
        if info["visible_only"] and not row.get("visible_to_client"):
            continue
        tasks.append({**task_view(row, client_view=info["visible_only"]), "client_id": cid, "client_name": info["name"]})
    return {"ok": True, "tasks": tasks, "clients": clients, "truncated": len(rows) >= MAX_ROWS}
