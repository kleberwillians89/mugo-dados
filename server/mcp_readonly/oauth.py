"""OAuth isolado do OAuth dos providers. Tokens opacos; apenas hashes persistidos."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import secrets
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit, parse_qsl

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from services.auth import get_user_from_bearer
from services.ig_supabase import sb_insert, sb_select, sb_update, sb_rpc, mcp_safe_errors
from .tools import dispatch, ToolFailure

router = APIRouter()
SCOPE = "mugo:read"
PUBLIC_ERROR = {"error": "invalid_request", "error_description": "Solicitação de conexão inválida ou indisponível."}
public_rates = OrderedDict()


class LoginRequired(ToolFailure):
    pass


def enabled():
    return os.getenv("MCP_ENABLED", "").lower() in {"true", "1", "yes", "on"}


def settings():
    resource = os.getenv("MCP_PUBLIC_URL", "").rstrip("/")
    frontend = os.getenv("MCP_FRONTEND_URL", "").rstrip("/")
    for value in (resource, frontend):
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ToolFailure("Configuração do conector indisponível.")
    if urlsplit(resource).path != "/mcp" or urlsplit(frontend).path not in {"", "/"}:
        raise ToolFailure("Configuração do conector indisponível.")
    return resource, frontend, resource[:-4]


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def challenge(verifier):
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def identifier(value):
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise ToolFailure("Identificador de conexão inválido.") from None


def valid_at(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")) > datetime.now(timezone.utc)
    except (ValueError, TypeError):
        return False


async def verified_user(request):
    async with asyncio.timeout(8):
        user = await get_user_from_bearer(request.headers.get("authorization"))
    if not user:
        raise LoginRequired("Faça login para gerenciar o conector.")
    return identifier(user["id"])


def allowed_redirects():
    return {value.strip() for value in os.getenv("MCP_ALLOWED_REDIRECT_URIS", "").split(",") if value.strip()}


async def client_row(value):
    cid = identifier(value)
    rows = await sb_select("mcp_oauth_clients", select="id,client_name,redirect_uris,created_at", filters={"id": f"eq.{cid}"}, limit=1)
    return next((row for row in rows if row.get("id") == cid), None)


def requested_resource(value, resource):
    """RFC 8707: ausente vale o recurso padrão; barra final é tolerada."""
    if value is None or value == "":
        return resource
    return value.rstrip("/") if isinstance(value, str) else value


async def authorization_parameters(data):
    resource, _, _ = settings()
    data = {**data, "resource": requested_resource(data.get("resource"), resource)}
    row = await client_row(data.get("client_id"))
    redirect = data.get("redirect_uri")
    if (not row or redirect not in allowed_redirects() or redirect not in row.get("redirect_uris", [])
            or data.get("response_type") != "code" or data.get("code_challenge_method") != "S256"
            or not re.fullmatch(r"[A-Za-z0-9_-]{43}", str(data.get("code_challenge") or ""))
            or not isinstance(data.get("state"), str) or not 1 <= len(data["state"]) <= 512
            or data.get("resource") != resource or data.get("scope", SCOPE) != SCOPE):
        raise ToolFailure("Solicitação de autorização inválida.")
    return {key: data[key] for key in ("client_id", "redirect_uri", "response_type", "code_challenge", "code_challenge_method", "state", "resource")}


def callback(uri, **params):
    return uri + ("&" if urlsplit(uri).query else "?") + urlencode(params)


async def body(request):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 16384:
            raise ToolFailure("Solicitação muito grande.")
    if "application/json" in request.headers.get("content-type", ""):
        result = json.loads(raw)
    elif "application/x-www-form-urlencoded" in request.headers.get("content-type", ""):
        pairs = parse_qsl(raw.decode("utf-8"), max_num_fields=16, keep_blank_values=True)
        result = dict(pairs)
        if len(pairs) != len(result):
            raise ToolFailure("Parâmetros duplicados.")
    else:
        raise ToolFailure("Formato de solicitação inválido.")
    if not isinstance(result, dict):
        raise ToolFailure("Solicitação inválida.")
    return result


# Guardas consistentes, sem eco de erros SQL, dados pessoais ou parâmetros OAuth.
def endpoint(path, *, method="GET", public=False):
    def decorate(fn):
        async def safe(request: Request):
            if not enabled():
                return JSONResponse({"detail": "Recurso indisponível."}, 404)
            privacy_token = mcp_safe_errors.set(True)
            try:
                settings()
                if public:
                    minute = int(time.monotonic() // 60)
                    count = public_rates.get(minute, 0)
                    public_rates.clear()
                    public_rates[minute] = count + 1
                    if count >= 120:
                        return JSONResponse({"error": "temporarily_unavailable"}, 429)
                async with asyncio.timeout(9):
                    result = await fn(request)
                result.headers["Cache-Control"] = "no-store"
                result.headers["Pragma"] = "no-cache"
                return result
            except LoginRequired:
                return JSONResponse({"detail": "Autenticação obrigatória."}, 401, headers={"Cache-Control": "no-store"})
            except (ToolFailure, ValueError, UnicodeError):
                return JSONResponse(PUBLIC_ERROR, 400, headers={"Cache-Control": "no-store"})
            except Exception:
                return JSONResponse({"error": "temporarily_unavailable", "error_description": "Conector indisponível. Tente novamente mais tarde."}, 503, headers={"Cache-Control": "no-store"})
            finally:
                mcp_safe_errors.reset(privacy_token)
        router.add_api_route(path, safe, methods=[method])
        return fn
    return decorate


@endpoint("/.well-known/oauth-protected-resource", public=True)
async def protected_resource(request):
    resource, _, issuer = settings()
    return JSONResponse({"resource": resource, "authorization_servers": [issuer], "scopes_supported": [SCOPE], "bearer_methods_supported": ["header"]})


@endpoint("/.well-known/oauth-authorization-server", public=True)
async def authorization_server(request):
    _, _, issuer = settings()
    return JSONResponse({"issuer": issuer, "authorization_endpoint": issuer + "/oauth/authorize", "token_endpoint": issuer + "/oauth/token",
        "registration_endpoint": issuer + "/oauth/register", "revocation_endpoint": issuer + "/oauth/revoke",
        "response_types_supported": ["code"], "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"], "token_endpoint_auth_methods_supported": ["none"], "scopes_supported": [SCOPE]})


def grant_types_ok(value):
    """RFC 7591: ordem livre; authorization_code obrigatório, refresh_token opcional."""
    if value is None:
        return True
    return (isinstance(value, list) and "authorization_code" in value
            and set(value) <= {"authorization_code", "refresh_token"})


@endpoint("/oauth/register", method="POST", public=True)
async def register(request):
    data = await body(request)
    redirects = data.get("redirect_uris")
    if (not isinstance(redirects, list) or not 1 <= len(redirects) <= 5
            or any(not isinstance(uri, str) or uri not in allowed_redirects() for uri in redirects)
            or data.get("token_endpoint_auth_method", "none") != "none"
            or not grant_types_ok(data.get("grant_types"))
            or not isinstance(data.get("response_types", ["code"]), list)
            or set(data.get("response_types", ["code"])) != {"code"}):
        raise ToolFailure("Registro não autorizado.")
    cid = str(uuid.uuid4())
    # Nome é metadado visível apenas na conta que autorizar; nunca é logado.
    name = data.get("client_name", "Claude")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
        raise ToolFailure("Nome de aplicativo inválido.")
    await sb_insert("mcp_oauth_clients", {"id": cid, "client_name": name.strip(), "redirect_uris": redirects}, returning="minimal")
    return JSONResponse({"client_id": cid, "client_id_issued_at": int(time.time()), "client_name": name.strip(), "redirect_uris": redirects,
        "token_endpoint_auth_method": "none", "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"]}, 201)


@endpoint("/oauth/authorize", public=True)
async def authorize(request):
    if len(request.query_params.multi_items()) != len(request.query_params):
        raise ToolFailure("Parâmetros duplicados.")
    params = await authorization_parameters(dict(request.query_params))
    _, frontend, _ = settings()
    return RedirectResponse(frontend + "/conectar-claude/autorizar?" + urlencode(params), 303)


@endpoint("/api/mcp/consent", method="POST")
async def consent(request):
    uid = await verified_user(request)
    data = await body(request)
    params = await authorization_parameters(data)
    if data.get("approve") is not True:
        return JSONResponse({"redirect_url": callback(params["redirect_uri"], error="access_denied", state=params["state"])})
    # Revalida as empresas exibidas; nenhum escopo de tenant é obtido do browser.
    await dispatch(uid, "list_companies")
    code = secrets.token_urlsafe(48)
    await sb_insert("mcp_oauth_codes", {"code_hash": digest(code), "user_id": uid, "oauth_client_id": params["client_id"],
        "redirect_uri": params["redirect_uri"], "resource": params["resource"], "challenge": params["code_challenge"]}, returning="minimal")
    return JSONResponse({"redirect_url": callback(params["redirect_uri"], code=code, state=params["state"])})


@endpoint("/oauth/token", method="POST", public=True)
async def token(request):
    data = await body(request)
    resource, _, _ = settings()
    cid = identifier(data.get("client_id"))
    if requested_resource(data.get("resource"), resource) != resource or not await client_row(cid):
        raise ToolFailure("Cliente ou recurso inválido.")
    access, refresh = secrets.token_urlsafe(48), secrets.token_urlsafe(48)
    if data.get("grant_type") == "authorization_code":
        verifier = data.get("code_verifier", "")
        code = data.get("code", "")
        if (not isinstance(verifier, str) or not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier)
                or not isinstance(code, str) or not 20 <= len(code) <= 256 or data.get("redirect_uri") not in allowed_redirects()):
            raise ToolFailure("Código ou PKCE inválido.")
        ok = await sb_rpc("mcp_exchange_code", {"p_code_hash": digest(code), "p_client_id": cid, "p_redirect_uri": data["redirect_uri"],
            "p_resource": resource, "p_challenge": challenge(verifier), "p_access_hash": digest(access), "p_refresh_hash": digest(refresh)})
    elif data.get("grant_type") == "refresh_token":
        old_refresh = data.get("refresh_token")
        if not isinstance(old_refresh, str) or not 20 <= len(old_refresh) <= 256:
            raise ToolFailure("Refresh inválido.")
        ok = await sb_rpc("mcp_rotate_refresh", {"p_refresh_hash": digest(old_refresh), "p_client_id": cid,
            "p_resource": resource, "p_access_hash": digest(access), "p_new_refresh_hash": digest(refresh)})
    else:
        return JSONResponse({"error": "unsupported_grant_type"}, 400)
    if ok is not True:
        return JSONResponse({"error": "invalid_grant"}, 400)
    return JSONResponse({"access_token": access, "token_type": "Bearer", "expires_in": 3600, "refresh_token": refresh, "scope": SCOPE})


@endpoint("/oauth/revoke", method="POST", public=True)
async def revoke(request):
    data = await body(request)
    value = data.get("token")
    if not isinstance(value, str) or not 20 <= len(value) <= 256:
        return JSONResponse({})
    await sb_rpc("mcp_revoke_family", {"p_token_hash": digest(value), "p_client_id": identifier(data.get("client_id"))})
    return JSONResponse({})


async def authenticate(authorization):
    resource, _, _ = settings()
    parts = (authorization or "").split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not 20 <= len(parts[1]) <= 256:
        return None
    rows = await sb_select("mcp_oauth_tokens", select="id,user_id,resource,revoked_at,access_expires_at",
        filters={"access_hash": f"eq.{digest(parts[1])}"}, limit=1)
    row = rows[0] if rows else None
    if not row or row.get("resource") != resource or row.get("revoked_at") or not valid_at(row.get("access_expires_at")):
        return None
    await sb_update("mcp_oauth_tokens", filters={"id": f"eq.{identifier(row['id'])}"},
                    patch={"last_used_at": datetime.now(timezone.utc).isoformat()}, returning="minimal")
    return identifier(row["user_id"]), digest(parts[1])


@endpoint("/api/mcp/connections")
async def connections(request):
    uid = await verified_user(request)
    rows = await sb_select("mcp_oauth_tokens", select="id,oauth_client_id,created_at,last_used_at,refresh_expires_at,revoked_at,rotated_at",
        filters={"user_id": f"eq.{uid}", "revoked_at": "is.null", "rotated_at": "is.null"}, order="created_at.desc", limit=100)
    output = []
    for row in rows:
        if row.get("revoked_at") or row.get("rotated_at") or not valid_at(row.get("refresh_expires_at")):
            continue
        client = await client_row(row["oauth_client_id"])
        output.append({"id": row["id"], "name": (client or {}).get("client_name", "Aplicativo"),
            "created_at": row.get("created_at"), "last_used_at": row.get("last_used_at")})
    companies = await dispatch(uid, "list_companies")
    resource, _, _ = settings()
    return JSONResponse({"url": resource, "connections": output, "companies": companies["companies"]})


@endpoint("/api/mcp/connections/revoke", method="POST")
async def disconnect(request):
    uid = await verified_user(request)
    data = await body(request)
    tid = identifier(data.get("id"))
    rows = await sb_select("mcp_oauth_tokens", select="refresh_hash,oauth_client_id", filters={"id": f"eq.{tid}", "user_id": f"eq.{uid}"}, limit=1)
    if rows:
        await sb_rpc("mcp_revoke_family", {"p_token_hash": rows[0]["refresh_hash"], "p_client_id": rows[0]["oauth_client_id"]})
    return JSONResponse({"ok": True})


@endpoint("/api/mcp/authorization")
async def authorization_preview(request):
    uid = await verified_user(request)
    params = await authorization_parameters(dict(request.query_params))
    client = await client_row(params["client_id"])
    companies = await dispatch(uid, "list_companies")
    resource, _, _ = settings()
    return JSONResponse({"url": resource, "application": client["client_name"], "companies": companies["companies"], "connections": []})
