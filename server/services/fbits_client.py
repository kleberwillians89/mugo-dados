"""Cliente somente leitura da API pública FBITS/Wake Commerce.

Documentação oficial (wakecommerce.readme.io):
- Base URL: https://api.fbits.net
- Autenticação: header `Authorization: Basic {token}`, token gerado pelo
  lojista no painel (Configurações > Integrações > Tokens).
- Limite: 120 requisições/minuto POR GRUPO de endpoint. Ao exceder, a API
  responde 429 com `Retry-After`; 5 requisições com o limite esgotado
  bloqueiam o token por 1 hora. Por isso este cliente usa margem (100/min) e
  interrompe o ciclo no primeiro 429, sem novas tentativas.
- GET /situacoesPedido: situações de pedido da loja (também valida o token).
- GET /pedidos: dataInicial/dataFinal (aaaa-mm-dd hh:mm:ss),
  enumTipoFiltroData, pagina (padrão 1), quantidadeRegistros (máx. 50),
  direcaoOrdenacao ASC|DESC. Sem total de páginas: o fim é uma página com
  menos registros que o tamanho pedido.

O token é SEMPRE recebido explicitamente da conexão do tenant. Não existe
leitura de token por variável de ambiente. O token e o header Authorization
nunca são logados nem incluídos em mensagens de erro.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from datetime import datetime
from typing import Any, AsyncIterator, Awaitable, Callable, Deque, Dict, List, Optional

import httpx


FBITS_BASE_URL = "https://api.fbits.net"
FBITS_PAGE_SIZE = 50
FBITS_MAX_REQUESTS_PER_MINUTE = 100
FBITS_MAX_PAGES_PER_WINDOW = 400
FBITS_SERVER_ERROR_RETRIES = 2

# Situações historicamente usadas como "aprovadas". NÃO são universais: cada
# loja configura as próprias situações. Servem só como sugestão inicial até a
# regra de receita ser validada com os dados reais de cada tenant.
FBITS_APPROVED_ORDER_STATUSES = "1,11,14"
FBITS_APPROVED_ORDER_STATUS_IDS = tuple(
    value.strip() for value in FBITS_APPROVED_ORDER_STATUSES.split(",") if value.strip()
)

FBITS_DATE_FILTERS = (
    "DataPedido", "DataAprovacao", "DataModificacaoStatus",
    "DataAlteracao", "DataCriacao", "DataStatus",
)


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


class FbitsApiError(RuntimeError):
    """Erro sanitizado: nunca contém token, header ou corpo bruto da resposta."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        status_code: Optional[int] = None,
        retry_after: Optional[int] = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.retry_after = retry_after
        self.retryable = retryable
        self.public_message = message


def _retry_after_seconds(response: httpx.Response) -> Optional[int]:
    raw = _safe_str(response.headers.get("Retry-After"))
    if raw.isdigit():
        return int(raw)
    return None


def _api_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except Exception:
        return ""
    if isinstance(payload, dict):
        return _safe_str(payload.get("mensagem") or payload.get("message"))[:200]
    return ""


def _format_datetime(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def orders_from_payload(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("pedidos", "items", "data", "results"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
    return []


class FbitsRateLimiter:
    """Janela deslizante de 60s. Aguarda antes de exceder o limite configurado."""

    def __init__(
        self,
        *,
        max_per_minute: int = FBITS_MAX_REQUESTS_PER_MINUTE,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.max_per_minute = max(1, int(max_per_minute))
        self._clock = clock
        self._sleep = sleep
        self._sent: Deque[float] = deque()

    async def acquire(self) -> None:
        while True:
            now = self._clock()
            while self._sent and now - self._sent[0] >= 60.0:
                self._sent.popleft()
            if len(self._sent) < self.max_per_minute:
                self._sent.append(now)
                return
            await self._sleep(max(0.01, 60.0 - (now - self._sent[0])))


class FbitsClient:
    def __init__(
        self,
        token: str,
        *,
        base_url: str = FBITS_BASE_URL,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        rate_limiter: Optional[FbitsRateLimiter] = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        timeout: float = 45.0,
        server_error_retries: int = FBITS_SERVER_ERROR_RETRIES,
    ) -> None:
        token = _safe_str(token)
        if token.lower().startswith("basic "):
            token = token[6:].strip()
        if not token:
            raise FbitsApiError("Informe o token da API FBITS.", code="FBITS_TOKEN_REQUIRED", status_code=400)
        self._authorization = f"Basic {token}"
        self._base_url = base_url.rstrip("/")
        self._transport = transport
        self._rate_limiter = rate_limiter or FbitsRateLimiter(sleep=sleep)
        self._sleep = sleep
        self._timeout = timeout
        self._server_error_retries = max(0, int(server_error_retries))
        self.requests_made = 0
        # Header x-total-count da última resposta (total do filtro, não da página).
        self.last_total_count: Optional[int] = None

    def __repr__(self) -> str:  # nunca expor o token em repr/logs
        return f"FbitsClient(base_url={self._base_url!r})"

    async def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        attempt = 0
        while True:
            attempt += 1
            await self._rate_limiter.acquire()
            self.requests_made += 1
            try:
                async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                    response = await client.get(
                        f"{self._base_url}{path}",
                        params=params,
                        headers={"Accept": "application/json", "Authorization": self._authorization},
                    )
            except httpx.HTTPError as exc:
                if attempt <= self._server_error_retries:
                    print(f"[fbits][http] endpoint={path} status=network_error attempt={attempt} retry=1")
                    await self._sleep(min(4.0, 1.0 * attempt))
                    continue
                print(f"[fbits][http] endpoint={path} status=network_error attempt={attempt} error_type={exc.__class__.__name__}")
                raise FbitsApiError(
                    "Não foi possível acessar a API da FBITS agora.",
                    code="FBITS_UNAVAILABLE", retryable=True,
                ) from None

            status = response.status_code
            if status == 429:
                retry_after = _retry_after_seconds(response)
                print(f"[fbits][http] endpoint={path} status=429 retry_after={retry_after if retry_after is not None else '-'} action=stop_cycle")
                raise FbitsApiError(
                    "Limite de requisições da FBITS atingido. A sincronização foi pausada"
                    + (f" e pode ser retomada em {retry_after}s." if retry_after is not None else "."),
                    code="FBITS_RATE_LIMITED", status_code=429, retry_after=retry_after, retryable=True,
                )
            if status in {401, 403}:
                print(f"[fbits][http] endpoint={path} status={status}")
                raise FbitsApiError(
                    "Token FBITS inválido ou sem permissão para consultar pedidos.",
                    code="FBITS_INVALID_TOKEN" if status == 401 else "FBITS_PERMISSION_DENIED",
                    status_code=status,
                )
            if status >= 500:
                if attempt <= self._server_error_retries:
                    print(f"[fbits][http] endpoint={path} status={status} attempt={attempt} retry=1")
                    await self._sleep(min(4.0, 1.0 * attempt))
                    continue
                print(f"[fbits][http] endpoint={path} status={status} attempt={attempt}")
                raise FbitsApiError(
                    "A API da FBITS está temporariamente indisponível.",
                    code="FBITS_UNAVAILABLE", status_code=status, retryable=True,
                )
            if status >= 400:
                detail = _api_message(response)
                print(f"[fbits][http] endpoint={path} status={status}")
                raise FbitsApiError(
                    "A FBITS recusou a consulta" + (f": {detail}" if detail else "."),
                    code="FBITS_REQUEST_REJECTED", status_code=status,
                )
            total_count = _safe_str(response.headers.get("x-total-count"))
            self.last_total_count = int(total_count) if total_count.isdigit() else None
            try:
                return response.json()
            except ValueError:
                raise FbitsApiError(
                    "A FBITS retornou uma resposta inválida.", code="FBITS_INVALID_RESPONSE", status_code=status,
                ) from None

    async def list_order_statuses(self) -> List[Dict[str, Any]]:
        payload = await self._get("/situacoesPedido")
        rows = payload if isinstance(payload, list) else []
        statuses = [
            {
                "id": _safe_str(row.get("situacaoPedidoId")),
                "nome": _safe_str(row.get("nome")),
                "descricao": _safe_str(row.get("descricao")),
            }
            for row in rows
            if isinstance(row, dict) and _safe_str(row.get("situacaoPedidoId"))
        ]
        print(f"[fbits][http] endpoint=/situacoesPedido status=200 statuses={len(statuses)}")
        return statuses

    async def revenue_indicators(
        self,
        *,
        start: str,
        end: str,
        compare_start: Optional[str] = None,
        compare_end: Optional[str] = None,
    ) -> Dict[str, Any]:
        """GET /dashboard/faturamento: receita, pedidos e ticket médio que a
        própria loja exibe no painel. Datas aaaa-mm-dd (dias inteiros, sem
        hora nem fuso). O comparativo devolve os mesmos indicadores
        (`indicador*Comparativo`) para o período informado."""
        payload = await self._get(
            "/dashboard/faturamento",
            params={
                "dataInicial": start,
                "dataFinal": end,
                "dataInicialComparativo": compare_start or start,
                "dataFinalComparativo": compare_end or end,
            },
        )
        return payload if isinstance(payload, dict) else {}

    async def iter_order_pages(
        self,
        *,
        start: datetime,
        end: datetime,
        date_filter: str = "DataPedido",
        page_size: int = FBITS_PAGE_SIZE,
    ) -> AsyncIterator[List[Dict[str, Any]]]:
        if date_filter not in FBITS_DATE_FILTERS:
            raise ValueError(f"enumTipoFiltroData inválido: {date_filter}")
        size = max(1, min(int(page_size), FBITS_PAGE_SIZE))
        previous_first_id = None
        for page in range(1, FBITS_MAX_PAGES_PER_WINDOW + 1):
            payload = await self._get(
                "/pedidos",
                params={
                    "dataInicial": _format_datetime(start),
                    "dataFinal": _format_datetime(end),
                    "enumTipoFiltroData": date_filter,
                    "pagina": page,
                    "quantidadeRegistros": size,
                    "direcaoOrdenacao": "ASC",
                },
            )
            rows = orders_from_payload(payload)
            print(
                f"[fbits][http] endpoint=/pedidos status=200 filter={date_filter} "
                f"start={_format_datetime(start)} end={_format_datetime(end)} page={page} count={len(rows)}"
            )
            first_id = _safe_str(rows[0].get("pedidoId")) if rows else None
            if first_id and first_id == previous_first_id:
                # A API ignorou a paginação — nunca repetir a mesma página em loop.
                raise FbitsApiError(
                    "A FBITS repetiu a mesma página de pedidos; sincronização interrompida.",
                    code="FBITS_PAGINATION_LOOP",
                )
            previous_first_id = first_id
            if rows:
                yield rows
            if len(rows) < size:
                return
        raise FbitsApiError(
            "Janela de pedidos maior que o limite de páginas por ciclo.",
            code="FBITS_WINDOW_TOO_LARGE",
        )
