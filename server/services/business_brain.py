"""Contexto de negócio pré-preenchido pela IA com o que o Dados já sabe da empresa.

Lê o pacote de inteligência (perfil da marca, posts e legendas, campanhas que venderam, vendas por origem,
Mídia On, metas, clipping) e o nome da empresa, e propõe os 8 campos do contexto.

- Só preenche campo VAZIO: o que a equipe escreveu nunca é trocado.
- Na tela, o botão "Preencher com IA" só põe o rascunho no formulário; quem salva é a equipe.
- O job ``business-context-prefill`` (rodado à mão) grava os campos vazios de todas as marcas ativas.
- Sem dado, o campo fica vazio: a IA não inventa número, preço nem característica.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .business_context import FIELDS, MAX_FIELD_LENGTH, load_business_context, save_business_context
from .ig_supabase import sb_select
from .studio_intelligence import build_content_intelligence, clean_text, to_prompt
from .studio_llm import STR, arr, llm_json, obj

SCHEMA = obj({**{f: STR for f in FIELDS}, "fontes": arr(STR)})

INSTRUCTIONS = (
    "Você é o estrategista sênior da agência Mugô. Escreve o contexto de negócio de uma marca a partir dos dados "
    "reais dela. Frases objetivas, em português do Brasil. Nunca invente preço, número, prêmio, canal ou "
    "característica que não esteja nos dados: se não houver base para um campo, devolva string vazia."
)

GUIDE = {
    "segment": "mercado em que atua (1 linha)",
    "product_description": "o que vende, citando os produtos e campanhas que aparecem nos dados",
    "audience": "quem compra e o que valoriza (pelos posts que engajam e pelo perfil da marca)",
    "positioning": "como a marca quer ser percebida (pelo tom e pelas legendas)",
    "differentiators": "o que a diferencia, só com base no que a própria marca comunica",
    "commercial_context": "canais de venda, origem das vendas, ticket e sazonalidade SE estiverem nos dados",
    "goals": "metas do mês e foco das campanhas ativas",
    "strategic_notes": "restrições da marca, riscos do clipping e lacunas de dado",
}


def fill_empty(current: Dict[str, Any], suggested: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """Mantém o que já está preenchido; só entra sugestão em campo vazio."""
    out: Dict[str, Optional[str]] = {}
    for field in FIELDS:
        mine = str(current.get(field) or "").strip()
        new = str(suggested.get(field) or "").strip()[:MAX_FIELD_LENGTH]
        out[field] = mine or new or None
    return out


async def _company_name(client_id: str) -> str:
    try:
        rows = await sb_select("clients", select="name,trade_name", filters={"id": f"eq.{client_id}"}, limit=1)
    except Exception:  # noqa: BLE001 — sem nome, a IA segue com os dados
        rows = []
    row = rows[0] if rows else {}
    return str(row.get("trade_name") or row.get("name") or "").strip()


async def suggest_business(client_id: str) -> Dict[str, Any]:
    """Rascunho dos campos vazios. Não grava nada."""
    import json
    current = (await load_business_context(client_id)).get("context") or {}
    empty = [f for f in FIELDS if not str(current.get(f) or "").strip()]
    if not empty:
        return {"suggestion": {}, "filled": [], "sources": [], "message": "Todos os campos já estão preenchidos."}
    intel = await build_content_intelligence(client_id, use_cache=False)
    prompt = (
        f"EMPRESA: {await _company_name(client_id) or 'sem nome cadastrado'}\n"
        f"Preencha SÓ estes campos: {json.dumps({f: GUIDE[f] for f in empty}, ensure_ascii=False)}\n"
        f"Campos já escritos pela equipe (use como verdade, não reescreva): "
        f"{json.dumps({k: v for k, v in current.items() if v}, ensure_ascii=False)}\n"
        "Até 4 linhas por campo. Em fontes, liste de onde tirou (ex.: 'legendas dos posts', 'vendas por origem').\n\n"
        f"DADOS DA MARCA:\n{to_prompt(intel, sections=['marca', 'posts', 'campanhas_que_mais_venderam', 'vendas_por_origem', 'campanhas_ativas', 'plano_de_midia', 'metas_do_mes', 'kpis', 'clipping', 'aprendizados', 'ultima_analise'], limit=9000)}\n"
    )
    data = await llm_json(instructions=INSTRUCTIONS, prompt=prompt, schema_name="business_context_v1",
                          schema=SCHEMA, temperature=0.3, timeout=120)
    suggestion = {f: clean_text(data.get(f), MAX_FIELD_LENGTH) for f in empty if clean_text(data.get(f), MAX_FIELD_LENGTH)}
    return {"suggestion": suggestion, "filled": sorted(suggestion),
            "sources": [clean_text(s, 120) for s in (data.get("fontes") or [])[:6] if clean_text(s, 120)],
            "gaps": intel.get("lacunas") or []}


async def _active_clients() -> List[str]:
    rows = await sb_select("clients", select="id,status", limit=500)
    return [str(r["id"]) for r in rows if r.get("id") and str(r.get("status") or "active").lower() not in ("inactive", "archived", "inativo")]


async def prefill_all(client_id: Optional[str] = None) -> Dict[str, Any]:
    """Grava os campos vazios do contexto de cada marca ativa (os preenchidos ficam como estão)."""
    clients = [client_id] if client_id else await _active_clients()
    counts = {"clients": len(clients), "updated": 0, "complete": 0, "failed": 0, "fields": 0}
    for cid in clients:
        try:
            result = await suggest_business(cid)
            if not result["suggestion"]:
                counts["complete"] += 1
                continue
            current = (await load_business_context(cid)).get("context") or {}
            await save_business_context(client_id=cid, user_id="", payload=fill_empty(current, result["suggestion"]))
            counts["updated"] += 1
            counts["fields"] += len(result["suggestion"])
        except Exception as exc:  # noqa: BLE001 — uma marca não para as outras
            counts["failed"] += 1
            print(f"[business_brain] client_id={cid} failed={getattr(exc, 'code', type(exc).__name__)}")
    return counts
