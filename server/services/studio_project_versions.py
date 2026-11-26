"""Versões do Planejamento (e do Evento): refazer com IA nunca apaga o plano anterior.

Regras:
* antes de a IA refazer, o plano atual vira versão (se ainda não estiver guardado igual) — inclusive o que foi
  editado à mão; sem conseguir guardar, a IA NÃO refaz (nada é substituído em silêncio);
* o plano novo da IA vira a versão seguinte; aprovar (etapa "Finalizado") grava a versão aprovada;
* restaurar uma versão antiga grava a atual e cria uma versão nova com o conteúdo antigo (o histórico só cresce);
* cada versão guarda plano, entradas, título, etapa, número, data e autor.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .ig_supabase import sb_insert, sb_select

TABLE = "studio_project_versions"
ORIGIN_LABEL = {"ia": "Gerada pela IA", "edicao": "Edição da equipe", "aprovada": "Versão aprovada", "restaurada": "Restaurada"}


class VersionsUnavailable(RuntimeError):
    """Tabela de versões indisponível (migração 000149 não aplicada)."""


def _same(a: Any, b: Any) -> bool:
    return json.dumps(a or {}, sort_keys=True, ensure_ascii=False, default=str) == json.dumps(b or {}, sort_keys=True, ensure_ascii=False, default=str)


def has_plan(project: Dict[str, Any]) -> bool:
    return bool(project.get("plan") and any(k != "research" for k in project["plan"]))


async def _rows(project_id: str, *, select: str, limit: int) -> List[Dict[str, Any]]:
    try:
        return await sb_select(TABLE, select=select, filters={"project_id": f"eq.{project_id}"}, order="version.desc", limit=limit) or []
    except Exception as exc:  # noqa: BLE001
        raise VersionsUnavailable(str(exc)[:120]) from None


async def latest(project_id: str) -> Optional[Dict[str, Any]]:
    rows = await _rows(project_id, select="version,plan,inputs,title,status,origin", limit=1)
    return rows[0] if rows else None


async def snapshot(client_id: str, project: Dict[str, Any], *, origin: str, user_id: Optional[str], user_name: Optional[str],
                   note: Optional[str] = None, force: bool = False) -> Optional[int]:
    """Grava o estado do projeto como versão nova. Sem mudança desde a última versão, não duplica (salvo ``force``)."""
    if origin not in ORIGIN_LABEL or not has_plan(project):
        return None
    last = await latest(str(project["id"]))
    if last and not force and _same(last.get("plan"), project.get("plan")) and _same(last.get("inputs"), project.get("inputs")):
        return int(last["version"])
    number = int(last["version"]) + 1 if last else 1
    try:
        await sb_insert(TABLE, {"client_id": client_id, "project_id": str(project["id"]), "version": number, "origin": origin,
                                "title": project.get("title"), "status": project.get("status"), "inputs": project.get("inputs") or {},
                                "plan": project.get("plan") or {}, "note": (note or None) and str(note)[:600],
                                "created_by": user_id, "created_by_name": (user_name or None) and str(user_name)[:120]},
                        returning="minimal")
    except Exception as exc:  # noqa: BLE001
        raise VersionsUnavailable(str(exc)[:120]) from None
    return number


async def list_versions(client_id: str, project_id: str) -> List[Dict[str, Any]]:
    rows = await _rows(project_id, select="version,origin,title,status,note,created_by_name,created_at,client_id", limit=100)
    return [{"version": r["version"], "origin": r["origin"], "origin_label": ORIGIN_LABEL.get(r["origin"], r["origin"]),
             "title": r.get("title"), "status": r.get("status"), "note": r.get("note"), "author": r.get("created_by_name") or "Equipe",
             "created_at": r.get("created_at")} for r in rows if r.get("client_id") == client_id]


async def get_version(client_id: str, project_id: str, version: int) -> Optional[Dict[str, Any]]:
    try:
        rows = await sb_select(TABLE, select="*", filters={"project_id": f"eq.{project_id}", "version": f"eq.{int(version)}",
                                                           "client_id": f"eq.{client_id}"}, limit=1)
    except Exception as exc:  # noqa: BLE001
        raise VersionsUnavailable(str(exc)[:120]) from None
    if not rows:
        return None
    r = rows[0]
    return {"version": r["version"], "origin": r["origin"], "origin_label": ORIGIN_LABEL.get(r["origin"], r["origin"]),
            "title": r.get("title"), "status": r.get("status"), "inputs": r.get("inputs") or {}, "plan": r.get("plan") or {},
            "note": r.get("note"), "author": r.get("created_by_name") or "Equipe", "created_at": r.get("created_at")}
