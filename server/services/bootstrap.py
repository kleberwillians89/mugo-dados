from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import List, Dict, Optional
import httpx

from .crypto import encrypt_secret
from .ig_supabase import sb_insert, sb_select, sb_update


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_missing_token(value: str | None) -> bool:
    token = (value or "").strip()
    if not token:
        return True
    return token.lower() in {"null", "none", "undefined", "nil"}


def _collect(prefix: str) -> Optional[Dict[str, str]]:
    client_id = _env(f"{prefix}_CLIENT_ID")
    access_token = _env(f"{prefix}_ACCESS_TOKEN") or _env("META_ACCESS_TOKEN")
    ig_user_id = _env(f"{prefix}_IG_USER_ID") or _env("META_IG_USER_ID")
    expires_at = _env(f"{prefix}_EXPIRES_AT")
    ad_account_id = _env(f"{prefix}_META_AD_ACCOUNT_ID") or _env(f"{prefix}_AD_ACCOUNT_ID")

    if not client_id or _is_missing_token(access_token):
        return None
    return {
        "client_id": client_id,
        "access_token": access_token,
        "ig_user_id": ig_user_id,
        "expires_at": expires_at,
        "ad_account_id": ad_account_id,
    }


async def bootstrap_meta_from_env() -> List[str]:
    """
    Semeia conexões Meta no startup para ambientes locais.
    Não valida token online aqui: só persiste para evitar reconnect manual.
    """
    raw = _env("META_BOOTSTRAP_PREFIXES")
    prefixes = [p.strip().upper() for p in raw.split(",") if p.strip()] if raw else ["MUGO"]
    applied: List[str] = []

    for p in prefixes:
        item = _collect(p)
        if not item:
            continue

        cid = item["client_id"]
        token = item["access_token"]
        ig_user_id = item.get("ig_user_id") or ""
        expires_at = item.get("expires_at") or None
        ad_account_id = (item.get("ad_account_id") or "").strip()
        normalized_ad_account_id = ad_account_id if ad_account_id.startswith("act_") else f"act_{ad_account_id}" if ad_account_id else ""
        if _is_missing_token(token):
            print(f"[bootstrap_meta] skip prefix={p} reason=missing_access_token")
            continue

        # legado
        patch = {"ig_access_token": token}
        if ig_user_id:
            patch["ig_user_id"] = ig_user_id
        try:
            await sb_update(
                "clients",
                filters={"id": f"eq.{cid}"},
                patch=patch,
                returning="minimal",
            )
        except httpx.HTTPStatusError as exc:
            # Alguns bancos legados têm constraint UNIQUE em ig_user_id.
            # Nesse caso, mantém ao menos o token no cliente alvo.
            if exc.response is None or exc.response.status_code != 409:
                raise
            await sb_update(
                "clients",
                filters={"id": f"eq.{cid}"},
                patch={"ig_access_token": token},
                returning="minimal",
            )

        # novo modelo (se tabela existir)
        ig_id = (ig_user_id or "").strip()
        row = {
            "client_id": cid,
            "platform": "instagram",
            "connection_type": "organic",
            "meta_user_id": "",
            "ig_user_id": ig_id,
            "username": "",
            "business_id": "",
            "ad_account_id": "",
            "ad_account_name": "",
            "scopes_json": [],
            "encrypted_access_token": encrypt_secret(token),
            "access_token": None,
            "expires_at": expires_at,
            "token_expires_at": expires_at,
            "token_last_refreshed_at": None,
            "last_validated_at": None,
            "last_sync_status": "never",
            "requires_reauth": False,
            "is_active": True,
            "status": "active",
            "last_error": None,
            "connected_at": _iso_now(),
        }
        try:
            existing = await sb_select(
                "meta_connections",
                filters={
                    "client_id": f"eq.{cid}",
                    "platform": "eq.instagram",
                    "connection_type": "eq.organic",
                    "ig_user_id": f"eq.{ig_id}",
                    "ad_account_id": "eq.",
                },
                limit=1,
            )
            if existing:
                await sb_update(
                    "meta_connections",
                    filters={"id": f"eq.{existing[0].get('id')}"},
                    patch=row,
                    returning="minimal",
                )
            else:
                await sb_insert("meta_connections", row, returning="minimal")
        except httpx.HTTPStatusError as exc:
            if exc.response is None or exc.response.status_code != 404:
                raise

        if normalized_ad_account_id:
            paid_row = {
                "client_id": cid,
                "platform": "meta_ads",
                "connection_type": "paid",
                "meta_user_id": "",
                "ig_user_id": "",
                "username": "",
                "business_id": "",
                "ad_account_id": normalized_ad_account_id,
                "ad_account_name": "",
                "scopes_json": [],
                "encrypted_access_token": encrypt_secret(token),
                "access_token": None,
                "expires_at": expires_at,
                "token_expires_at": expires_at,
                "token_last_refreshed_at": None,
                "last_validated_at": None,
                "last_sync_status": "never",
                "requires_reauth": False,
                "is_active": True,
                "status": "active",
                "last_error": None,
                "connected_at": _iso_now(),
            }
            try:
                existing_paid = await sb_select(
                    "meta_connections",
                    filters={
                        "client_id": f"eq.{cid}",
                        "platform": "eq.meta_ads",
                        "connection_type": "eq.paid",
                        "ad_account_id": f"eq.{normalized_ad_account_id}",
                    },
                    limit=1,
                )
                if existing_paid:
                    await sb_update(
                        "meta_connections",
                        filters={"id": f"eq.{existing_paid[0].get('id')}"},
                        patch=paid_row,
                        returning="minimal",
                    )
                else:
                    await sb_insert("meta_connections", paid_row, returning="minimal")
            except httpx.HTTPStatusError as exc:
                if exc.response is None or exc.response.status_code != 404:
                    raise

        applied.append(p)

    return applied
