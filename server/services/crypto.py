from __future__ import annotations

import base64
import hashlib
import os
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _resolve_secret_material() -> str:
    # Ordem de preferência explícita; fallback evita quebrar ambientes legados.
    for key_name in ("TOKEN_ENCRYPTION_KEY", "META_TOKEN_ENCRYPTION_KEY", "SUPABASE_SERVICE_ROLE_KEY"):
        candidate = _env(key_name)
        if candidate:
            return candidate
    raise RuntimeError("Token encryption key não configurada no ambiente")


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    secret = _resolve_secret_material()
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_secret(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        raise RuntimeError("Valor secreto vazio para criptografia")
    token = _fernet().encrypt(raw.encode("utf-8"))
    return token.decode("utf-8")


def decrypt_secret(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        raise RuntimeError("Valor secreto vazio para descriptografia")
    try:
        out = _fernet().decrypt(raw.encode("utf-8"))
        return out.decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError("Falha ao descriptografar segredo") from exc
