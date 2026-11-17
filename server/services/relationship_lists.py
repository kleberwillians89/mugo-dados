"""Listas segmentadas do Relacionamento (somente hashes, isoladas por tenant).

Pertencer a uma lista não é autorização de marketing: a elegibilidade é
confirmada de novo na fonte da loja + supressões antes de cada envio.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Set

from .ig_supabase import sb_delete, sb_insert, sb_select, sb_upsert
from .sales_by_origin import _paged

LISTS = "relationship_lists"
MEMBERS = "relationship_list_members"
_UUID = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$", re.I)


class ListError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def valid_id(value: Any) -> str:
    item = str(value or "").strip()
    if not _UUID.fullmatch(item):
        raise ListError("Lista inválida.", 422)
    return item


async def get_list(client_id: str, list_id: str) -> Dict[str, Any]:
    rows = await sb_select(LISTS, select="id,name,description,created_at",
                           filters={"client_id": f"eq.{client_id}", "id": f"eq.{valid_id(list_id)}"}, limit=1)
    if not rows:
        raise ListError("Lista não encontrada nesta empresa.", 404)
    return rows[0]


async def list_lists(client_id: str) -> List[Dict[str, Any]]:
    return await sb_select(LISTS, select="id,name,description,created_at", filters={"client_id": f"eq.{client_id}"},
                           order="created_at.desc", limit=100)


async def create_list(client_id: str, *, name: str, description: str = "", user_id: str | None = None) -> Dict[str, Any]:
    name = " ".join(str(name).split())[:100]
    if not name:
        raise ListError("Informe um nome para a lista.", 422)
    row = await sb_insert(LISTS, {"client_id": client_id, "name": name,
                                 "description": str(description or "").strip()[:300], "created_by": user_id})
    return await get_list(client_id, row["id"])


async def delete_list(client_id: str, list_id: str) -> None:
    await get_list(client_id, list_id)
    await sb_delete(LISTS, filters={"client_id": f"eq.{client_id}", "id": f"eq.{list_id}"}, returning="minimal")


async def member_hashes(client_id: str, list_id: str) -> Set[str]:
    await get_list(client_id, list_id)
    rows, truncated = await _paged(MEMBERS, select="email_hash",
                                  filters={"client_id": f"eq.{client_id}", "list_id": f"eq.{list_id}"},
                                  order="email_hash.asc", max_rows=200_000)
    if truncated:
        raise ListError("Lista grande demais para conferir integralmente. Divida em listas menores.", 422)
    return {r["email_hash"] for r in rows}


async def add_members(client_id: str, list_id: str, emails: Any) -> Dict[str, int]:
    await get_list(client_id, list_id)
    if not isinstance(emails, list) or not 1 <= len(emails) <= 500:
        raise ListError("Envie entre 1 e 500 e-mails por lote.", 422)
    from .email_marketing import email_hash, valid_email
    hashes = set()
    for raw in emails:
        email = valid_email(raw)
        if not email:
            raise ListError("Há um e-mail inválido na lista. Corrija e tente novamente.", 422)
        hashes.add(email_hash(email))
    rows = [{"client_id": client_id, "list_id": list_id, "email_hash": h} for h in sorted(hashes)]
    for i in range(0, len(rows), 200):
        await sb_upsert(MEMBERS, rows[i:i + 200], on_conflict="client_id,list_id,email_hash")
    return {"accepted": len(rows), "duplicates_in_input": len(emails) - len(rows)}
