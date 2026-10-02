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
