from __future__ import annotations

import base64
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account

from .single_tenant import get_default_ga4_property_id
from .integration_errors import google_api_error

GA4_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
GA4_API_BASE = "https://analyticsdata.googleapis.com/v1beta"
GA4_TIMEOUT_SECONDS = 60
GA4_PAGE_SIZE = 10000


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _env(name: str) -> str:
    return _safe_str(os.getenv(name))


def _normalize_property_id(value: Any) -> str:
    property_id = _safe_str(value)
    if property_id.startswith("properties/"):
        property_id = property_id.split("/", 1)[1].strip()
    return property_id


def _read_json_file(path_value: str) -> Dict[str, Any]:
    path = Path(path_value).expanduser().resolve()
    if not path.exists():
        raise RuntimeError(f"Arquivo de credenciais GA4 não encontrado: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _is_render_runtime() -> bool:
    return _env("RENDER").lower() == "true"


def _is_local_dev_runtime() -> bool:
    if _is_render_runtime():
        return False

    explicit_env = _env("ENVIRONMENT").lower() or _env("APP_ENV").lower() or _env("PYTHON_ENV").lower()
    if explicit_env in {"production", "prod"}:
        return False

    return True


@lru_cache(maxsize=1)
def _load_service_account_info() -> Dict[str, Any]:
    inline_json_base64 = _env("GA4_SERVICE_ACCOUNT_JSON_BASE64")
    if inline_json_base64:
        decoded = base64.b64decode(inline_json_base64).decode("utf-8")
        return json.loads(decoded)

    inline_json = _env("GA4_SERVICE_ACCOUNT_JSON")
    if inline_json:
        return json.loads(inline_json)

    file_candidate = _env("GA4_CREDENTIALS_PATH") or _env("GOOGLE_APPLICATION_CREDENTIALS")
    if file_candidate:
        if _is_local_dev_runtime():
            return _read_json_file(file_candidate)
        raise RuntimeError(
            "GA4_CREDENTIALS_PATH/GOOGLE_APPLICATION_CREDENTIALS só podem ser usados em ambiente local/dev. "
            "Em produção use GA4_SERVICE_ACCOUNT_JSON_BASE64 ou GA4_SERVICE_ACCOUNT_JSON."
        )

    raise RuntimeError(
        "Credenciais do GA4 não configuradas. Use GA4_SERVICE_ACCOUNT_JSON_BASE64, "
        "GA4_SERVICE_ACCOUNT_JSON ou GA4_CREDENTIALS_PATH (somente local/dev)."
    )


@lru_cache(maxsize=1)
def _build_credentials() -> service_account.Credentials:
    info = _load_service_account_info()
    return service_account.Credentials.from_service_account_info(info, scopes=[GA4_SCOPE])


def _get_access_token() -> str:
    credentials = _build_credentials()
    if not credentials.valid or credentials.expired or not credentials.token:
        credentials.refresh(Request())
    token = _safe_str(credentials.token)
    if not token:
        raise RuntimeError("Não foi possível obter access token para o GA4.")
    return token


def _order_bys_payload(order_bys: Optional[List[Dict[str, Any]]]) -> Optional[List[Dict[str, Any]]]:
    if not order_bys:
        return None
    normalized: List[Dict[str, Any]] = []
    for item in order_bys:
        if not isinstance(item, dict):
            continue
        normalized.append(item)
    return normalized or None


def _build_run_report_body(
    *,
    start_date: str,
    end_date: str,
    dimensions: Iterable[str],
    metrics: Iterable[str],
    limit: int,
    offset: int,
    dimension_filter: Optional[Dict[str, Any]] = None,
    order_bys: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "dateRanges": [{"startDate": start_date, "endDate": end_date}],
        "dimensions": [{"name": _safe_str(name)} for name in dimensions if _safe_str(name)],
        "metrics": [{"name": _safe_str(name)} for name in metrics if _safe_str(name)],
        "limit": str(max(1, int(limit))),
        "offset": str(max(0, int(offset))),
        "keepEmptyRows": False,
    }

    normalized_order_bys = _order_bys_payload(order_bys)
    if normalized_order_bys:
        payload["orderBys"] = normalized_order_bys
    if dimension_filter:
        payload["dimensionFilter"] = dimension_filter

    return payload


def _parse_response_rows(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    dimension_headers = [header.get("name") for header in (payload.get("dimensionHeaders") or [])]
    metric_headers = [header.get("name") for header in (payload.get("metricHeaders") or [])]
    parsed_rows: List[Dict[str, Any]] = []

    for row in payload.get("rows") or []:
        values: Dict[str, Any] = {}
        for index, name in enumerate(dimension_headers):
            if not name:
                continue
            dimension_values = row.get("dimensionValues") or []
            raw_value = dimension_values[index].get("value") if index < len(dimension_values) else None
            values[str(name)] = raw_value
        for index, name in enumerate(metric_headers):
            if not name:
                continue
            metric_values = row.get("metricValues") or []
            raw_value = metric_values[index].get("value") if index < len(metric_values) else None
            values[str(name)] = raw_value

        parsed_rows.append(
            {
                "values": values,
                "raw_row": row,
            }
        )

    return parsed_rows


async def run_ga4_report(
    *,
    start_date: str,
    end_date: str,
    dimensions: Iterable[str],
    metrics: Iterable[str],
    property_id: Optional[str] = None,
    access_token: Optional[str] = None,
    dimension_filter: Optional[Dict[str, Any]] = None,
    order_bys: Optional[List[Dict[str, Any]]] = None,
    timeout_seconds: int = GA4_TIMEOUT_SECONDS,
    page_size: int = GA4_PAGE_SIZE,
) -> Dict[str, Any]:
    resolved_property_id = _normalize_property_id(property_id) or get_default_ga4_property_id()
    if not resolved_property_id:
        raise RuntimeError("GA4_PROPERTY_ID inválido.")

    token = _safe_str(access_token) or _get_access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    url = f"{GA4_API_BASE}/properties/{resolved_property_id}:runReport"

    all_rows: List[Dict[str, Any]] = []
    offset = 0
    total_rows = 0
    response_payload: Dict[str, Any] = {}

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        while True:
            body = _build_run_report_body(
                start_date=start_date,
                end_date=end_date,
                dimensions=dimensions,
                metrics=metrics,
                limit=page_size,
                offset=offset,
                dimension_filter=dimension_filter,
                order_bys=order_bys,
            )
            response: httpx.Response | None = None
            try:
                response = await client.post(url, headers=headers, json=body)
                response.raise_for_status()
            except Exception as exc:
                if response is not None:
                    raise google_api_error(
                        response, api="Analytics Data API",
                        unavailable_code="GOOGLE_PROPERTY_UNAVAILABLE",
                        operation="consultar a propriedade GA4",
                    ) from exc
                raise
            response_payload = response.json()

            parsed_rows = _parse_response_rows(response_payload)
            all_rows.extend(parsed_rows)
            total_rows = int(response_payload.get("rowCount") or len(all_rows))

            fetched_count = len(parsed_rows)
            if fetched_count <= 0:
                break
            offset += fetched_count
            if fetched_count < page_size or offset >= total_rows:
                break

    return {
        "property_id": resolved_property_id,
        "row_count": total_rows,
        "rows": all_rows,
        "metadata": {
            "currency_code": _safe_str((response_payload.get("metadata") or {}).get("currencyCode")) or None,
            "time_zone": _safe_str((response_payload.get("metadata") or {}).get("timeZone")) or None,
        },
    }
