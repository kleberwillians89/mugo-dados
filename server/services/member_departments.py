"""Departamentos de cada profissional, para a Nova tarefa sugerir os responsáveis da área escolhida.

- Uma pessoa pode ter várias áreas; vale em todos os clientes (é da pessoa, não do cliente).
- Só quem administra usuários da empresa edita, e só de quem é integrante dessa empresa.
- Nunca deduz área por nome, e-mail ou histórico. Sem a tabela (migração 000158), tudo segue sem áreas.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .ig_supabase import sb_delete, sb_insert, sb_select

TABLE = "member_departments"
DEPARTMENTS = ("Atendimento", "CRM", "Criação", "Dados", "Design", "Desenvolvimento", "Estratégia", "Mídia", "Operações",
               "Redação", "Social Media")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def clean_departments(values: Any) -> List[str]:
    """Só áreas do catálogo, sem repetir (aceita maiúscula/minúscula diferente). Puro, para teste."""
    by_key = {d.lower(): d for d in DEPARTMENTS}
    out: List[str] = []
    for value in values if isinstance(values, list) else []:
        name = by_key.get(str(value or "").strip().lower())
        if name and name not in out:
            out.append(name)
    return out


async def departments_of(user_ids: List[str]) -> Dict[str, List[str]]:
    ids = sorted({u for u in user_ids if _UUID.match(str(u or ""))})
    out: Dict[str, List[str]] = {u: [] for u in ids}
    if not ids:
        return out
    try:
        for start in range(0, len(ids), 100):
            rows = await sb_select(TABLE, select="user_id,department", limit=1000,
                                   filters={"user_id": f"in.({','.join(ids[start:start + 100])})"})
            for r in rows:
                out.setdefault(str(r["user_id"]), []).append(str(r["department"]))
    except Exception as exc:  # noqa: BLE001 — migração 000158 pendente: sem áreas
        print(f"[member_departments] unavailable error_type={type(exc).__name__}")
    return {u: sorted(v) for u, v in out.items()}


async def set_departments(user_id: str, departments: Any, *, actor_id: Optional[str]) -> List[str]:
    if not _UUID.match(str(user_id or "")):
        raise ValueError("Usuário inválido.")
    wanted = clean_departments(departments)
    await sb_delete(TABLE, filters={"user_id": f"eq.{user_id}"})
    now = datetime.now(timezone.utc).isoformat()
    for name in wanted:
        await sb_insert(TABLE, {"user_id": user_id, "department": name, "updated_by": actor_id, "updated_at": now})
    return wanted
