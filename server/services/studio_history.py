"""Histórico de cada pauta: quem fez o quê e quando (kanban interno da equipe).

Grava um evento por ação: criou, editou o texto, trocou a arte, mudou a data, moveu de etapa, enviou ao cliente,
o cliente aprovou/pediu ajuste/editou/comentou, agendou, publicou (ou falhou). Nunca derruba a ação principal:
se a migração 000080 não estiver aplicada ou o banco falhar, só não registra.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo

from .ig_supabase import sb_insert, sb_select

TABLE = "studio_item_events"
SAO_PAULO = ZoneInfo("America/Sao_Paulo")
STATUS_LABEL = {"rascunho": "Rascunho", "em_revisao": "Em revisão", "aprovado": "Aprovado", "rejeitado": "Ajuste pedido", "publicado": "Publicado"}
FORMAT_LABEL = {"reels": "Reels", "carrossel": "Carrossel", "imagem": "Imagem", "stories": "Stories", "video": "Vídeo"}
TEXT_FIELDS = {"title": "título", "hook": "gancho", "caption_draft": "legenda", "pillar": "pilar", "rationale": "motivo"}


def _when(value: Any) -> str:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(SAO_PAULO).strftime("%d/%m às %H:%M")
    except (TypeError, ValueError):
        return ""


def _same(key: str, old: Any, new: Any) -> bool:
    if key == "scheduled_at":
        try:
            a = datetime.fromisoformat(str(old).replace("Z", "+00:00"))
            b = datetime.fromisoformat(str(new).replace("Z", "+00:00"))
            if b.tzinfo is None:
                b = b.replace(tzinfo=SAO_PAULO)
            return a == b
        except (TypeError, ValueError):
            return False
    if key == "collaborators":
        return [str(x).lower().lstrip("@") for x in (old or [])] == [str(x).lower().lstrip("@") for x in (new or [])]
    return (str(old).strip() if old is not None else "") == (str(new).strip() if new is not None else "")


def changed_fields(before: Optional[Dict[str, Any]], patch: Dict[str, Any]) -> Dict[str, Any]:
    """Só o que mudou de verdade (a tela manda todos os campos a cada salvar)."""
    if not before:
        return dict(patch)
    return {k: v for k, v in patch.items() if not _same(k, before.get(k), v)}


def describe_patch(patch: Dict[str, Any]) -> List[str]:
    """Frases do que mudou numa edição da equipe (uma por tipo de mudança)."""
    out: List[str] = []
    if patch.get("status"):
        out.append(f"moveu para {STATUS_LABEL.get(patch['status'], patch['status'])}")
    if "art_url" in patch:
        out.append("trocou a arte" if patch.get("art_url") else "tirou a arte")
    if patch.get("scheduled_at"):
        out.append(f"mudou a data para {_when(patch['scheduled_at'])}".strip())
    if patch.get("format"):
        out.append(f"mudou o formato para {FORMAT_LABEL.get(patch['format'], patch['format'])}")
    if "collaborators" in patch:
        names = [f"@{c}" for c in patch.get("collaborators") or []]
        out.append(f"marcou colaborador{'es' if len(names) > 1 else ''} {', '.join(names)}" if names else "tirou os colaboradores")
    edited = [label for key, label in TEXT_FIELDS.items() if key in patch]
    if edited:
        out.append(f"editou {', '.join(edited)}")
    return out


async def record(client_id: str, item_id: Optional[str], action: str, *, actor_name: Optional[str], side: str = "mugo",
                 actor_id: Optional[str] = None, detail: Optional[str] = None) -> None:
    if not item_id:
        return
    try:
        await sb_insert(TABLE, {"client_id": client_id, "item_id": str(item_id), "action": action[:200],
                                "actor_name": (actor_name or ("Cliente" if side == "cliente" else "Equipe Mugô"))[:80],
                                "actor_side": side if side in ("mugo", "cliente", "sistema") else "mugo",
                                "actor_id": actor_id, "detail": (detail or None) and str(detail)[:1000]})
    except Exception as exc:  # noqa: BLE001 — histórico é complemento
        print(f"[studio_history] record_failed client_id={client_id} error_type={exc.__class__.__name__}")


async def record_many(client_id: str, item_id: Optional[str], actions: Iterable[str], **kw: Any) -> None:
    for action in actions:
        await record(client_id, item_id, action, **kw)


async def list_item(client_id: str, item_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    try:
        return await sb_select(TABLE, select="id,action,actor_name,actor_side,detail,created_at", order="created_at.desc", limit=limit,
                               filters={"client_id": f"eq.{client_id}", "item_id": f"eq.{item_id}"})
    except Exception:  # noqa: BLE001
        return []


async def latest_by_item(client_id: str, limit: int = 400) -> Dict[str, Dict[str, Any]]:
    """Último evento de cada pauta (para o cartão do kanban)."""
    try:
        rows = await sb_select(TABLE, select="item_id,action,actor_name,actor_side,created_at", order="created_at.desc", limit=limit,
                               filters={"client_id": f"eq.{client_id}"})
    except Exception:  # noqa: BLE001
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        out.setdefault(str(r["item_id"]), r)
    return out
