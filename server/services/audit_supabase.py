from __future__ import annotations

import os
from typing import Any, Dict

import httpx


def _env(name: str) -> str:
    return str(os.getenv(name) or "").strip()


def audit_credentials() -> tuple[str, str]:
    url = _env("SUPABASE_URL").rstrip("/")
    key = _env("SUPABASE_AUDIT_KEY") or _env("SUPABASE_SERVICE_ROLE_KEY")
    if not url.startswith(("https://", "http://")):
        raise RuntimeError("SUPABASE_URL ausente ou inválida.")
    if len(key) < 20:
        raise RuntimeError("Defina SUPABASE_AUDIT_KEY ou SUPABASE_SERVICE_ROLE_KEY para auditoria somente leitura.")
    return url, key


class ReadOnlySupabase:
    """Minimal PostgREST client that physically exposes GET requests only."""

    def __init__(self) -> None:
        self.url, self._key = audit_credentials()
        self.request_log: list[Dict[str, Any]] = []

    def _headers(self, *, openapi: bool = False) -> Dict[str, str]:
        return {
            "apikey": self._key,
            "Authorization": f"Bearer {self._key}",
            "Accept": "application/openapi+json" if openapi else "application/json",
        }

    async def select(
        self, table: str, *, select: str = "*", filters: Dict[str, str] | None = None,
        order: str | None = None, limit: int | None = None, offset: int | None = None,
    ) -> list[Dict[str, Any]]:
        params: Dict[str, str] = {"select": select}
        if filters:
            params.update({str(key): str(value) for key, value in filters.items()})
        if order:
            params["order"] = order
        if limit is not None:
            params["limit"] = str(min(max(1, int(limit)), 10000))
        if offset is not None:
            params["offset"] = str(max(0, int(offset)))
        resource = _env("SUPABASE_AUDIT_CONNECTIONS_RESOURCE") if table == "integration_connections" else table
        resource = resource or table
        self.request_log.append({"method": "GET", "resource": resource, "select": select})
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(
                f"{self.url}/rest/v1/{resource}", headers=self._headers(), params=params,
            )
        response.raise_for_status()
        payload = response.json() if response.content else []
        return payload if isinstance(payload, list) else []

    async def openapi(self) -> Dict[str, Any]:
        self.request_log.append({"method": "GET", "resource": "openapi", "select": None})
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(f"{self.url}/rest/v1/", headers=self._headers(openapi=True))
        response.raise_for_status()
        payload = response.json() if response.content else {}
        return payload if isinstance(payload, dict) else {}

    def assert_read_only(self) -> None:
        methods = {str(item.get("method") or "").upper() for item in self.request_log}
        if methods - {"GET"}:
            raise RuntimeError(f"AUDIT_WRITE_METHOD_BLOCKED:{sorted(methods)}")
