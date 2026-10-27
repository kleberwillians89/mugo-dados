"""Streamable HTTP oficial. PR A: exclusivamente desenvolvimento local."""
from __future__ import annotations

import os
import logging
from typing import Any
from contextlib import asynccontextmanager
from contextvars import ContextVar
from collections import OrderedDict
import time

from starlette.responses import JSONResponse

from services.ig_supabase import mcp_safe_errors
from .tools import TOOLS, ToolFailure, dispatch

identity: ContextVar[str | None] = ContextVar("mcp_identity", default=None)


def enabled():
    return os.getenv("MCP_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


def local_access():
    # Todos os marcadores são verificados, inclusive quando discordam entre si.
    production = any(os.getenv(key, "").strip().lower() in {"production", "prod"}
                     for key in ("APP_ENV", "ENVIRONMENT", "PYTHON_ENV"))
    return (not production and os.getenv("APP_ENV", "").strip().lower() in {"local", "dev", "development", "test"}
            and os.getenv("RENDER", "").lower() != "true"
            and os.getenv("ALLOW_NO_AUTH", "").lower() in {"true", "1", "yes", "on"})


class LocalGateway:
    def __init__(self):
        self.sdk = None
        self.sdk_app = None
        self.buckets = OrderedDict()
        self.active_reads = 0

    def setup(self):
        if self.sdk is not None:
            return
        # Flag desligada não importa nem instancia o SDK.
        from mcp.server.fastmcp import FastMCP
        from mcp.server.transport_security import TransportSecuritySettings
        from mcp.types import ToolAnnotations
        from mcp.server.fastmcp.exceptions import ToolError

        class SafeMCP(FastMCP):
            async def call_tool(self, name, arguments):
                allowed = {"company_id", "start", "end"} | ({"provider"} if name == "get_paid_media" else set())
                if name not in TOOLS or not isinstance(arguments, dict) or set(arguments) - (set() if name == "list_companies" else allowed):
                    raise ToolError("Ferramenta ou argumentos não autorizados.")
                if any(value is not None and (not isinstance(value, str) or len(value) > 128) for value in arguments.values()):
                    raise ToolError("Argumentos de leitura inválidos.")
                if name != "list_companies" and not arguments.get("company_id"):
                    raise ToolError("Selecione uma empresa.")
                if name == "get_paid_media" and arguments.get("provider") not in {"meta", "google_ads"}:
                    raise ToolError("Selecione meta ou google_ads.")
                return await super().call_tool(name, arguments)

        class SafeLog(logging.Filter):
            def filter(self, record):
                record.msg = '[mcp] sdk_event level=' + record.levelname
                record.args = ()
                record.exc_info = record.exc_text = record.stack_info = None
                return True

        # O SDK pode incluir argumentos inválidos/exceções em logs. Esta fronteira
        # conserva severidade, sem conteúdo de requisição, cabeçalhos ou traceback.
        sdk_logger = logging.getLogger("mcp")
        if not any(getattr(handler, "_mugo_mcp_safe", False) for handler in sdk_logger.handlers):
            handler = logging.StreamHandler()
            handler._mugo_mcp_safe = True
            handler.addFilter(SafeLog())
            sdk_logger.addHandler(handler)
            sdk_logger.propagate = False

        self.sdk = SafeMCP("Mugô Dados", stateless_http=True, json_response=True,
            max_request_body_size=32768, streamable_http_path="/mcp",
            transport_security=TransportSecuritySettings(
                allowed_hosts=["localhost", "127.0.0.1", "[::1]", "localhost:*", "127.0.0.1:*", "[::1]:*"],
                allowed_origins=["http://localhost", "http://127.0.0.1", "http://localhost:*", "http://127.0.0.1:*"],
            ))

        async def invoke(name, **kwargs):
            uid = identity.get()
            if not uid:
                raise ToolError("Autenticação obrigatória.")
            if self.active_reads >= 2:
                raise ToolError("Há leituras em andamento. Tente novamente em instantes.")
            self.active_reads += 1
            try:
                return await dispatch(uid, name, **kwargs)
            except ToolFailure as exc:
                raise ToolError(str(exc)) from None
            finally:
                self.active_reads -= 1

        async def list_companies() -> dict[str, Any]:
            return await invoke("list_companies")

        async def get_paid_media(company_id: str, provider: str, start: str | None = None, end: str | None = None) -> dict[str, Any]:
            return await invoke("get_paid_media", company_id=company_id, provider=provider, start=start, end=end)

        descriptions = {
            "list_companies": "Lista empresas autorizadas e fontes conectadas, sem dados pessoais de compradores.",
            "get_data_freshness": "Consulte antes de analisar: conexão, último sucesso e cobertura das fontes.",
            "get_business_overview": "KPIs canônicos e comparação anterior, respeitando fontes e cobertura. Não gera análise.",
            "get_paid_media": "Mídia paga persistida: provider meta ou google_ads; no máximo 50 campanhas, sem sincronizar. Receitas são atribuídas pelas plataformas e não devem ser somadas entre fontes.",
            "get_site_traffic": "Métricas persistidas do GA4; dimensões sem garantia de privacidade são omitidas.",
            "get_sales_by_origin": "Vendas agregadas por origem; atribuição não comprova causalidade.",
            "get_customer_summary": "Somente agregados de compradores; nunca retorna compradores individuais.",
            "get_goals": "Metas numéricas e progresso do período; não altera metas.",
            "get_business_context": "Disponibilidade do contexto salvo; textos sem comprovação de privacidade são omitidos.",
            "get_latest_analysis": "Metadados da última análise salva; não chama IA e omite texto livre sem origem segura.",
        }
        for name, description in descriptions.items():
            if name == "list_companies":
                fn = list_companies
            elif name == "get_paid_media":
                fn = get_paid_media
            else:
                # Factory preserva uma assinatura explícita, sem tenant/SQL/credencial livre.
                def factory(tool_name):
                    async def read(company_id: str, start: str | None = None, end: str | None = None) -> dict[str, Any]:
                        return await invoke(tool_name, company_id=company_id, start=start, end=end)
                    return read
                fn = factory(name)
            self.sdk.tool(name=name, description=description + " Datas AAAA-MM-DD; até 400 dias, padrão 30 dias.",
                annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
                structured_output=True)(fn)
        class DependencyLog(SafeLog):
            def filter(self, record):
                if mcp_safe_errors.get() and record.name.startswith(("httpx", "httpcore")):
                    return super().filter(record)
                return True

        for handler in logging.getLogger().handlers:
            if not getattr(handler, "_mugo_dependency_safe", False):
                handler.addFilter(DependencyLog())
                handler._mugo_dependency_safe = True
        self.sdk_app = self.sdk.streamable_http_app()

    async def __call__(self, scope, receive, send):
        privacy_token = mcp_safe_errors.set(True)
        try:
            await self.handle(scope, receive, send)
        finally:
            mcp_safe_errors.reset(privacy_token)

    async def handle(self, scope, receive, send):
        if not enabled() or not local_access():
            return await JSONResponse({"detail": "Recurso indisponível."}, status_code=404)(scope, receive, send)
        if scope["method"] != "POST":
            return await JSONResponse({"detail": "Use POST para requisições MCP sem sessão."}, status_code=405, headers={"Allow": "POST"})(scope, receive, send)
        peer = (scope.get("client") or (None,))[0]
        listener = (scope.get("server") or (None,))[0]
        if peer not in {"127.0.0.1", "::1", "localhost", "testclient"} or listener not in {"127.0.0.1", "::1", "localhost"}:
            return await JSONResponse({"detail": "Acesso permitido apenas localmente."}, status_code=403)(scope, receive, send)
        if self.sdk_app is None:
            return await JSONResponse({"detail": "Transporte não inicializado."}, status_code=503)(scope, receive, send)
        uid = os.getenv("DEV_USER_ID", "").strip() or "local-dev-user"
        now = time.monotonic()
        count, started = self.buckets.pop(uid, (0, now))
        if now - started >= 60:
            count, started = 0, now
        self.buckets[uid] = (count + 1, started)
        while len(self.buckets) > 1024:
            self.buckets.popitem(last=False)
        if count >= 60:
            return await JSONResponse({"detail": "Limite de leitura atingido; aguarde um minuto."}, status_code=429)(scope, receive, send)
        token = identity.set(uid)
        response_start = None
        chunks = bytearray()
        overflow = False

        async def bounded_send(message):
            nonlocal response_start, overflow
            if message["type"] == "http.response.start":
                response_start = message
            elif message["type"] == "http.response.body":
                if not overflow:
                    chunks.extend(message.get("body", b""))
                    if len(chunks) > 262144:
                        overflow = True
                        chunks.clear()
                if not message.get("more_body", False):
                    if overflow:
                        await JSONResponse({"detail": "Resposta excede o limite de leitura."}, 413)(scope, receive, send)
                    else:
                        await send(response_start)
                        await send({"type": "http.response.body", "body": bytes(chunks)})

        try:
            await self.sdk_app(scope, receive, bounded_send)
        finally:
            identity.reset(token)


def install(app):
    gateway = LocalGateway()
    app.add_route("/mcp", gateway, methods=["GET", "POST", "DELETE"])
    previous = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        async with previous(application):
            if enabled() and local_access():
                gateway.setup()
                async with gateway.sdk.session_manager.run():
                    yield
            else:
                yield

    app.router.lifespan_context = lifespan
    return gateway
