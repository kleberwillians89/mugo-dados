# server/services/ig_months.py
from __future__ import annotations

from typing import Dict, Any, List, Set
import httpx

from .connection_resolver import resolve_connection_for_scope
from .ig_supabase import sb_query, sb_select

def _resolve_client_id(client_id: str | None) -> str:
    cid = (client_id or "").strip()
    if not cid:
        raise RuntimeError("client_id é obrigatório")
    return cid

def _month_key(value: str | None) -> str:
    text = str(value or "").strip()
    if len(text) >= 7 and text[4:5] == "-" and text[5:7].isdigit():
        return text[:7]
    return ""


def _extract_months(rows: List[Dict[str, Any]], field_name: str) -> Set[str]:
    out: Set[str] = set()
    for row in rows:
        mk = _month_key(str(row.get(field_name) or ""))
        if mk:
            out.add(mk)
    return out


def _is_missing_column_error(exc: httpx.HTTPStatusError, column_name: str) -> bool:
    if exc.response is None:
        return False
    if exc.response.status_code not in {400, 404}:
        return False
    body = str(exc.response.text or "").lower()
    col = str(column_name or "").lower()
    return col in body and ("column" in body or "schema cache" in body)


def _is_missing_relation_error(exc: httpx.HTTPStatusError, table_name: str) -> bool:
    if exc.response is None:
        return False
    if exc.response.status_code not in {400, 404}:
        return False
    body = str(exc.response.text or "").lower()
    table = str(table_name or "").lower()
    return table in body and ("relation" in body or "does not exist" in body or "schema cache" in body)


async def _select_month_rows(
    *,
    table: str,
    field_name: str,
    client_id: str,
    connection_id: str,
    allow_missing_table: bool = False,
) -> tuple[List[Dict[str, Any]], str]:
    filters = {"client_id": f"eq.{client_id}"}
    mode = "client_scope"
    if connection_id:
        filters["connection_id"] = f"eq.{connection_id}"
        mode = "connection_scope"

    try:
        rows = await sb_select(
            table,
            select=field_name,
            filters=filters,
            order=f"{field_name}.asc",
            limit=10000,
        )
        return rows, mode
    except httpx.HTTPStatusError as exc:
        if allow_missing_table and _is_missing_relation_error(exc, table):
            return [], "table_missing"
        if not (connection_id and _is_missing_column_error(exc, "connection_id")):
            raise
        rows = await sb_select(
            table,
            select=field_name,
            filters={"client_id": f"eq.{client_id}"},
            order=f"{field_name}.asc",
            limit=10000,
        )
        return rows, "connection_column_missing"


async def get_months(client_id: str | None, connection_id: str | None = None) -> Dict[str, Any]:
    cid = _resolve_client_id(client_id)
    requested_connection = str(connection_id or "").strip()

    resolved_connection_id = ""
    resolved_connection_source = "none"
    organic_connection_id = ""
    paid_connection_id = ""

    if requested_connection:
        resolved_any = await resolve_connection_for_scope(
            client_id=cid,
            requested_connection_id=requested_connection,
        )
        resolved_connection_id = str(resolved_any.get("connection_id") or "").strip()
        resolved_connection_source = str(resolved_any.get("source") or "none").strip() or "none"
        organic_connection_id = resolved_connection_id
        paid_connection_id = resolved_connection_id
    else:
        organic_resolved = await resolve_connection_for_scope(
            client_id=cid,
            platform="instagram",
            connection_type="organic",
        )
        paid_resolved = await resolve_connection_for_scope(
            client_id=cid,
            platform="meta_ads",
            connection_type="paid",
            require_ad_account=True,
        )
        organic_connection_id = str(organic_resolved.get("connection_id") or "").strip()
        paid_connection_id = str(paid_resolved.get("connection_id") or "").strip()
        resolved_connection_id = organic_connection_id or paid_connection_id
        resolved_connection_source = (
            str(organic_resolved.get("source") or paid_resolved.get("source") or "none").strip() or "none"
        )

    print(
        "[months] request "
        f"client_id={cid} connection_id_requested={requested_connection or '-'} "
        f"connection_id_resolved={resolved_connection_id or '-'} source={resolved_connection_source} "
        f"organic_connection_id={organic_connection_id or '-'} paid_connection_id={paid_connection_id or '-'}"
    )

    snapshot_rows = await sb_query(
        "ig_profile_snapshots",
        f"client_id=eq.{cid}&select=snapshot_date&order=snapshot_date.asc"
    )

    media_rows, media_mode = await _select_month_rows(
        table="ig_media",
        field_name="timestamp",
        client_id=cid,
        connection_id=organic_connection_id,
    )

    # Inclui meses de Ads para não "parar" quando o orgânico não atualizou.
    ad_account_rows, ad_account_mode = await _select_month_rows(
        table="ad_account_daily_stats",
        field_name="stat_date",
        client_id=cid,
        connection_id=paid_connection_id,
    )
    campaign_rows, campaign_mode = await _select_month_rows(
        table="campaign_daily_stats",
        field_name="stat_date",
        client_id=cid,
        connection_id=paid_connection_id,
    )
    ad_rows, ad_mode = await _select_month_rows(
        table="ad_daily_stats",
        field_name="stat_date",
        client_id=cid,
        connection_id=paid_connection_id,
    )
    promoted_rows, promoted_mode = await _select_month_rows(
        table="promoted_post_daily_stats",
        field_name="stat_date",
        client_id=cid,
        connection_id=paid_connection_id,
        allow_missing_table=True,
    )

    months = set()
    months.update(_extract_months(snapshot_rows, "snapshot_date"))
    months.update(_extract_months(media_rows, "timestamp"))
    months.update(_extract_months(ad_account_rows, "stat_date"))
    months.update(_extract_months(campaign_rows, "stat_date"))
    months.update(_extract_months(ad_rows, "stat_date"))
    months.update(_extract_months(promoted_rows, "stat_date"))

    sorted_months = sorted(months)

    print(
        "[months] result "
        f"client_id={cid} months={len(sorted_months)} "
        f"snapshots={len(snapshot_rows)} media={len(media_rows)} ad_account={len(ad_account_rows)} "
        f"campaign={len(campaign_rows)} ad={len(ad_rows)} promoted={len(promoted_rows)} "
        f"modes=media:{media_mode}|ad_account:{ad_account_mode}|campaign:{campaign_mode}|ad:{ad_mode}|promoted:{promoted_mode}"
    )

    return {
        "ok": True,
        "client_id": cid,
        "connection_id": resolved_connection_id or None,
        "months": sorted_months,
    }
