from __future__ import annotations

from collections import Counter
from typing import Any, Awaitable, Callable, Dict

SelectFn = Callable[..., Awaitable[list[Dict[str, Any]]]]

VALID_PROVIDERS = {"meta", "instagram", "google_ads", "ga4", "shopify", "fbits"}
VALID_GENERIC_STATUSES = {
    "not_configured", "awaiting_authorization", "selection_required", "connecting",
    "importing", "connected", "updated", "stale", "token_expired",
    "reauth_required", "sync_error", "disconnected",
}
ACTIVE_GENERIC_STATUSES = {"connected", "selection_required", "updated", "stale"}
ACTIVE_META_STATUSES = {"active", "connected", "ok"}
SECRET_FIELDS = {
    "encrypted_token", "encrypted_access_token", "encrypted_refresh_token",
    "access_token", "refresh_token", "token", "secret",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if _text(value).lower() in {"true", "1", "yes"}:
        return True
    if _text(value).lower() in {"false", "0", "no"}:
        return False
    return None


def _token_presence(row: Dict[str, Any]) -> tuple[bool | None, bool | None]:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    declared_token = _bool(row.get("token_available"))
    declared_refresh = _bool(row.get("refresh_token_available"))
    if declared_token is None:
        declared_token = _bool(metadata.get("token_available"))
    if declared_refresh is None:
        declared_refresh = _bool(metadata.get("refresh_token_available"))
    encrypted_token = bool(_text(row.get("encrypted_token")))
    encrypted_access = bool(_text(row.get("encrypted_access_token")))
    encrypted_refresh = bool(_text(row.get("encrypted_refresh_token")))
    token_available = declared_token if declared_token is not None else (encrypted_token or encrypted_access or encrypted_refresh)
    refresh_available = declared_refresh if declared_refresh is not None else (
        True if encrypted_refresh else False if not encrypted_token else None
    )
    return token_available, refresh_available


def _safe_row(row: Dict[str, Any]) -> Dict[str, Any]:
    token_available, refresh_available = _token_presence(row)
    credential_fields_visible = any(field in row for field in ("encrypted_token", "encrypted_access_token", "encrypted_refresh_token"))
    physical_token_available = any(bool(_text(row.get(field))) for field in ("encrypted_token", "encrypted_access_token", "encrypted_refresh_token")) if credential_fields_visible else None
    return {
        key: value for key, value in row.items()
        if key.lower() not in SECRET_FIELDS
    } | {
        "token_available": token_available,
        "refresh_token_available": refresh_available,
        "physical_token_available": physical_token_available,
    }


def _issue(
    severity: str, code: str, row: Dict[str, Any],
    safe_reason: str, suggested_action: str, **extra: Any,
) -> Dict[str, Any]:
    return {
        "severity": severity,
        "code": code,
        "client_id": _text(row.get("client_id")) or None,
        "provider": _text(row.get("provider") or row.get("platform")) or None,
        "connection_id": _text(row.get("id") or row.get("connection_id")) or None,
        "safe_reason": safe_reason,
        "suggested_action": suggested_action,
        **extra,
    }


async def _optional_select(select_fn: SelectFn, table: str, **kwargs: Any) -> tuple[list[Dict[str, Any]], str | None]:
    try:
        return await select_fn(table, **kwargs), None
    except Exception as exc:
        return [], exc.__class__.__name__


async def audit_existing_connections(select_fn: SelectFn) -> Dict[str, Any]:
    raw_generic = await select_fn("integration_connections", order="updated_at.desc", limit=10000)
    raw_meta = await select_fn("meta_connections", order="updated_at.desc", limit=10000)
    generic = [_safe_row(row) for row in raw_generic]
    meta = [_safe_row(row) for row in raw_meta]
    issues: list[Dict[str, Any]] = []

    reference_tables = {
        "sync_checkpoints": "generic",
        "shopify_stores": "generic",
        "cron_job_runs": "meta",
        "ig_profile_snapshots": "meta",
        "ig_media": "meta",
        "ig_comments": "meta",
        "ad_account_daily_stats": "meta",
        "campaign_daily_stats": "meta",
        "ad_daily_stats": "meta",
        "promoted_post_daily_stats": "meta",
    }
    references: Dict[str, list[Dict[str, Any]]] = {}
    unavailable_tables: Dict[str, str] = {}
    for table in reference_tables:
        rows, error = await _optional_select(
            select_fn, table, select="client_id,connection_id", limit=10000,
        )
        references[table] = rows
        if error:
            unavailable_tables[table] = error
            issues.append(_issue(
                "info", "AUDIT_TABLE_UNAVAILABLE", {"provider": "audit"},
                f"A tabela opcional {table} não pôde ser consultada com a credencial atual.",
                "grant_read_only_select_or_confirm_table_is_not_applicable", table=table,
            ))

    generic_ids = {_text(row.get("id")): row for row in generic if _text(row.get("id"))}
    meta_ids = {_text(row.get("id")): row for row in meta if _text(row.get("id"))}

    duplicate_keys = Counter(
        (_text(row.get("client_id")), _text(row.get("provider")), _text(row.get("external_key")))
        for row in generic if _text(row.get("external_key"))
    )
    for (client_id, provider, _external_key), count in duplicate_keys.items():
        if count > 1:
            issues.append(_issue(
                "critical", "DUPLICATE_EXTERNAL_CONNECTION",
                {"client_id": client_id, "provider": provider},
                "Existem conexões duplicadas para tenant, provider e identificador externo.",
                "review_and_select_canonical_connection", count=count,
            ))

    active_counts = Counter(
        (_text(row.get("client_id")), _text(row.get("provider")))
        for row in generic
        if _text(row.get("status")).lower() in ACTIVE_GENERIC_STATUSES
        and not _text(row.get("disconnected_at"))
    )
    for (client_id, provider), count in active_counts.items():
        if count > 1:
            issues.append(_issue(
                "critical", "MULTIPLE_ACTIVE_CONNECTIONS",
                {"client_id": client_id, "provider": provider},
                "Mais de uma conexão ativa atende ao mesmo tenant e provider.",
                "explicitly_choose_and_disconnect_duplicates", count=count,
            ))

    for row in generic:
        provider = _text(row.get("provider")).lower()
        status = _text(row.get("status")).lower()
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        if not _text(row.get("client_id")):
            issues.append(_issue("critical", "CLIENT_ID_MISSING", row, "A conexão não possui tenant.", "assign_valid_tenant"))
        if not provider or provider not in VALID_PROVIDERS:
            issues.append(_issue("critical", "PROVIDER_INVALID", row, "O provider está ausente ou fora do catálogo permitido.", "classify_connection_provider"))
        if status not in VALID_GENERIC_STATUSES:
            issues.append(_issue("critical", "STATUS_INCOMPATIBLE", row, "O status da conexão não pertence à taxonomia suportada.", "normalize_connection_status"))
        if status in ACTIVE_GENERIC_STATUSES and row.get("token_available") is False:
            issues.append(_issue("critical", "TOKEN_UNAVAILABLE", row, "A conexão está ativa sem credencial criptografada disponível.", "reauthorize_connection"))
        declared = _bool(metadata.get("token_available"))
        if declared is not None and row.get("physical_token_available") is not None and declared != row.get("physical_token_available"):
            issues.append(_issue("warning", "TOKEN_AVAILABLE_INCONSISTENT", row, "A flag segura de token diverge da presença da credencial criptografada.", "recompute_safe_token_availability"))
        if provider == "ga4" and status in ACTIVE_GENERIC_STATUSES:
            if row.get("refresh_token_available") is False:
                issues.append(_issue("critical", "GA4_REFRESH_TOKEN_MISSING", row, "A conexão GA4 não possui refresh token criptografado.", "reauthorize_ga4_with_offline_access"))
            elif row.get("refresh_token_available") is None:
                issues.append(_issue("warning", "GA4_REFRESH_TOKEN_UNVERIFIED", row, "O schema legado não expõe uma flag segura para confirmar refresh token sem descriptografia.", "verify_with_safe_refresh_token_available_view"))
        if provider == "google_ads" and (status == "disconnected" or _text(row.get("disconnected_at"))):
            issues.append(_issue("info", "GOOGLE_ADS_DISCONNECTED", row, "A conexão Google Ads está desconectada e não deve ser selecionada.", "confirm_no_active_reference"))
        if provider == "shopify" and not _text(row.get("external_key") or metadata.get("shop_domain")):
            issues.append(_issue("warning", "SHOPIFY_DOMAIN_MISSING", row, "A conexão Shopify não identifica uma loja.", "reconnect_or_select_shop_domain"))

    meta_auth = [
        row for row in generic
        if _text(row.get("provider")) == "meta"
        and _text(row.get("status")).lower() in ACTIVE_GENERIC_STATUSES
        and not _text(row.get("disconnected_at"))
    ]
    auth_by_client: Dict[str, list[Dict[str, Any]]] = {}
    projection_by_client: Dict[str, list[Dict[str, Any]]] = {}
    for row in meta_auth:
        auth_by_client.setdefault(_text(row.get("client_id")), []).append(row)
    for row in meta:
        if _text(row.get("status")).lower() in ACTIVE_META_STATUSES and row.get("is_active") is not False:
            projection_by_client.setdefault(_text(row.get("client_id")), []).append(row)

    for client_id in sorted(set(auth_by_client) | set(projection_by_client)):
        auth_rows = auth_by_client.get(client_id, [])
        projections = projection_by_client.get(client_id, [])
        if auth_rows and not projections:
            issues.append(_issue("critical", "META_AUTHORIZATION_WITHOUT_PROJECTION", auth_rows[0], "A autorização Meta ativa não possui projeção operacional.", "run_explicit_meta_projection_repair"))
        if projections and not auth_rows:
            issues.append(_issue("critical", "META_PROJECTION_WITHOUT_AUTHORIZATION", projections[0], "A projeção Meta está ativa sem autorização válida.", "disconnect_projection_or_reauthorize_explicitly"))
        projection_counts = Counter((_text(row.get("platform")), _text(row.get("connection_type"))) for row in projections)
        for (platform, kind), count in projection_counts.items():
            if count > 1:
                issues.append(_issue("critical", "META_MULTIPLE_ACTIVE_PROJECTIONS", {"client_id": client_id, "provider": platform}, "Há múltiplas projeções Meta ativas para a mesma capacidade.", "repair_meta_projection_explicitly", count=count, connection_type=kind))
        if len(auth_rows) == 1:
            auth = auth_rows[0]
            metadata = auth.get("metadata") if isinstance(auth.get("metadata"), dict) else {}
            comparisons = (
                ("selected_page_id", "instagram", "business_id"),
                ("selected_instagram_id", "instagram", "ig_user_id"),
                ("selected_ad_account_id", "meta_ads", "ad_account_id"),
            )
            for selected_field, platform, projection_field in comparisons:
                expected = _text(metadata.get(selected_field))
                actual = {
                    _text(row.get(projection_field)) for row in projections
                    if _text(row.get("platform")) == platform and _text(row.get(projection_field))
                }
                if expected and (not actual or expected not in actual):
                    issues.append(_issue("critical", f"META_{selected_field.upper()}_DRIFT", auth, f"{selected_field} diverge da projeção operacional.", "review_meta_assets_and_run_explicit_repair"))

    for table, kind in reference_tables.items():
        target_ids = generic_ids if kind == "generic" else meta_ids
        for reference in references.get(table, []):
            connection_id = _text(reference.get("connection_id"))
            if not connection_id:
                continue
            target = target_ids.get(connection_id)
            if not target:
                issues.append(_issue("critical", "CONNECTION_REFERENCE_NOT_FOUND", {**reference, "provider": kind}, f"{table} referencia uma conexão inexistente.", "review_orphan_reference_without_automatic_write", table=table))
            elif _text(target.get("status")).lower() == "disconnected" or _text(target.get("disconnected_at")):
                issues.append(_issue("critical", "DISCONNECTED_CONNECTION_REFERENCED", target, f"{table} ainda referencia uma conexão desconectada.", "move_reference_to_explicit_active_connection", table=table))

    severities = Counter(issue["severity"] for issue in issues)
    return {
        "ok": True,
        "dry_run": True,
        "read_only": True,
        "scanned": {
            "integration_connections": len(generic),
            "meta_connections": len(meta),
            **{table: len(rows) for table, rows in references.items()},
        },
        "unavailable_tables": unavailable_tables,
        "coverage": {
            "database_configuration_references": sorted(reference_tables),
            "browser_local_or_session_storage": "not_stored_in_supabase_and_requires_browser_smoke_test",
        },
        "summary": {key: severities[key] for key in ("critical", "warning", "info")},
        "issues": issues,
    }


def assert_report_has_no_secrets(report: Dict[str, Any]) -> None:
    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key.lower() in SECRET_FIELDS:
                    raise RuntimeError(f"AUDIT_SECRET_FIELD_BLOCKED:{key}")
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(report)
