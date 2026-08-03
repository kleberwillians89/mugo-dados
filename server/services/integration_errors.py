from __future__ import annotations

from typing import Optional

import httpx


class IntegrationError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        code: str,
        provider: str,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.public_message = message
        self.status_code = status_code
        self.code = code
        self.provider = provider
        self.retryable = retryable


def provider_http_error(
    provider: str,
    status_code: int,
    *,
    operation: str,
) -> IntegrationError:
    status = int(status_code or 0)
    provider_label = "Google" if provider == "google" else "Shopify"
    if status == 400:
        return IntegrationError(
            f"{provider_label} recusou os parâmetros da solicitação.",
            status_code=400,
            code=f"{provider.upper()}_BAD_REQUEST",
            provider=provider,
        )
    if status == 401:
        return IntegrationError(
            f"A autorização da {provider_label} expirou ou foi revogada. Conecte novamente.",
            status_code=401,
            code=f"{provider.upper()}_REAUTH_REQUIRED",
            provider=provider,
        )
    if status == 403:
        return IntegrationError(
            f"A conexão da {provider_label} não possui permissão para {operation}.",
            status_code=403,
            code=f"{provider.upper()}_INSUFFICIENT_SCOPE",
            provider=provider,
        )
    if status == 404:
        return IntegrationError(
            f"O recurso solicitado não foi encontrado na {provider_label}.",
            status_code=404,
            code=f"{provider.upper()}_RESOURCE_NOT_FOUND",
            provider=provider,
        )
    if status == 409:
        return IntegrationError(
            f"A configuração da {provider_label} ainda está pendente.",
            status_code=409,
            code=f"{provider.upper()}_CONFIGURATION_PENDING",
            provider=provider,
        )
    if status == 429:
        return IntegrationError(
            f"A {provider_label} limitou temporariamente as solicitações. Tente novamente em instantes.",
            status_code=429,
            code=f"{provider.upper()}_RATE_LIMITED",
            provider=provider,
            retryable=True,
        )
    if status in {502, 503, 504}:
        return IntegrationError(
            f"A {provider_label} está temporariamente indisponível.",
            status_code=503,
            code=f"{provider.upper()}_UNAVAILABLE",
            provider=provider,
            retryable=True,
        )
    if status >= 500:
        return IntegrationError(
            f"A {provider_label} retornou uma falha temporária.",
            status_code=502,
            code=f"{provider.upper()}_UPSTREAM_ERROR",
            provider=provider,
            retryable=True,
        )
    return IntegrationError(
        f"Não foi possível concluir a solicitação na {provider_label}.",
        status_code=502,
        code=f"{provider.upper()}_UPSTREAM_ERROR",
        provider=provider,
        retryable=True,
    )


def from_httpx_error(
    provider: str,
    exc: Exception,
    *,
    operation: str,
) -> IntegrationError:
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        return provider_http_error(
            provider,
            exc.response.status_code,
            operation=operation,
        )
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
        return IntegrationError(
            f"{'Google' if provider == 'google' else 'Shopify'} está temporariamente indisponível.",
            status_code=503,
            code=f"{provider.upper()}_UNAVAILABLE",
            provider=provider,
            retryable=True,
        )
    return IntegrationError(
        f"Falha de comunicação com {'Google' if provider == 'google' else 'Shopify'}.",
        status_code=502,
        code=f"{provider.upper()}_UPSTREAM_ERROR",
        provider=provider,
        retryable=True,
    )


def google_api_error(
    response: httpx.Response,
    *,
    api: str,
    unavailable_code: str,
    operation: str,
) -> IntegrationError:
    try:
        payload = response.json()
    except (TypeError, ValueError):
        payload = {}
    error = payload.get("error") if isinstance(payload, dict) else {}
    details = error.get("details") if isinstance(error, dict) else []
    reasons = {
        str(item.get("reason") or item.get("reasonCode") or "").upper()
        for item in (details if isinstance(details, list) else [])
        if isinstance(item, dict)
    }
    message = str((error or {}).get("message") or "")[:240] if isinstance(error, dict) else ""
    if "SERVICE_DISABLED" in reasons or "has not been used" in message.lower():
        return IntegrationError(
            f"A {api} não está habilitada no projeto Google OAuth.",
            status_code=409,
            code="GOOGLE_ADMIN_API_DISABLED" if api == "Analytics Admin API" else "GOOGLE_DATA_API_DISABLED",
            provider="google",
        )
    if response.status_code == 404:
        return IntegrationError(
            f"O recurso Google selecionado não está mais disponível para {operation}.",
            status_code=404, code=unavailable_code, provider="google",
        )
    if response.status_code == 403:
        return IntegrationError(
            f"A conexão Google não possui permissão para {operation}.",
            status_code=403, code="GOOGLE_SCOPE_INSUFFICIENT", provider="google",
        )
    return provider_http_error("google", response.status_code, operation=operation)


def error_status(exc: Exception, default: Optional[int] = None) -> int:
    value = getattr(exc, "status_code", None)
    if isinstance(value, int):
        return value
    return int(default or 500)
