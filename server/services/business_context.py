"""Contexto de negócio da empresa, para a Inteligência raciocinar sobre o caso.

Pertence à EMPRESA, não ao usuário: quem tem acesso à empresa vê o mesmo
contexto. É texto editorial escrito pela equipe (segmento, produto, público,
posicionamento, objetivos), nunca credencial — e é o que permite sair do
resumo genérico de métricas.

Leitura e escrita passam pelo backend, que aplica papel e tenant; o browser
não toca a tabela. Campos são limitados em tamanho antes de ir ao modelo, para
o contexto não virar um canal de injeção de texto arbitrário.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .ig_supabase import sb_select, sb_upsert

TABLE = "client_business_context"

FIELDS = (
    "segment", "product_description", "audience", "positioning",
    "differentiators", "commercial_context", "goals", "strategic_notes",
)
MAX_FIELD_LENGTH = 1200


def _text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def normalize_business_context(payload: Dict[str, Any] | None) -> Dict[str, Optional[str]]:
    """Só os campos conhecidos, truncados. Campo vazio virá como None."""
    source = payload if isinstance(payload, dict) else {}
    return {
        field: (_text(source.get(field))[:MAX_FIELD_LENGTH] or None)
        for field in FIELDS
    }


def is_filled(context: Dict[str, Any] | None) -> bool:
    return any(_text((context or {}).get(field)) for field in FIELDS)


async def load_business_context(client_id: str) -> Dict[str, Any]:
    """Contexto da empresa. Ausência não é erro: a análise segue sem ele."""
    cid = _text(client_id)
    if not cid:
        return {"available": False, "context": normalize_business_context({})}
    try:
        rows = await sb_select(
            TABLE,
            select=",".join(("client_id", *FIELDS, "updated_at")),
            filters={"client_id": f"eq.{cid}"}, limit=1,
        )
    except Exception as exc:
        # Tabela ainda não aplicada no remoto, ou leitura indisponível: a
        # Inteligência degrada para "sem contexto", nunca falha por isto.
        print(
            f"[intelligence][business_context] client_id={cid} status=unavailable "
            f"error_type={exc.__class__.__name__}"
        )
        return {"available": False, "context": normalize_business_context({})}
    row = rows[0] if rows and _text(rows[0].get("client_id")) == cid else {}
    context = normalize_business_context(row)
    return {
        "available": is_filled(context),
        "context": context,
        "updated_at": row.get("updated_at"),
    }


async def save_business_context(
    *, client_id: str, user_id: str, payload: Dict[str, Any],
) -> Dict[str, Any]:
    """Grava o contexto da empresa já autorizada pela rota."""
    cid = _text(client_id)
    if not cid:
        raise RuntimeError("CLIENT_ID_REQUIRED")
    context = normalize_business_context(payload)
    await sb_upsert(
        TABLE,
        [{"client_id": cid, **context, "updated_by": _text(user_id) or None}],
        on_conflict="client_id",
    )
    return {"available": is_filled(context), "context": context}


# ---- Contexto da marca para a IA (contexto do negócio + memória da marca) ----------------------------
# A memória da marca (``brand_knowledge``) é o resumo do material que a equipe enviou e dos fatos
# confirmados no agente da marca. Ela já ia para o calendário, as ideias de post e os comentários; aqui
# passa a ir também para a Inteligência (análises e chat), para nenhuma resposta sair "sem conhecer a
# marca". Continua sendo texto editorial: nunca métrica verificada nem instrução de sistema.
BRAND_MEMORY_CHARS = 2500
COMPACT_FIELD_CHARS = 320
COMPACT_MEMORY_CHARS = 1400


async def load_business_context_for_ai(client_id: str, *, memory_chars: int = BRAND_MEMORY_CHARS) -> Dict[str, Any]:
    """Contexto do negócio + memória da marca. Nunca levanta: sem dado, segue sem ele."""
    business = await load_business_context(client_id)
    try:
        from .brand_knowledge import knowledge_for_prompt
        memory = (await knowledge_for_prompt(client_id, limit=memory_chars)).strip()
    except Exception as exc:  # noqa: BLE001 — memória indisponível não derruba a análise
        print(f"[intelligence][brand_memory] client_id={_text(client_id)} status=unavailable error_type={exc.__class__.__name__}")
        memory = ""
    context = {**(business.get("context") or {}), "brand_memory": memory or None}
    return {**business, "context": context, "available": bool(business.get("available") or memory),
            "brand_memory_available": bool(memory)}


def compact_brand_context(context: Dict[str, Any] | None, *, field_chars: int = COMPACT_FIELD_CHARS,
                          memory_chars: int = COMPACT_MEMORY_CHARS) -> Optional[Dict[str, str]]:
    """Versão curta para prompts com teto de tamanho (chat da Inteligência). None quando não há nada."""
    source = context if isinstance(context, dict) else {}
    out: Dict[str, str] = {}
    for field in (*FIELDS, "brand_memory"):
        value = _text(source.get(field))
        if value:
            out[field] = value[: memory_chars if field == "brand_memory" else field_chars]
    return out or None
