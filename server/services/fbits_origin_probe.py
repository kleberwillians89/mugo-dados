"""Diagnóstico SOMENTE LEITURA: onde a FBITS/Wake informa a origem do pedido.

Uso (Render shell ou local com as variáveis do backend):

    python run_jobs.py fbits-origin-probe --client-id <empresa>
    python run_jobs.py fbits-origin-probe --client-id <empresa> --order-id 12345
    python run_jobs.py fbits-origin-probe --client-id <empresa> --days 14 --limit 40

O que faz:
- Lê pedidos recentes (lista) e o detalhe de alguns deles (GET /pedidos/{id}),
  porque a lista pode omitir campos que o detalhe traz.
- Mostra SÓ campos de origem: canal, origem/suborigem, contato, marketplace e
  metadados de campanha (utm_*, gclid, fbclid, parceiro...). Outras chaves de
  metadados aparecem só pelo nome, com o valor oculto.
- Nunca mostra nome, e-mail, CPF, telefone, endereço ou pagamento do cliente.
- Não grava nada no banco e não altera o estado da conexão.

Saída: por pedido, os campos encontrados e a origem que o Mugô Dados
calcularia; no fim, um resumo de quantos pedidos têm UTM e em qual campo.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from .fbits_client import FbitsApiError, FbitsClient
from .fbits_connections import load_fbits_connection
from .generic_connections import get_connection
from .integration_errors import IntegrationError
from .order_attribution import fbits_order_attribution

# Chaves cujo VALOR pode ser mostrado: sinais de origem/campanha, sem PII.
_ORIGIN_KEY = re.compile(r"utm|origem|origin|canal|channel|parceiro|partner|campanha|campaign|midia|media|"
                         r"source|referr|gclid|fbclid|ttclid|afiliad|affiliate|cupom|coupon|marketplace", re.I)
# Nunca mostrar, mesmo que o nome pareça de origem.
_PII_KEY = re.compile(r"email|e-mail|cpf|cnpj|telefone|phone|celular|nome|name|endereco|address|cep|"
                      r"documento|rg|cartao|card|pagamento|payment|ip\b|token|senha|password", re.I)
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_TOP_LEVEL_ORIGIN_FIELDS = ("canalId", "canalNome", "canalOrigem", "origemPedido", "marketPlacePedidoId",
                            "marketPlacePedidoSiteId", "tipoRastreamentoPedido", "omnichannel")


def _safe(value: Any) -> Any:
    """Valor curto e sem e-mail; estruturas só com chaves de origem."""
    if isinstance(value, dict):
        return {key: _safe(item) for key, item in value.items() if not _PII_KEY.search(str(key))}
    if isinstance(value, list):
        return [_safe(item) for item in value[:10]]
    if isinstance(value, str):
        text = value.strip()
        return "[oculto: parece e-mail]" if _EMAIL.search(text) else text[:160]
    return value


def _safe_origin(value: Any) -> Any:
    """Estruturas de origem da loja (origemPedido, omnichannel): não são dados
    pessoais, então "nome" aqui é o nome da origem e pode aparecer."""
    if isinstance(value, dict):
        return {key: _safe_origin(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe_origin(item) for item in value[:10]]
    return _safe(value)


def _metadata_view(order: Dict[str, Any]) -> Dict[str, Any]:
    pairs = order.get("metadados") if isinstance(order.get("metadados"), list) else []
    shown, hidden = {}, []
    for pair in pairs:
        if not isinstance(pair, dict):
            continue
        key = str(pair.get("chave") or "").strip()
        if not key:
            continue
        if _ORIGIN_KEY.search(key) and not _PII_KEY.search(key):
            shown[key] = _safe(pair.get("valor"))
        else:
            hidden.append(key)
    return {"campos_de_origem": shown, "outras_chaves_ocultas": sorted(set(hidden))}


def _extra_origin_fields(value: Any, path: str = "") -> Dict[str, Any]:
    """Qualquer outra chave com cara de origem em qualquer nível (fora usuario/pagamento)."""
    found: Dict[str, Any] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}" if path else str(key)
            if child.split(".")[0] in {"usuario", "pagamento", "pagamentos", "endereco", "enderecoEntrega", "itens", "metadados"}:
                continue
            if _PII_KEY.search(str(key)):
                continue
            if _ORIGIN_KEY.search(str(key)) and child not in _TOP_LEVEL_ORIGIN_FIELDS and not isinstance(item, (dict, list)):
                found[child] = _safe(item)
            elif isinstance(item, (dict, list)):
                found.update(_extra_origin_fields(item, child))
    elif isinstance(value, list):
        for index, item in enumerate(value[:5]):
            found.update(_extra_origin_fields(item, f"{path}[{index}]"))
    return found


def describe_order_origin(order: Dict[str, Any]) -> Dict[str, Any]:
    """Visão segura (sem PII) dos campos de origem de um pedido."""
    user = order.get("usuario") if isinstance(order.get("usuario"), dict) else {}
    return {
        "pedidoId": order.get("pedidoId"),
        "data": order.get("data"),
        "campos_de_origem_no_topo": {key: _safe_origin(order.get(key)) for key in _TOP_LEVEL_ORIGIN_FIELDS if key in order},
        "usuario.origemContato": _safe(user.get("origemContato")) if "origemContato" in user else None,
        "metadados": _metadata_view(order),
        "outros_campos_com_cara_de_origem": _extra_origin_fields(order),
        "chaves_do_pedido": sorted(str(key) for key in order.keys()),
        "origem_calculada_pelo_mugo": fbits_order_attribution(order),
    }


async def _client_for(client_id: str) -> FbitsClient:
    row = await load_fbits_connection(client_id)
    if not row:
        raise IntegrationError("Nenhuma conexão FBITS encontrada para esta empresa.", status_code=404,
                               code="FBITS_CONNECTION_NOT_FOUND", provider="fbits")
    full = await get_connection(client_id, str(row.get("id") or ""), include_token=True)
    try:
        token = str(json.loads(full.get("_token") or "{}").get("token") or "").strip()
    except (TypeError, ValueError):
        token = ""
    if not token:
        raise IntegrationError("A conexão FBITS não possui token.", status_code=401,
                               code="FBITS_REAUTH_REQUIRED", provider="fbits")
    return FbitsClient(token)


def summarize(views: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    views = list(views)
    sources = Counter(view["origem_calculada_pelo_mugo"]["attribution_source"] for view in views)
    channels = Counter(view["origem_calculada_pelo_mugo"]["origin_channel"] for view in views)
    meta_keys = Counter(key for view in views for key in view["metadados"]["campos_de_origem"])
    hidden_keys = Counter(key for view in views for key in view["metadados"]["outras_chaves_ocultas"])
    extra = Counter(key for view in views for key in view["outros_campos_com_cara_de_origem"])
    top = Counter(key for view in views for key in view["campos_de_origem_no_topo"])
    with_utm = sources.get("utm", 0)
    if not views:
        verdict = "Nenhum pedido no intervalo. Aumente --days ou informe --order-id."
    elif with_utm:
        verdict = f"{with_utm} de {len(views)} pedidos têm UTM em campos que o Mugô Dados já lê. A captura vai funcionar."
    elif extra:
        verdict = ("Nenhum pedido com UTM nos campos lidos hoje, mas há outros campos com cara de origem "
                   "(ver 'outros_campos'). Envie este resumo para ajustar a leitura.")
    else:
        verdict = ("Nenhum pedido com UTM na resposta da API. Só canal/origem da loja estará disponível; "
                   "confirme com a Wake como expor as UTMs persistidas na API de pedidos.")
    return {
        "pedidos_analisados": len(views),
        "veredito": verdict,
        "origem_por_tipo": dict(sources),
        "canal_calculado": dict(channels),
        "campos_no_topo_encontrados": dict(top),
        "metadados_de_origem_encontrados": dict(meta_keys),
        "metadados_outras_chaves": dict(hidden_keys),
        "outros_campos": dict(extra),
    }


async def probe_fbits_order_origin(
    client_id: str, *, order_id: Optional[str] = None, days: int = 7, limit: int = 20, detail_sample: int = 5,
    client: Optional[FbitsClient] = None,
) -> Dict[str, Any]:
    client = client or await _client_for(client_id)
    lista: List[Dict[str, Any]] = []
    detalhe: List[Dict[str, Any]] = []
    try:
        if order_id:
            detalhe.append(describe_order_origin(await client.get_order(order_id)))
        else:
            end = datetime.now(timezone.utc)
            start = end - timedelta(days=max(1, min(int(days), 30)))
            orders: List[Dict[str, Any]] = []
            # A API devolve do mais antigo para o mais novo: lê o intervalo
            # (com teto) e fica com os mais recentes.
            async for page in client.iter_order_pages(start=start, end=end, date_filter="DataPedido"):
                orders.extend(order for order in page if isinstance(order, dict))
                if len(orders) >= 500:
                    break
            orders = orders[-max(1, int(limit)):]  # os mais recentes
            lista = [describe_order_origin(order) for order in orders]
            for order in orders[-max(0, int(detail_sample)):]:
                if order.get("pedidoId") is not None:
                    detalhe.append(describe_order_origin(await client.get_order(str(order["pedidoId"]))))
    except FbitsApiError as exc:
        return {"ok": False, "code": exc.code, "message": exc.public_message}
    return {
        "ok": True,
        "empresa": client_id,
        "resumo_lista": summarize(lista) if lista else None,
        "resumo_detalhe": summarize(detalhe) if detalhe else None,
        "pedidos_lista": lista,
        "pedidos_detalhe": detalhe,
        "requisicoes_feitas": client.requests_made,
        "observacao": "Somente leitura. Nenhum dado de cliente (nome, e-mail, CPF, telefone, endereço) é exibido.",
    }
