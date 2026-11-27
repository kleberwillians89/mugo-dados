"""Kanban como fonte de contexto da produção (briefing "Integração do Kanban aos módulos de criação").

Duas peças compartilhadas, usadas por qualquer módulo (E-mail Marketing primeiro; Social Media, Mídia On, Redação depois):

- **Seletor**: as tarefas reais e autorizadas da empresa ATIVA (nunca de outra), com busca por título.
- **Leitor de contexto**: o briefing da tarefa de forma estruturada — do briefing de origem (``studio_briefs``,
  que guarda as tarefas que gerou) quando existe; senão, das linhas rotuladas das notas ("Objetivo: …").
  Sem IA: só lê o que está guardado.

E o vínculo (``task_work_links``): o que foi produzido a partir de cada tarefa, para retomar sem duplicar e para
"Ir para o job". A tarefa nunca muda de status por causa disso.
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Any, Dict, List, Optional

from .ig_supabase import sb_rpc, sb_select
from .studio_calendar import StudioError
from .studio_tasks import MULTI_COLUMNS, OPEN_STATUSES, TABLE as TASKS, _mine, list_tasks, task_view

LINKS = "task_work_links"
MODULES = ("email_marketing", "social_media", "midia_on", "redacao", "calendar", "whatsapp")
_UUID = re.compile(r"^[0-9a-fA-F-]{36}$")

# Entregável → módulo, por palavra (o briefing escreve em português livre: "E-mails promocionais", "Legendas"…).
MODULE_WORDS: Dict[str, tuple] = {
    "email_marketing": ("e-mail", "email", "newsletter", "mailing"),
    "social_media": ("legenda", "post", "reels", "reel", "stories", "story", "carrossel", "feed", "instagram", "tiktok", "roteiro"),
    "midia_on": ("anúncio", "anuncio", "ads", "google", "meta ads", "shopping", "tráfego", "trafego", "campanha paga", "mídia", "midia"),
    "redacao": ("landing", "texto", "artigo", "blog", "roteiro", "release", "copy", "página", "pagina"),
}
_LABELS = {"objetivo": "objective", "mensagem": "key_message", "público": "audience", "publico": "audience",
           "prazo": "deadline", "meta": "goal", "oferta": "offer", "entregáveis": "deliverables",
           "entregaveis": "deliverables", "não fazer": "avoid", "nao fazer": "avoid", "restrições": "avoid",
           "restricoes": "avoid"}
_ROLE_LINE = re.compile(r"^sua parte(?:\s*\(([^)]*)\))?\s*:\s*(.+)$", re.IGNORECASE)


def _text(value: Any, limit: int = 600) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _uuid(value: Any) -> str:
    value = _text(value, 40)
    if not _UUID.match(value):
        raise StudioError("TASK_NOT_FOUND", "Tarefa não encontrada.")
    return value


def deliverables_for(module: str, deliverables: List[str]) -> List[str]:
    """Os entregáveis do briefing que cabem neste módulo (na ordem do briefing)."""
    words = MODULE_WORDS.get(module, ())
    return [d for d in deliverables if any(w in d.lower() for w in words)]


def parse_notes(notes: str) -> Dict[str, Any]:
    """Tarefa sem briefing de origem: lê as linhas rotuladas das notas. O que não tiver rótulo vira o resumo."""
    out: Dict[str, Any] = {"deliverables": [], "avoid": []}
    free: List[str] = []
    for raw in str(notes or "").splitlines():
        line = raw.strip(" -•\t")
        if not line:
            continue
        role = _ROLE_LINE.match(line)
        if role:
            out["your_part"] = _text(role.group(2), 400)
            continue
        if line.lower().startswith("briefing:"):
            out.setdefault("title", _text(line.split(":", 1)[1], 120))
            continue
        label, sep, rest = line.partition(":")
        key = _LABELS.get(label.strip().lower()) if sep else None
        if key in ("deliverables", "avoid"):
            out[key] += [_text(x, 160) for x in re.split(r";|\n", rest) if _text(x)]
        elif key:
            out[key] = _text(rest, 400)
        else:
            free.append(line)
    if free:
        out["summary"] = _text(" ".join(free), 600)
    return out


async def _client_name(client_id: str) -> str:
    try:
        rows = await sb_select("clients", select="name,trade_name", filters={"id": f"eq.{client_id}"}, limit=1)
    except Exception:  # noqa: BLE001
        rows = []
    return (rows[0].get("trade_name") or rows[0].get("name")) if rows else ""


async def list_pickable(client_id: str, scope: Dict[str, Any], *, q: Optional[str] = None) -> Dict[str, Any]:
    """Seletor: tarefas abertas da empresa ativa que esta pessoa pode ver (a mesma regra do quadro)."""
    out = await list_tasks(client_id, limit=300, client_view=scope["client_view"], only_user=scope["only_user"])
    if not out.get("available"):
        return {"available": False, "client_name": "", "tasks": []}
    term = _text(q, 80).lower()
    tasks = [t for t in out["tasks"] if t["status"] in OPEN_STATUSES and (not term or term in t["title"].lower())]
    return {"available": True, "client_name": await _client_name(client_id),
            "tasks": [{"id": t["id"], "title": t["title"], "status": t["status"], "due_date": t["due_date"],
                       "category": t["category"], "assignees": [a["name"] for a in t.get("assignees") or []]} for t in tasks[:100]]}


async def authorized_task(client_id: str, task_id: str, scope: Dict[str, Any]) -> Dict[str, Any]:
    """A tarefa, só se esta pessoa a vê no quadro desta empresa. Fora disso: "não encontrada" (sem dizer se existe)."""
    tid = _uuid(task_id)
    rows = await sb_select(TASKS, select=MULTI_COLUMNS, filters={"client_id": f"eq.{client_id}", "id": f"eq.{tid}"}, limit=1)
    row = rows[0] if rows else None
    if not row or str(row.get("client_id")) != client_id:
        raise StudioError("TASK_NOT_FOUND", "Tarefa não encontrada.")
    if scope.get("client_view") and not row.get("visible_to_client"):
        raise StudioError("TASK_NOT_FOUND", "Tarefa não encontrada.")
    if scope.get("only_user") and not _mine(row, scope["only_user"]):
        raise StudioError("TASK_NOT_FOUND", "Tarefa não encontrada.")
    return row


async def _brief_of(client_id: str, task_id: str) -> Optional[Dict[str, Any]]:
    try:
        rows = await sb_select("studio_briefs", select="id,brief,request,tasks", limit=1, filters={
            "client_id": f"eq.{client_id}", "tasks": "cs." + json.dumps([{"task_id": task_id}], separators=(",", ":"))})
    except Exception as exc:  # noqa: BLE001 — sem briefing de origem, vale o que está nas notas
        print(f"[task_context] brief_lookup_failed client_id={client_id} {type(exc).__name__}")
        return None
    return rows[0] if rows else None


async def links_for(client_id: str, task_id: str, module: Optional[str] = None) -> List[Dict[str, Any]]:
    filters = {"client_id": f"eq.{client_id}", "task_id": f"eq.{task_id}"}
    if module:
        filters["module"] = f"eq.{module}"
    try:
        return await sb_select(LINKS, select="id,module,deliverable,record_id,operation_key,link_status,created_at",
                               filters={**filters, "link_status": "eq.linked"},
                               order="created_at.desc", limit=50)
    except Exception:  # noqa: BLE001 — compatibilidade somente durante rollout da 000166
        try:
            return await sb_select(LINKS, select="id,module,deliverable,record_id,created_at", filters=filters,
                                   order="created_at.desc", limit=50)
        except Exception as exc:  # noqa: BLE001 — sem a migração 000159: sem vínculos, nada quebra
            print(f"[task_context] links_unavailable client_id={client_id} {type(exc).__name__}")
            return []


def work_operation_key(module: str, deliverable: str = "", *, version: Optional[str] = None) -> str:
    raw = _text(deliverable, 160).casefold() or "default"
    normalized = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")[:100] or "default"
    return f"{module}:{normalized}" + (f":{_text(version, 40)}" if version else "")


async def claim_work(client_id: str, task_id: str, *, module: str, operation_key: str,
                     deliverable: str = "", brief_id: Optional[str] = None,
                     user_id: Optional[str] = None) -> Dict[str, Any]:
    if module not in MODULES:
        raise StudioError("MODULE_INVALID", "Módulo inválido.")
    token = str(uuid.uuid4())
    rows = await sb_rpc("claim_task_work_link", {
        "p_client_id": client_id, "p_task_id": task_id, "p_brief_id": brief_id,
        "p_module": module, "p_deliverable": _text(deliverable, 160),
        "p_operation_key": _text(operation_key, 160), "p_claim_token": token,
        "p_created_by": user_id,
    })
    row = rows[0] if isinstance(rows, list) and rows else rows if isinstance(rows, dict) else None
    if not row:
        raise StudioError("WORK_LINK_FAILED", "Não foi possível reservar este trabalho.")
    return {**row, "claim_token": token}


async def complete_work(claim: Dict[str, Any], record_id: str) -> Dict[str, Any]:
    rows = await sb_rpc("complete_task_work_link", {
        "p_link_id": claim["link_id"], "p_claim_token": claim["claim_token"],
        "p_record_id": str(record_id)[:80],
    })
    row = rows[0] if isinstance(rows, list) and rows else rows if isinstance(rows, dict) else None
    if not row:
        raise StudioError("WORK_LINK_FAILED", "O conteúdo foi criado, mas o vínculo não foi confirmado.")
    return row


async def fail_work(claim: Dict[str, Any]) -> None:
    try:
        await sb_rpc("fail_task_work_link", {
            "p_link_id": claim["link_id"], "p_claim_token": claim["claim_token"],
        })
    except Exception as exc:  # noqa: BLE001 - falha original continua sendo a resposta
        print(f"[task_context] claim_release_failed {type(exc).__name__}")


async def record_link(client_id: str, task_id: str, *, module: str, record_id: str, deliverable: str = "",
                      brief_id: Optional[str] = None, user_id: Optional[str] = None,
                      operation_key: Optional[str] = None) -> Dict[str, Any]:
    key = operation_key or work_operation_key(module, deliverable, version=str(record_id))
    claim = await claim_work(client_id, task_id, module=module, operation_key=key, deliverable=deliverable,
                             brief_id=brief_id, user_id=user_id)
    if claim.get("link_status") == "linked":
        if str(claim.get("record_id")) != str(record_id):
            raise StudioError("WORK_ALREADY_LINKED", "Esta operação já está vinculada a outro conteúdo.")
        return claim
    if not claim.get("acquired"):
        raise StudioError("WORK_IN_PROGRESS", "Este conteúdo já está sendo criado. Aguarde e atualize a tela.")
    return await complete_work(claim, record_id)


async def task_context(client_id: str, task_id: str, scope: Dict[str, Any], *, module: Optional[str] = None) -> Dict[str, Any]:
    """Leitor de contexto: briefing estruturado da tarefa, entregáveis deste módulo e o que já foi produzido."""
    row = await authorized_task(client_id, task_id, scope)
    view = task_view(row, client_view=bool(scope.get("client_view")))
    notes = str(row.get("notes") or "")
    parsed = parse_notes(notes)
    source = await _brief_of(client_id, view["id"])
    brief: Dict[str, Any] = {}
    your_part = parsed.get("your_part")
    if source:
        b = source.get("brief") or {}
        brief = {k: b.get(k) for k in ("title", "summary", "objective", "key_message", "audience", "deadline", "goal")}
        brief["deliverables"] = list(b.get("deliverables") or [])
        brief["avoid"] = list(b.get("avoid") or [])
        role = next((t.get("role") for t in source.get("tasks") or [] if str(t.get("task_id")) == view["id"]), None)
        what = next((r.get("what") for r in b.get("roles") or [] if role and r.get("role") == role), None)
        your_part = what or your_part
    merged = {**{k: v for k, v in parsed.items() if k != "your_part"}, **{k: v for k, v in brief.items() if v}}
    merged["deliverables"] = brief.get("deliverables") or parsed.get("deliverables") or []
    merged["avoid"] = brief.get("avoid") or parsed.get("avoid") or []
    merged.setdefault("title", view["title"])
    fits = deliverables_for(module, merged["deliverables"]) if module else []
    links = await links_for(client_id, view["id"], module)
    return {
        "client_id": client_id, "client_name": await _client_name(client_id),
        "task": {k: view.get(k) for k in ("id", "title", "status", "due_date", "category", "deliverable_url", "assignees")},
        "brief_id": str(source["id"]) if source else None, "source": "briefing" if source else "notas",
        "context": {**merged, "your_part": your_part or None, "notes": notes[:4000]},
        "module": module, "deliverables_for_module": fits, "suggested_deliverable": fits[0] if len(fits) == 1 else None,
        "links": links,
    }


def max_percent_allowed(avoid: List[str], extra: str = "") -> Optional[int]:
    """Limite de desconto escrito nas restrições ("não prometer descontos superiores a 50%", "até 50% off")."""
    text = " ".join([*avoid, extra]).lower()
    found = re.findall(r"(?:superior(?:es)?\s+a|acima\s+de|mais\s+de|maior(?:es)?\s+que|até|ate)\s*(\d{1,2})\s*%", text)
    return min(int(x) for x in found) if found else None


def percents_over(text: str, limit: Optional[int]) -> List[int]:
    if limit is None:
        return []
    return sorted({int(x) for x in re.findall(r"(\d{1,3})\s*%", str(text or "")) if int(x) > limit})
