import asyncio
import os
import time
from typing import Any, Dict, List, Optional

import httpx


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _assert_env() -> None:
    url = _env("SUPABASE_URL")
    key = _env("SUPABASE_SERVICE_ROLE_KEY")

    if not url.startswith("http://") and not url.startswith("https://"):
        raise RuntimeError("Missing or invalid environment variable: SUPABASE_URL.")
    if len(key) < 20:
        raise RuntimeError("Missing or invalid environment variable: SUPABASE_SERVICE_ROLE_KEY.")


def _headers() -> Dict[str, str]:
    key = _env("SUPABASE_SERVICE_ROLE_KEY")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _base_url() -> str:
    return _env("SUPABASE_URL").rstrip("/") + "/rest/v1"


def _response_text(exc: httpx.HTTPStatusError) -> str:
    try:
        return (exc.response.text or "").strip()
    except Exception:
        return ""


def _is_column_compat_error(exc: httpx.HTTPStatusError, column_name: str) -> bool:
    if exc.response is None:
        return False
    if exc.response.status_code not in {400, 404}:
        return False
    txt = _response_text(exc).lower()
    col = column_name.lower()
    return col in txt or "column" in txt or "schema cache" in txt


def _is_retryable_transport_error(exc: Exception) -> bool:
    return isinstance(
        exc,
        (
            httpx.ReadError,
            httpx.ReadTimeout,
            httpx.RemoteProtocolError,
            httpx.ConnectError,
            httpx.PoolTimeout,
        ),
    )


def _retry_budget(method: str) -> int:
    return 3 if method.upper() in {"GET", "PATCH"} else 1


async def _request(
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json: Any = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 60,
) -> Any:
    _assert_env()
    h = _headers()
    if headers:
        h.update(headers)

    url = f"{_base_url()}{path}"
    attempts = _retry_budget(method)
    resolved_timeout = httpx.Timeout(
        timeout,
        connect=min(15, timeout),
        read=timeout,
        write=timeout,
        pool=min(15, timeout),
    )

    async with httpx.AsyncClient(timeout=resolved_timeout) as client:
        for attempt in range(1, attempts + 1):
            started = time.perf_counter()
            try:
                r = await client.request(method, url, headers=h, params=params, json=json)
            except Exception as exc:
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                print(
                    "[supabase][request_error] "
                    f"method={method} path={path} timeout={timeout} duration_ms={elapsed_ms} "
                    f"attempt={attempt}/{attempts} error={exc.__class__.__name__}: {str(exc)[:260]}"
                )
                if _is_retryable_transport_error(exc) and attempt < attempts:
                    backoff_ms = 200 * attempt
                    print(
                        "[supabase][request_retry] "
                        f"method={method} path={path} retry_in_ms={backoff_ms}"
                    )
                    await asyncio.sleep(backoff_ms / 1000)
                    continue
                raise

            elapsed_ms = int((time.perf_counter() - started) * 1000)
            print(
                "[supabase][request_done] "
                f"method={method} path={path} status={r.status_code} duration_ms={elapsed_ms} "
                f"attempt={attempt}/{attempts}"
            )
            if r.status_code >= 400:
                body = (r.text or "").strip().replace("\n", " ")
                if len(body) > 500:
                    body = f"{body[:500]}..."
                print(
                    "[supabase][http_error] "
                    f"method={method} path={path} status={r.status_code} duration_ms={elapsed_ms} body={body or '-'}"
                )
            r.raise_for_status()
            if not r.text:
                return None
            try:
                return r.json()
            except Exception:
                return None


async def sb_query(table: str, query: str) -> List[Dict[str, Any]]:
    """
    Compat helper: aceita query pronta.
    Ex: sb_query("ig_profile_snapshots", "client_id=eq.xxx&order=snapshot_date.asc")
    """
    data = await _request("GET", f"/{table}?{query}&select=*")
    return data if isinstance(data, list) else []


async def sb_select(
    table: str,
    *,
    select: str = "*",
    filters: Optional[Dict[str, str]] = None,
    order: Optional[str] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"select": select}
    if filters:
        params.update(filters)
    if order:
        params["order"] = order
    if limit is not None:
        params["limit"] = str(limit)
    if offset is not None:
        params["offset"] = str(max(0, int(offset)))

    data = await _request("GET", f"/{table}", params=params)
    return data if isinstance(data, list) else []


async def sb_get_one(
    table: str,
    query: str,
) -> Optional[Dict[str, Any]]:
    data = await _request("GET", f"/{table}?{query}&select=*")
    if isinstance(data, list) and data:
        return data[0]
    return None


async def sb_get_one_by(
    table: str,
    *,
    filters: Dict[str, str],
    select: str = "*",
    order: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    rows = await sb_select(table, select=select, filters=filters, order=order, limit=1)
    return rows[0] if rows else None


async def sb_insert(table: str, row: Dict[str, Any], returning: str = "representation") -> Optional[Dict[str, Any]]:
    headers = {"Prefer": f"return={returning}"}
    data = await _request("POST", f"/{table}", json=[row], headers=headers)
    if returning == "minimal":
        return {"ok": True}
    if isinstance(data, list) and data:
        return data[0]
    return None


async def sb_insert_many(table: str, rows: List[Dict[str, Any]], returning: str = "minimal") -> Dict[str, Any] | List[Dict[str, Any]]:
    if not rows:
        return {"ok": True, "count": 0}

    headers = {"Prefer": f"return={returning}"}
    data = await _request("POST", f"/{table}", json=rows, headers=headers)
    if returning == "minimal":
        return {"ok": True, "count": len(rows)}
    return data if isinstance(data, list) else []


async def sb_update(
    table: str,
    *,
    filters: Dict[str, str],
    patch: Dict[str, Any],
    returning: str = "representation",
) -> List[Dict[str, Any]]:
    headers = {"Prefer": f"return={returning}"}
    params = dict(filters)
    data = await _request("PATCH", f"/{table}", params=params, json=patch, headers=headers)
    if returning == "minimal":
        return []
    return data if isinstance(data, list) else []


async def sb_delete(
    table: str,
    *,
    filters: Dict[str, str],
    returning: str = "representation",
) -> List[Dict[str, Any]]:
    headers = {"Prefer": f"return={returning}"}
    params = dict(filters)
    data = await _request("DELETE", f"/{table}", params=params, headers=headers)
    if returning == "minimal":
        return []
    return data if isinstance(data, list) else []


async def sb_upsert(table: str, rows: List[Dict[str, Any]], on_conflict: str) -> Dict[str, Any]:
    headers = {"Prefer": "resolution=merge-duplicates,return=minimal"}
    await _request("POST", f"/{table}", params={"on_conflict": on_conflict}, json=rows, headers=headers)
    return {"ok": True}


async def sb_rpc(fn_name: str, args: Dict[str, Any]) -> Any:
    return await _request("POST", f"/rpc/{fn_name}", json=args, timeout=30)


async def sb_upload_public(path: str, content: bytes, content_type: str) -> str:
    """
    Faz upload no bucket IG_MEDIA_BUCKET e retorna URL pública.
    """
    _assert_env()
    bucket = _env("IG_MEDIA_BUCKET") or "ig-media"

    supa_url = _env("SUPABASE_URL").rstrip("/")
    key = _env("SUPABASE_SERVICE_ROLE_KEY")

    upload_url = f"{supa_url}/storage/v1/object/{bucket}/{path}"
    headers = {
        "Authorization": f"Bearer {key}",
        "apikey": key,
        "Content-Type": content_type or "application/octet-stream",
        "x-upsert": "true",
    }

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(upload_url, headers=headers, content=content)
        r.raise_for_status()

    return f"{supa_url}/storage/v1/object/public/{bucket}/{path}"


async def sb_get_client_memberships(user_id: str) -> List[Dict[str, Any]]:
    uid = (user_id or "").strip()
    if not uid:
        return []

    try:
        try:
            rows = await sb_select(
                "client_memberships",
                # Evita select embutido de relação (clients(...)) porque pode falhar
                # em ambientes onde a FK/relationship não está exposta no PostgREST.
                select="id,user_id,client_id,role,created_at",
                filters={"user_id": f"eq.{uid}"},
                order="created_at.asc",
            )
        except httpx.HTTPStatusError as exc:
            # Compat: schema legado sem created_at em client_memberships.
            if not _is_column_compat_error(exc, "created_at"):
                raise
            rows = await sb_select(
                "client_memberships",
                select="id,user_id,client_id,role",
                filters={"user_id": f"eq.{uid}"},
                order="client_id.asc",
            )

        out: List[Dict[str, Any]] = []
        for r in rows:
            cid = str(r.get("client_id") or "").strip()
            c = await sb_get_one("clients", f"id=eq.{cid}")
            out.append(
                {
                    **r,
                    "clients": {
                        "id": (c or {}).get("id"),
                        "name": (c or {}).get("name") or "Sem nome",
                        "created_at": (c or {}).get("created_at"),
                    },
                }
            )
        return out
    except httpx.HTTPStatusError as exc:
        # Compat: ambiente antigo ainda com tabela client_users.
        if exc.response is None or exc.response.status_code != 404:
            raise

        legacy_table = (_env("CLIENT_USERS_TABLE") or "client_users").strip()
        legacy_rows = await sb_select(
            legacy_table,
            select="user_id,client_id",
            filters={"user_id": f"eq.{uid}"},
            order="client_id.asc",
        )

        out: List[Dict[str, Any]] = []
        for r in legacy_rows:
            cid = str(r.get("client_id") or "").strip()
            if not cid:
                continue
            c = await sb_get_one("clients", f"id=eq.{cid}")
            out.append(
                {
                    "id": None,
                    "user_id": uid,
                    "client_id": cid,
                    "role": "owner",
                    "created_at": None,
                    "clients": {
                        "id": (c or {}).get("id"),
                        "name": (c or {}).get("name") or "Sem nome",
                        "created_at": (c or {}).get("created_at"),
                    },
                }
            )
        return out


async def sb_get_client_id_for_user(user_id: str, requested_client_id: Optional[str] = None) -> str:
    """
    Resolve client_id para usuário autenticado.
    Se requested_client_id vier, valida membership naquele client.
    """
    uid = (user_id or "").strip()
    if not uid:
        raise RuntimeError("user_id vazio (sb_get_client_id_for_user)")

    req = (requested_client_id or "").strip()
    rows: List[Dict[str, Any]] = []
    try:
        if req:
            filters = {"user_id": f"eq.{uid}", "client_id": f"eq.{req}"}
            try:
                maybe = await sb_get_one_by(
                    "client_memberships",
                    filters=filters,
                    select="client_id",
                    order="created_at.asc",
                )
            except httpx.HTTPStatusError as exc:
                # Compat: schema legado sem created_at em client_memberships.
                if not _is_column_compat_error(exc, "created_at"):
                    raise
                maybe = await sb_get_one_by(
                    "client_memberships",
                    filters=filters,
                    select="client_id",
                    order="client_id.asc",
                )
            rows = [maybe] if maybe else []
        else:
            try:
                rows = await sb_select(
                    "client_memberships",
                    select="client_id",
                    filters={"user_id": f"eq.{uid}"},
                    order="created_at.asc",
                    limit=200,
                )
            except httpx.HTTPStatusError as exc:
                # Compat: schema legado sem created_at em client_memberships.
                if not _is_column_compat_error(exc, "created_at"):
                    raise
                rows = await sb_select(
                    "client_memberships",
                    select="client_id",
                    filters={"user_id": f"eq.{uid}"},
                    order="client_id.asc",
                    limit=200,
                )
    except httpx.HTTPStatusError as exc:
        # Compat com esquema legado.
        if exc.response is None or exc.response.status_code != 404:
            raise
        legacy_table = (_env("CLIENT_USERS_TABLE") or "client_users").strip()
        if req:
            maybe = await sb_get_one_by(
                legacy_table,
                filters={"user_id": f"eq.{uid}", "client_id": f"eq.{req}"},
                select="client_id",
                order="client_id.asc",
            )
            rows = [maybe] if maybe else []
        else:
            rows = await sb_select(
                legacy_table,
                select="client_id",
                filters={"user_id": f"eq.{uid}"},
                order="client_id.asc",
                limit=200,
            )

    rows = [r for r in rows if isinstance(r, dict)]
    if not rows:
        raise PermissionError("Usuário não possui acesso ao cliente solicitado.")

    if not req and len(rows) > 1:
        raise PermissionError(
            "Usuário possui múltiplos clientes. Informe client_id explicitamente."
        )

    cid = str(rows[0].get("client_id") or "").strip()
    if not cid:
        raise RuntimeError("client_id vazio na tabela client_memberships")
    return cid


async def sb_get_connection_for_client(client_id: str, connection_id: str) -> Optional[Dict[str, Any]]:
    cid = (client_id or "").strip()
    conn_id = (connection_id or "").strip()
    if not cid or not conn_id:
        return None
    rows = await sb_select(
        "meta_connections",
        select="id,client_id,platform,connection_type,status,updated_at",
        filters={"id": f"eq.{conn_id}", "client_id": f"eq.{cid}"},
        limit=1,
    )
    return rows[0] if rows else None


async def sb_get_active_instagram_connections() -> List[Dict[str, Any]]:
    return await sb_select(
        "meta_connections",
        select=(
            "id,client_id,platform,connection_type,status,expires_at,token_last_refreshed_at,"
            "token_expires_at,last_validated_at,last_sync_at,last_synced_at,last_sync_status,"
            "requires_reauth,is_active,updated_at,ig_user_id,ad_account_id,meta_user_id,username,"
            "business_id,ad_account_name,scopes_json,encrypted_access_token,access_token,last_error"
        ),
        filters={
            "platform": "eq.instagram",
            "connection_type": "eq.organic",
            "status": "eq.active",
        },
        order="updated_at.asc",
    )


async def sb_get_active_meta_connections(
    *,
    platform: Optional[str] = None,
    connection_type: Optional[str] = None,
    client_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    filters: Dict[str, str] = {"status": "eq.active"}
    if platform:
        filters["platform"] = f"eq.{platform}"
    if connection_type:
        filters["connection_type"] = f"eq.{connection_type}"
    if client_id:
        filters["client_id"] = f"eq.{client_id}"

    return await sb_select(
        "meta_connections",
        select=(
            "id,client_id,platform,connection_type,status,expires_at,token_last_refreshed_at,"
            "token_expires_at,last_validated_at,last_sync_at,last_synced_at,last_sync_status,"
            "requires_reauth,is_active,updated_at,ig_user_id,ad_account_id,meta_user_id,username,"
            "business_id,ad_account_name,scopes_json,encrypted_access_token,access_token,last_error"
        ),
        filters=filters,
        order="updated_at.asc",
        limit=500,
    )
