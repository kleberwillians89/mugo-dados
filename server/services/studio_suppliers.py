"""Fornecedores (aba do Evento): quem a marca já usa para produzir — buffet, foto, vídeo, som e luz, estrutura…

* Cadastro por empresa (``studio_suppliers``): nome, categoria, contato, cidade, faixa de preço, nota e observações.
* Ligação com o evento (``studio_project_suppliers``): cada evento tem os fornecedores dele, com o que cada um faz,
  o status (cotando → contratado → confirmado, ou cancelado) e o valor. "Lançar no orçamento" põe o valor no
  orçamento do plano, na categoria certa, sem duplicar.
* A IA do plano lê os fornecedores cadastrados (nome, categoria, cidade, preço e nota; nunca telefone nem e-mail)
  e os já ligados ao evento: usa quem existe antes de sugerir contratar, e o valor fechado no orçamento.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .ig_supabase import sb_delete, sb_insert, sb_select, sb_update
from .studio_calendar import StudioError

SUPPLIERS = "studio_suppliers"
LINKS = "studio_project_suppliers"
CATEGORIES: Dict[str, str] = {
    "buffet": "Buffet e alimentação", "bebidas": "Bebidas e bar", "fotografia": "Fotografia", "video": "Vídeo e filmagem",
    "som_luz": "Som, luz e DJ", "estrutura": "Estrutura, palco e tendas", "decoracao": "Decoração e cenografia",
    "espaco": "Espaço e locação", "seguranca": "Segurança", "limpeza": "Limpeza", "transporte": "Transporte e logística",
    "staff": "Recepção e staff", "brindes": "Brindes", "impressao": "Impressão e sinalização", "talentos": "Talentos e modelos",
    "outros": "Outros",
}
LINK_STATUSES = ("cotando", "contratado", "confirmado", "cancelado")
# Categoria do fornecedor → categoria do orçamento do Evento.
BUDGET_CATEGORY = {
    "buffet": "logistica", "bebidas": "logistica", "fotografia": "equipe", "video": "equipe", "som_luz": "equipamento",
    "estrutura": "equipamento", "decoracao": "locacao", "espaco": "locacao", "seguranca": "equipe", "limpeza": "equipe",
    "transporte": "logistica", "staff": "equipe", "brindes": "outros", "impressao": "outros", "talentos": "equipe", "outros": "outros",
}
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _t(value: Any, n: int) -> str:
    return " ".join(str(value or "").split())[:n]


def _money(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    from .studio_briefs import parse_brl
    number = float(value) if isinstance(value, (int, float)) else parse_brl(value)
    if number is None or number < 0 or number > 100_000_000:
        raise StudioError("SUPPLIER_VALUE_INVALID", "Valor inválido.")
    return round(number, 2)


# ------------------------------------------------------------------ cadastro

def clean_supplier(data: Dict[str, Any], *, partial: bool = False) -> Dict[str, Any]:
    row: Dict[str, Any] = {}
    if "name" in data or not partial:
        name = _t(data.get("name"), 120)
        if not name:
            raise StudioError("SUPPLIER_NAME_REQUIRED", "Dê o nome do fornecedor.")
        row["name"] = name
    if "category" in data or not partial:
        category = data.get("category") or "outros"
        if category not in CATEGORIES:
            raise StudioError("SUPPLIER_CATEGORY_INVALID", "Categoria inválida.")
        row["category"] = category
    for key, limit in (("contact_name", 120), ("phone", 40), ("city", 120), ("price_note", 200), ("notes", 1000), ("website", 300)):
        if key in data:
            row[key] = _t(data.get(key), limit) or None
    if "email" in data:
        email = _t(data.get("email"), 200).lower()
        if email and not _EMAIL.match(email):
            raise StudioError("SUPPLIER_EMAIL_INVALID", "E-mail inválido.")
        row["email"] = email or None
    if row.get("website") and not row["website"].startswith(("https://", "http://")):
        row["website"] = f"https://{row['website']}"
    if "rating" in data:
        rating = data.get("rating")
        if rating in (None, "", 0):
            row["rating"] = None
        else:
            try:
                rating = int(rating)
            except (TypeError, ValueError):
                raise StudioError("SUPPLIER_RATING_INVALID", "Nota de 1 a 5.") from None
            if not 1 <= rating <= 5:
                raise StudioError("SUPPLIER_RATING_INVALID", "Nota de 1 a 5.")
            row["rating"] = rating
    if "active" in data:
        row["active"] = bool(data.get("active"))
    return row


async def list_suppliers(client_id: str, *, include_inactive: bool = True) -> List[Dict[str, Any]]:
    filters = {"client_id": f"eq.{client_id}"}
    if not include_inactive:
        filters["active"] = "eq.true"
    return await sb_select(SUPPLIERS, select="*", filters=filters, order="name.asc", limit=500)


async def _supplier(client_id: str, supplier_id: str) -> Dict[str, Any]:
    rows = await sb_select(SUPPLIERS, select="*", filters={"client_id": f"eq.{client_id}", "id": f"eq.{supplier_id}"}, limit=1)
    if not rows:
        raise StudioError("SUPPLIER_NOT_FOUND", "Fornecedor não encontrado.")
    return rows[0]


async def create_supplier(client_id: str, data: Dict[str, Any], *, user_id: str) -> Dict[str, Any]:
    row = await sb_insert(SUPPLIERS, {"client_id": client_id, "created_by": user_id, "active": True, **clean_supplier(data)})
    if not row:
        raise StudioError("SUPPLIER_SAVE_FAILED", "Não foi possível salvar.")
    return row


async def update_supplier(client_id: str, supplier_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    current = await _supplier(client_id, supplier_id)
    patch = {**clean_supplier(data, partial=True), "updated_at": _now()}
    rows = await sb_update(SUPPLIERS, filters={"client_id": f"eq.{client_id}", "id": f"eq.{supplier_id}"}, patch=patch)
    return rows[0] if rows else {**current, **patch}


async def delete_supplier(client_id: str, supplier_id: str) -> None:
    await _supplier(client_id, supplier_id)
    await sb_delete(SUPPLIERS, filters={"client_id": f"eq.{client_id}", "id": f"eq.{supplier_id}"}, returning="minimal")


# ------------------------------------------------------------------ ligação com o evento

async def _event(client_id: str, project_id: str) -> Dict[str, Any]:
    from .studio_projects import get_project
    project = await get_project(client_id, project_id)
    if project.get("kind") != "evento":
        raise StudioError("PROJECT_KIND_INVALID", "Fornecedores são do Evento.")
    return project


async def event_suppliers(client_id: str, project_id: str) -> List[Dict[str, Any]]:
    """Fornecedores ligados ao evento, cada um com os dados do cadastro."""
    links = await sb_select(LINKS, select="*", filters={"client_id": f"eq.{client_id}", "project_id": f"eq.{project_id}"},
                            order="created_at.asc", limit=100)
    if not links:
        return []
    ids = sorted({str(link["supplier_id"]) for link in links})
    suppliers = {str(s["id"]): s for s in await sb_select(SUPPLIERS, select="*", limit=len(ids),
                                                         filters={"client_id": f"eq.{client_id}", "id": f"in.({','.join(ids)})"})}
    return [{**link, "supplier": suppliers.get(str(link["supplier_id"]))} for link in links if suppliers.get(str(link["supplier_id"]))]


def clean_link(data: Dict[str, Any], *, partial: bool = False) -> Dict[str, Any]:
    row: Dict[str, Any] = {}
    if "item" in data or not partial:
        row["item"] = _t(data.get("item"), 160) or None
    if "status" in data or not partial:
        status = data.get("status") or "cotando"
        if status not in LINK_STATUSES:
            raise StudioError("SUPPLIER_STATUS_INVALID", "Status inválido.")
        row["status"] = status
    if "value" in data:
        row["value"] = _money(data.get("value"))
    if "notes" in data:
        row["notes"] = _t(data.get("notes"), 500) or None
    return row


async def link_supplier(client_id: str, project_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    await _event(client_id, project_id)
    supplier = await _supplier(client_id, str(data.get("supplier_id") or ""))
    existing = await sb_select(LINKS, select="id", limit=1,
                               filters={"client_id": f"eq.{client_id}", "project_id": f"eq.{project_id}", "supplier_id": f"eq.{supplier['id']}"})
    if existing:
        raise StudioError("SUPPLIER_ALREADY_LINKED", "Esse fornecedor já está no evento.")
    row = await sb_insert(LINKS, {"client_id": client_id, "project_id": project_id, "supplier_id": supplier["id"], **clean_link(data)})
    if not row:
        raise StudioError("SUPPLIER_SAVE_FAILED", "Não foi possível salvar.")
    return {**row, "supplier": supplier}


async def update_link(client_id: str, project_id: str, link_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    patch = {**clean_link(data, partial=True), "updated_at": _now()}
    rows = await sb_update(LINKS, filters={"client_id": f"eq.{client_id}", "project_id": f"eq.{project_id}", "id": f"eq.{link_id}"}, patch=patch)
    if not rows:
        raise StudioError("SUPPLIER_LINK_NOT_FOUND", "Fornecedor não está neste evento.")
    return rows[0]


async def unlink_supplier(client_id: str, project_id: str, link_id: str) -> None:
    await sb_delete(LINKS, filters={"client_id": f"eq.{client_id}", "project_id": f"eq.{project_id}", "id": f"eq.{link_id}"}, returning="minimal")


def budget_line(link: Dict[str, Any]) -> Dict[str, Any]:
    supplier = link.get("supplier") or {}
    item = f"{supplier.get('name') or 'Fornecedor'}" + (f" ({link['item']})" if link.get("item") else "")
    return {"category": BUDGET_CATEGORY.get(supplier.get("category") or "outros", "outros"), "item": item[:120],
            "value": float(link.get("value") or 0), "supplier_link_id": str(link["id"])}


async def push_to_budget(client_id: str, project_id: str) -> Dict[str, Any]:
    """Os fornecedores contratados/confirmados com valor entram no orçamento do plano (atualiza a linha se já estiver lá)."""
    from .studio_projects import update_project
    project = await _event(client_id, project_id)
    links = [link for link in await event_suppliers(client_id, project_id)
             if link.get("status") in ("contratado", "confirmado") and link.get("value")]
    if not links:
        raise StudioError("SUPPLIER_NOTHING_TO_BUDGET", "Nenhum fornecedor contratado com valor para lançar.")
    plan = dict(project.get("plan") or {})
    budget = [b for b in plan.get("budget") or [] if isinstance(b, dict)]
    by_link = {str(b.get("supplier_link_id")): n for n, b in enumerate(budget) if b.get("supplier_link_id")}
    for link in links:
        line = budget_line(link)
        if line["supplier_link_id"] in by_link:
            budget[by_link[line["supplier_link_id"]]] = line
        else:
            budget.append(line)
    return await update_project(client_id, project_id, {"plan": {**plan, "budget": budget}})


async def suppliers_text(client_id: str, project_id: Optional[str] = None) -> str:
    """Fornecedores para a IA do plano: só dados de negócio (sem telefone, e-mail ou nome de contato)."""
    lines: List[str] = []
    try:
        linked = await event_suppliers(client_id, project_id) if project_id else []
        everyone = await list_suppliers(client_id, include_inactive=False)
    except Exception as exc:  # noqa: BLE001 — sem tabela ou fora do ar: o plano segue sem fornecedores
        print(f"[studio][suppliers] read_failed error_type={type(exc).__name__}")
        return ""
    linked_ids = {str(link["supplier_id"]) for link in linked}
    for link in linked:
        s = link["supplier"]
        lines.append(f"- JÁ NO EVENTO: {s['name']} ({CATEGORIES.get(s.get('category'), 'Outros')}) · {link.get('item') or 's/ item'} · "
                     f"{link.get('status')}" + (f" · R$ {float(link['value']):.2f}" if link.get("value") else ""))
    for s in everyone:
        if str(s["id"]) in linked_ids:
            continue
        extra = " · ".join(x for x in (s.get("city"), s.get("price_note"), f"nota {s['rating']}/5" if s.get("rating") else None) if x)
        lines.append(f"- {s['name']} ({CATEGORIES.get(s.get('category'), 'Outros')})" + (f" · {extra}" if extra else ""))
        if len(lines) >= 40:
            break
    return "\n".join(lines)[:3000]
