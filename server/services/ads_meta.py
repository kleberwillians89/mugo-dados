from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl, urlsplit

from .meta_http import META_BASE, meta_get_json
from .integration_errors import IntegrationError


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _clip(value: Any, size: int = 600) -> str:
    text = _safe_str(value)
    if len(text) <= size:
        return text
    return f"{text[:size]}..."


# Teto rígido de páginas por chamada paginada. Sem esse limite, uma conta
# com volume incomum de linhas (ex.: nível "ad" com time_increment=1 em
# janela larga) pode paginar indefinidamente, mantendo lock e job_run
# abertos sem previsão de término. Valor provisório — reavaliar após
# observar `pages=` real nos logs [ads_meta][insights] em produção.
_MAX_INSIGHTS_PAGES = 200


def normalize_ad_account_id(ad_account_id: str) -> str:
    raw = _safe_str(ad_account_id)
    if not raw:
        return ""
    return raw if raw.startswith("act_") else f"act_{raw}"


async def _meta_get(
    url: str,
    params: Optional[Dict[str, Any]] = None,
    *,
    request_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return await meta_get_json(
        url,
        params=params,
        timeout=60,
        retries=3,
        context=request_context,
    )


async def fetch_ad_account_insights(
    *,
    ad_account_id: str,
    access_token: str,
    since: str,
    until: str,
    level: str | None = None,
    fields: str | None = None,
    time_increment: int | str | None = 1,
    date_preset: str | None = None,
    limit: int = 200,
    request_context: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    act_id = normalize_ad_account_id(ad_account_id)
    token = _safe_str(access_token)
    if not act_id:
        raise RuntimeError("ad_account_id inválido para insights.")
    if not token:
        raise RuntimeError("access_token inválido para insights.")

    selected_fields = fields or (
        "account_id,account_name,date_start,date_stop,"
        "spend,impressions,reach,clicks,cpc,ctr,cpm,frequency,actions,action_values"
    )

    configured_time_increment = "-"
    if isinstance(time_increment, str):
        configured_time_increment = _safe_str(time_increment) or "-"
    elif time_increment is not None:
        configured_time_increment = str(max(1, int(time_increment)))

    next_url: Optional[str] = f"{META_BASE}/{act_id}/insights"
    next_params: Optional[Dict[str, Any]] = {
        "fields": selected_fields,
        "limit": max(1, min(int(limit), 1000)),
        "access_token": token,
    }
    if isinstance(time_increment, str):
        text_increment = _safe_str(time_increment)
        if text_increment:
            next_params["time_increment"] = text_increment
    elif time_increment is not None:
        next_params["time_increment"] = max(1, int(time_increment))

    preset = _safe_str(date_preset)
    if preset:
        next_params["date_preset"] = preset
    else:
        next_params["time_range"] = json.dumps({"since": since, "until": until})

    if level:
        next_params["level"] = level

    rows: List[Dict[str, Any]] = []
    pages = 0
    visited_pages = set()
    visited_cursors = set()
    received_rows = set()

    def incomplete(reason: str) -> IntegrationError:
        # Nunca registrar URLs/cursors: paging.next pode carregar access_token.
        print(
            "[ads_meta][insights][incomplete] "
            f"reason={reason} pages={pages} max_pages={_MAX_INSIGHTS_PAGES} rows_received={len(rows)}"
        )
        return IntegrationError(
            "A paginação de Meta Ads ficou incompleta. Nenhum sucesso completo foi registrado.",
            status_code=502, code="META_ADS_PAGINATION_INCOMPLETE", provider="meta",
            diagnostics={"incomplete": True, "reason": reason, "pages": pages, "rows_received": len(rows)},
        )

    while next_url:
        parsed = urlsplit(next_url)
        if parsed.scheme not in {"https", "http"} or not parsed.netloc:
            raise incomplete("invalid_next_url")
        page_key = (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path,
                    tuple(sorted((k, v) for k, v in parse_qsl(parsed.query) if k != "access_token")))
        if page_key in visited_pages:
            raise incomplete("repeated_next_url")
        if pages >= _MAX_INSIGHTS_PAGES:
            raise incomplete("safety_limit_reached")
        visited_pages.add(page_key)
        pages += 1
        payload = await _meta_get(
            next_url,
            params=next_params,
            request_context={
                "resource": "ad_account_insights",
                "ad_account_id": act_id,
                **(request_context or {}),
            },
        )
        data_rows = payload.get("data") or []
        if isinstance(data_rows, list):
            for row in data_rows:
                if isinstance(row, dict):
                    signature = json.dumps(row, sort_keys=True, separators=(",", ":"))
                    if signature not in received_rows:
                        received_rows.add(signature)
                        rows.append(row)

        paging = payload.get("paging") or {}
        next_value = _safe_str(paging.get("next"))
        if not next_value:
            break
        cursor = _safe_str((paging.get("cursors") or {}).get("after"))
        if cursor:
            if cursor in visited_cursors:
                raise incomplete("repeated_cursor")
            visited_cursors.add(cursor)
        next_url = next_value
        next_params = None

    print(
        "[ads_meta][insights] "
        f"ad_account_id={act_id} since={since} until={until} level={_safe_str(level) or '-'} "
        f"time_increment={configured_time_increment} date_preset={preset or '-'} "
        f"pages={pages} rows={len(rows)}"
    )
    return rows


async def fetch_entity_insights(
    *,
    entity_id: str,
    access_token: str,
    since: str,
    until: str,
    fields: str,
    level: str | None = None,
    time_increment: int | str | None = 1,
    limit: int = 200,
    request_context: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    normalized_entity_id = _safe_str(entity_id)
    token = _safe_str(access_token)
    if not normalized_entity_id:
        raise RuntimeError("entity_id inválido para insights.")
    if not token:
        raise RuntimeError("access_token inválido para insights.")

    configured_time_increment = "-"
    if isinstance(time_increment, str):
        configured_time_increment = _safe_str(time_increment) or "-"
    elif time_increment is not None:
        configured_time_increment = str(max(1, int(time_increment)))

    next_url: Optional[str] = f"{META_BASE}/{normalized_entity_id}/insights"
    next_params: Optional[Dict[str, Any]] = {
        "fields": fields,
        "limit": max(1, min(int(limit), 1000)),
        "access_token": token,
        "time_range": json.dumps({"since": since, "until": until}),
    }
    if isinstance(time_increment, str):
        text_increment = _safe_str(time_increment)
        if text_increment:
            next_params["time_increment"] = text_increment
    elif time_increment is not None:
        next_params["time_increment"] = max(1, int(time_increment))

    if level:
        next_params["level"] = level

    rows: List[Dict[str, Any]] = []
    pages = 0

    while next_url:
        pages += 1
        payload = await _meta_get(
            next_url,
            params=next_params,
            request_context={
                "resource": "entity_insights",
                "entity_id": normalized_entity_id,
                **(request_context or {}),
            },
        )
        data_rows = payload.get("data") or []
        if isinstance(data_rows, list):
            for row in data_rows:
                if isinstance(row, dict):
                    rows.append(row)

        paging = payload.get("paging") or {}
        next_value = _safe_str(paging.get("next"))
        if not next_value:
            break
        next_url = next_value
        next_params = None

    print(
        "[ads_meta][entity_insights] "
        f"entity_id={normalized_entity_id} since={since} until={until} level={_safe_str(level) or '-'} "
        f"time_increment={configured_time_increment} "
        f"pages={pages} rows={len(rows)}"
    )
    return rows


async def fetch_ad_catalog(
    *,
    ad_account_id: str,
    access_token: str,
    fields: str | None = None,
    effective_statuses: Optional[List[str]] = None,
    limit: int = 200,
    request_context: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    act_id = normalize_ad_account_id(ad_account_id)
    token = _safe_str(access_token)
    if not act_id:
        raise RuntimeError("ad_account_id inválido para catálogo de Ads.")
    if not token:
        raise RuntimeError("access_token inválido para catálogo de Ads.")

    selected_fields = fields or (
        "id,name,status,effective_status,campaign_id,adset_id,"
        "campaign{id,name,objective},adset{id,name},"
        "creative{id,object_story_id,effective_object_story_id,object_id},"
        "promoted_object"
    )

    next_url: Optional[str] = f"{META_BASE}/{act_id}/ads"
    next_params: Optional[Dict[str, Any]] = {
        "fields": selected_fields,
        "limit": max(1, min(int(limit), 1000)),
        "access_token": token,
    }
    statuses = [str(s or "").strip() for s in (effective_statuses or []) if str(s or "").strip()]
    if statuses:
        next_params["effective_status"] = json.dumps(statuses)

    rows: List[Dict[str, Any]] = []
    pages = 0

    while next_url:
        pages += 1
        payload = await _meta_get(
            next_url,
            params=next_params,
            request_context={
                "resource": "ad_catalog",
                "ad_account_id": act_id,
                **(request_context or {}),
            },
        )
        data_rows = payload.get("data") or []
        if isinstance(data_rows, list):
            for row in data_rows:
                if isinstance(row, dict):
                    rows.append(row)

        paging = payload.get("paging") or {}
        next_value = _safe_str(paging.get("next"))
        if not next_value:
            break
        next_url = next_value
        next_params = None

    print(
        "[ads_meta][catalog] "
        f"ad_account_id={act_id} pages={pages} rows={len(rows)} statuses={len(statuses)}"
    )
    return rows


async def fetch_ad_creatives(
    *,
    ad_account_id: str,
    access_token: str,
    fields: str | None = None,
    limit: int = 200,
    request_context: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    act_id = normalize_ad_account_id(ad_account_id)
    token = _safe_str(access_token)
    if not act_id:
        raise RuntimeError("ad_account_id inválido para adcreatives.")
    if not token:
        raise RuntimeError("access_token inválido para adcreatives.")

    selected_fields = fields or (
        "id,name,object_story_id,effective_object_story_id,object_id,"
        "object_story_spec,instagram_permalink_url,thumbnail_url,status"
    )

    next_url: Optional[str] = f"{META_BASE}/{act_id}/adcreatives"
    next_params: Optional[Dict[str, Any]] = {
        "fields": selected_fields,
        "limit": max(1, min(int(limit), 1000)),
        "access_token": token,
    }

    rows: List[Dict[str, Any]] = []
    pages = 0
    while next_url:
        pages += 1
        payload = await _meta_get(
            next_url,
            params=next_params,
            request_context={
                "resource": "ad_creatives",
                "ad_account_id": act_id,
                **(request_context or {}),
            },
        )
        data_rows = payload.get("data") or []
        if isinstance(data_rows, list):
            for row in data_rows:
                if isinstance(row, dict):
                    rows.append(row)
        paging = payload.get("paging") or {}
        next_value = _safe_str(paging.get("next"))
        if not next_value:
            break
        next_url = next_value
        next_params = None

    print(
        "[ads_meta][adcreatives] "
        f"ad_account_id={act_id} pages={pages} rows={len(rows)}"
    )
    return rows
