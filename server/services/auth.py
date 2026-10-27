# server/services/auth.py
import os
from typing import Optional, Dict, Any
import httpx
import json
import base64
from .request_performance import measured, transport_started, transport_done
from datetime import datetime, timezone
import hashlib
import time

# Token já validado no Supabase Auth: reaproveitado por até 60 s (nunca além
# do vencimento do próprio token). Evita uma ida ao Supabase a cada chamada da
# tela (ex.: status da atualização a cada poucos segundos). Só resultados
# válidos entram; a chave é o hash do token, nunca o token.
_TOKEN_CACHE_SECONDS = 60
_TOKEN_CACHE_MAX = 2000
_token_cache: Dict[str, tuple] = {}


def _token_cache_key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _cached_user_id(token: str) -> Optional[str]:
    hit = _token_cache.get(_token_cache_key(token))
    if not hit:
        return None
    uid, expires_at = hit
    if time.time() >= expires_at:
        _token_cache.pop(_token_cache_key(token), None)
        return None
    return uid


def _remember_user_id(token: str, uid: str) -> None:
    claims = _decode_jwt_claims_no_verify(token) or {}
    try:
        token_exp = float(claims.get("exp") or 0)
    except (TypeError, ValueError):
        token_exp = 0
    expires_at = time.time() + _TOKEN_CACHE_SECONDS
    if token_exp:
        expires_at = min(expires_at, token_exp)
    if expires_at <= time.time():
        return
    if len(_token_cache) >= _TOKEN_CACHE_MAX:
        now = time.time()
        for key in [k for k, (_, exp) in _token_cache.items() if exp <= now] or list(_token_cache)[: _TOKEN_CACHE_MAX // 4]:
            _token_cache.pop(key, None)
    _token_cache[_token_cache_key(token)] = (uid, expires_at)


def forget_token(authorization: Optional[str]) -> None:
    token = _bearer_token(authorization)
    if token:
        _token_cache.pop(_token_cache_key(token), None)

def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()

def _bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


def _decode_jwt_claims_no_verify(token: str) -> Optional[Dict[str, Any]]:
    """
    Fallback local: decodifica claims sem validar assinatura.
    Usado apenas quando auth/v1/user falha.
    """
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return None
        payload = parts[1]
        pad = "=" * ((4 - (len(payload) % 4)) % 4)
        raw = base64.urlsafe_b64decode((payload + pad).encode("utf-8"))
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _validate_claims_for_local(claims: Dict[str, Any], supabase_url: str) -> Optional[str]:
    sub = str(claims.get("sub") or "").strip()
    aud = str(claims.get("aud") or "").strip()
    iss = str(claims.get("iss") or "").strip()
    exp = int(claims.get("exp") or 0)

    if not sub:
        return None
    if aud and aud != "authenticated":
        return None
    if iss and not iss.startswith(supabase_url.rstrip("/") + "/auth/v1"):
        return None
    now_ts = int(datetime.now(timezone.utc).timestamp())
    if exp and exp < now_ts:
        return None
    return sub

async def get_user_from_bearer(authorization: Optional[str]) -> Optional[Dict[str, str]]:
    """
    Valida o token chamando Supabase Auth e devolve {"id", "email"} do usuário.
    Retorna None quando o token é ausente/ inválido (sem fallback de dev).
    """
    token = _bearer_token(authorization)
    if not token:
        return None

    supabase_url = _env("SUPABASE_URL").rstrip("/")
    anon_key = _env("SUPABASE_ANON_KEY")
    service_role_key = _env("SUPABASE_SERVICE_ROLE_KEY")

    if not supabase_url.startswith("http"):
        raise RuntimeError("Missing or invalid environment variable: SUPABASE_URL.")
    keys = [k for k in [anon_key, service_role_key] if len(k) >= 20]
    if not keys:
        raise RuntimeError(
            "Missing environment variable: SUPABASE_ANON_KEY or SUPABASE_SERVICE_ROLE_KEY."
        )

    url = f"{supabase_url}/auth/v1/user"
    async with httpx.AsyncClient(timeout=20) as client:
        for key in keys:
            r = await client.get(url, headers={"Authorization": f"Bearer {token}", "apikey": key})
            if r.status_code != 200:
                continue
            data: Dict[str, Any] = r.json()
            uid = (data.get("id") or "").strip()
            if uid:
                return {"id": uid, "email": str(data.get("email") or "").strip()}
    return None


@measured("auth", memo=True)
async def get_user_id_from_bearer(authorization: Optional[str]) -> Optional[str]:
    """
    Valida token chamando Supabase Auth. Retorna user_id (sub) se válido.
    """
    token = _bearer_token(authorization)
    if not token:
        return None
    cached = _cached_user_id(token)
    if cached:
        return cached

    supabase_url = _env("SUPABASE_URL").rstrip("/")
    anon_key = _env("SUPABASE_ANON_KEY")
    service_role_key = _env("SUPABASE_SERVICE_ROLE_KEY")

    if not supabase_url.startswith("http"):
        raise RuntimeError("Missing or invalid environment variable: SUPABASE_URL.")
    keys = [k for k in [anon_key, service_role_key] if len(k) >= 20]
    if not keys:
        raise RuntimeError(
            "Missing environment variable: SUPABASE_ANON_KEY or SUPABASE_SERVICE_ROLE_KEY."
        )

    url = f"{supabase_url}/auth/v1/user"

    async with httpx.AsyncClient(timeout=20) as client:
        for key in keys:
            headers = {
                "Authorization": f"Bearer {token}",
                "apikey": key,
            }
            measurement = transport_started()
            status = "transport_error"
            try:
                r = await client.get(url, headers=headers)
                status = str(r.status_code)
            finally:
                transport_done(measurement, dependency="supabase_auth", operation="user", status=status)
            if r.status_code != 200:
                continue
            data: Dict[str, Any] = r.json()
            uid = (data.get("id") or "").strip()
            if uid:
                _remember_user_id(token, uid)
                return uid

    # Fallback estritamente local e opt-in. Nunca aceitar JWT sem assinatura
    # validada em produção.
    allow_unverified_dev = _env("ALLOW_UNVERIFIED_JWT_DEV").lower() in {
        "1", "true", "yes", "on"
    }
    environment = _env("APP_ENV").lower()
    if allow_unverified_dev and environment not in {"production", "prod"}:
        claims = _decode_jwt_claims_no_verify(token)
        if claims:
            uid = _validate_claims_for_local(claims, supabase_url=supabase_url)
            if uid:
                return uid

    return None
