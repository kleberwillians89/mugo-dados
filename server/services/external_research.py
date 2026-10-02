"""Pesquisa externa (mercado, referências, creators, UGC) — interface extensível.

Hoje **não existe provider real conectado**, e a regra é absoluta: nada aqui
inventa informação externa. Nenhuma função devolve handle, seguidores, views,
tendência, concorrente ou benchmark fabricado, e não há scraping improvisado.
Sem provider configurado, cada consulta responde `not_configured` e quem
consome simplesmente não renderiza a seção.

Para ligar um provider real, implemente o protocolo `ExternalResearchProvider`
e registre com `set_provider`. O provider precisa devolver, para cada item,
evidência verificável: `source_url` e `researched_at`. Item sem fonte é
descartado por `validate_items` — o que vai à tela sempre tem origem
auditável, para avaliação humana.

Duas naturezas distintas, nunca misturadas:
  - `CONTENT_REFERENCE`: conteúdo ou formato que serve de referência;
  - `POTENTIAL_UGC_CREATOR`: pessoa que *pode* ser avaliada para UGC.
A decisão de contratar é sempre humana: nada aqui recomenda contratação.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

STATUS_NOT_CONFIGURED = "not_configured"
STATUS_UNAVAILABLE = "unavailable"
STATUS_OK = "ok"

CONTENT_REFERENCE = "CONTENT_REFERENCE"
POTENTIAL_UGC_CREATOR = "POTENTIAL_UGC_CREATOR"
ITEM_KINDS = (CONTENT_REFERENCE, POTENTIAL_UGC_CREATOR)

# Campos de um item externo. `source_url` e `researched_at` são obrigatórios:
# sem eles não há como auditar a informação, então o item não passa.
ITEM_FIELDS = (
    "kind", "handle", "platform", "profile_url", "category",
    "reason_relevant", "observed_format", "public_signal",
    "source_url", "researched_at",
)
REQUIRED_ITEM_FIELDS = ("kind", "source_url", "researched_at")


def _text(value: Any) -> str:
    return str(value if value is not None else "").strip()


@runtime_checkable
class ExternalResearchProvider(Protocol):
    """Provider real de pesquisa externa. Toda resposta precisa de evidência."""

    name: str

    async def research_brand_context(self, *, client_id: str, query: Dict[str, Any]) -> List[Dict[str, Any]]: ...
    async def find_market_signals(self, *, client_id: str, query: Dict[str, Any]) -> List[Dict[str, Any]]: ...
    async def find_creators(self, *, client_id: str, query: Dict[str, Any]) -> List[Dict[str, Any]]: ...
    async def find_content_references(self, *, client_id: str, query: Dict[str, Any]) -> List[Dict[str, Any]]: ...


_provider: Optional[ExternalResearchProvider] = None


def set_provider(provider: Optional[ExternalResearchProvider]) -> None:
    global _provider
    _provider = provider


def get_provider() -> Optional[ExternalResearchProvider]:
    return _provider


def provider_configured() -> bool:
    return _provider is not None


def validate_items(items: Any, *, allowed_kinds: tuple[str, ...] = ITEM_KINDS) -> List[Dict[str, Any]]:
    """Mantém só item auditável: natureza conhecida e evidência verificável.

    Campos desconhecidos são descartados, para um provider não injetar texto
    arbitrário no que a análise lê.
    """
    valid: List[Dict[str, Any]] = []
    for row in items if isinstance(items, list) else []:
        if not isinstance(row, dict):
            continue
        kind = _text(row.get("kind")).upper()
        if kind not in allowed_kinds:
            continue
        if not all(_text(row.get(field)) for field in REQUIRED_ITEM_FIELDS):
            continue
        valid.append({field: _text(row.get(field)) or None for field in ITEM_FIELDS} | {"kind": kind})
    return valid


def unavailable(reason: str = STATUS_NOT_CONFIGURED) -> Dict[str, Any]:
    return {"status": reason, "provider": None, "items": []}


async def _query(method: str, *, client_id: str, query: Dict[str, Any], allowed_kinds: tuple[str, ...]) -> Dict[str, Any]:
    provider = _provider
    if provider is None:
        return unavailable()
    try:
        items = await getattr(provider, method)(client_id=client_id, query=query or {})
    except Exception as exc:
        print(
            f"[intelligence][external_research] client_id={client_id} method={method} "
            f"status=unavailable error_type={exc.__class__.__name__}"
        )
        return unavailable(STATUS_UNAVAILABLE)
    return {
        "status": STATUS_OK,
        "provider": _text(getattr(provider, "name", "")) or None,
        "items": validate_items(items, allowed_kinds=allowed_kinds),
    }


async def research_brand_context(*, client_id: str, query: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return await _query("research_brand_context", client_id=client_id, query=query or {}, allowed_kinds=ITEM_KINDS)


async def find_market_signals(*, client_id: str, query: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return await _query("find_market_signals", client_id=client_id, query=query or {}, allowed_kinds=(CONTENT_REFERENCE,))


async def find_creators(*, client_id: str, query: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return await _query("find_creators", client_id=client_id, query=query or {}, allowed_kinds=(POTENTIAL_UGC_CREATOR,))


async def find_content_references(*, client_id: str, query: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return await _query("find_content_references", client_id=client_id, query=query or {}, allowed_kinds=(CONTENT_REFERENCE,))


async def external_research_context(*, client_id: str, query: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Bloco de pesquisa externa do snapshot.

    Sem provider, devolve `not_configured` com listas vazias: a análise segue
    normalmente com os dados internos e a interface omite as seções.
    """
    if not provider_configured():
        return {
            "status": STATUS_NOT_CONFIGURED,
            "provider": None,
            "market_signals": [],
            "content_references": [],
            "ugc_creators": [],
        }
    market = await find_market_signals(client_id=client_id, query=query)
    references = await find_content_references(client_id=client_id, query=query)
    creators = await find_creators(client_id=client_id, query=query)
    statuses = {market["status"], references["status"], creators["status"]}
    return {
        "status": STATUS_OK if STATUS_OK in statuses else STATUS_UNAVAILABLE,
        "provider": market.get("provider") or references.get("provider") or creators.get("provider"),
        "market_signals": market["items"],
        "content_references": references["items"],
        "ugc_creators": creators["items"],
    }
