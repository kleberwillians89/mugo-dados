"""“Ir para o job”: o que foi produzido a partir de uma tarefa, com nome, situação e onde abrir.

Lê os vínculos de task_work_links (gravados quando algo nasce de uma tarefa: e-mail, texto da Redação, matriz do
Social Media, post, anúncio) e busca o nome atual de cada registro, sempre na mesma empresa. O que foi apagado
aparece como "removido", sem link. Nada aqui escreve.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from .ig_supabase import sb_select
from .task_context import authorized_task, links_for

MODULE_LABEL = {"email_marketing": "E-mail Marketing", "redacao": "Redação", "social_media": "Social Media",
                "calendar": "Calendário", "midia_on": "Mídia On", "whatsapp": "WhatsApp"}
# módulo → (tabela, colunas, rota do app, parâmetro que abre o registro)
SOURCES = {
    "email_marketing": ("email_campaigns", "id,name,status", "email_marketing", "campanha"),
    "redacao": ("studio_documents", "id,title,status", "redacao", "doc"),
    "social_media": ("studio_content_matrices", "id,week_start,status", "campaigns", "matriz"),
    "calendar": ("studio_calendar_items", "id,title,status", "calendar", "item"),
    "midia_on": ("studio_ad_drafts", "id,payload,status", "media", "campanha"),
}
STATUS = {"rascunho": "Rascunho", "agendada": "Agendada", "enviando": "Enviando", "enviada": "Enviada", "falhou": "Falhou",
          "cancelada": "Cancelada", "arquivado": "Arquivado", "em_revisao": "Em revisão", "aprovado": "Aprovado",
          "rejeitado": "Ajuste pedido", "publicado": "Publicado", "ativa": "Ativa", "arquivada": "Arquivada",
          "publicada": "Criada no Meta", "publicando": "Criando no Meta", "erro": "Erro"}


def _name(module: str, row: Dict[str, Any]) -> str:
    if module == "email_marketing":
        return str(row.get("name") or "E-mail sem nome")
    if module == "social_media":
        start = str(row.get("week_start") or "")[:10]
        return "Matriz de conteúdo" + (f" (a partir de {start[8:10]}/{start[5:7]})" if len(start) == 10 else "")
    if module == "midia_on":
        return str((row.get("payload") or {}).get("name") or "Campanha da Mídia On")
    return str(row.get("title") or "Sem título")


async def _rows(client_id: str, module: str, ids: List[str]) -> Dict[str, Dict[str, Any]]:
    table, columns, _, _ = SOURCES[module]
    try:
        rows = await sb_select(table, select=columns, limit=len(ids),
                               filters={"client_id": f"eq.{client_id}", "id": f"in.({','.join(ids)})"})
    except Exception as exc:  # noqa: BLE001 — uma fonte fora do ar não esconde as outras
        print(f"[task_produced] source_failed module={module} {type(exc).__name__}")
        return {}
    return {str(r["id"]): r for r in rows}


async def produced(client_id: str, task_id: str, scope: Dict[str, Any]) -> Dict[str, Any]:
    task = await authorized_task(client_id, task_id, scope)  # mesma regra do quadro: só quem vê a tarefa
    links = await links_for(client_id, str(task["id"]))
    by_module: Dict[str, List[str]] = {}
    for link in links:
        if link.get("module") in SOURCES and str(link.get("record_id") or "").replace("-", "").isalnum():
            by_module.setdefault(str(link["module"]), []).append(str(link["record_id"]))
    found = dict(zip(by_module, await asyncio.gather(*(_rows(client_id, m, list(dict.fromkeys(ids))) for m, ids in by_module.items()))))
    items = []
    for link in links:
        module, record = str(link.get("module") or ""), str(link.get("record_id") or "")
        row = (found.get(module) or {}).get(record)
        source = SOURCES.get(module)
        items.append({
            "module": module, "module_label": MODULE_LABEL.get(module, module), "record_id": record,
            "deliverable": link.get("deliverable") or "", "created_at": link.get("created_at"),
            "name": _name(module, row) if row else "Removido", "removed": row is None and module in SOURCES,
            "status": STATUS.get(str((row or {}).get("status") or ""), (row or {}).get("status") or ""),
            "route": source[2] if source and row else None, "query": f"{source[3]}={record}" if source and row else None,
        })
    return {"task_id": str(task["id"]), "items": items}
