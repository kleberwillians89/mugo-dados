"""Um app Shopify por loja (distribuição personalizada).

A Shopify só aceita o link de instalação de um app de distribuição personalizada na loja para a qual ele foi gerado.
Por isso cada cliente novo tem o próprio app no Dev Dashboard. Aqui ficam o Client ID e o segredo dele, por loja
(myshopify.com), com o segredo criptografado. Sem cadastro para a loja, vale o app padrão das variáveis de ambiente
(SHOPIFY_CLIENT_ID/SECRET e SHOPIFY_APP_SECRET), que é o da Roove — nada muda para quem já está conectado.

O segredo nunca sai daqui: a tela recebe só se está cadastrado e o fim do Client ID.
"""
from __future__ import annotations

import re
import time
from typing import Any, Dict, Optional

from .ig_supabase import sb_select, sb_upsert

TABLE = "shopify_app_credentials"
SHOP_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]\.myshopify\.com$")
_CACHE: Dict[str, tuple[float, Optional[Dict[str, str]]]] = {}
TTL = 60.0


class CredentialError(ValueError):
    pass


def _shop(value: Any) -> str:
    shop = str(value or "").strip().lower().removeprefix("https://").removeprefix("http://").split("/")[0]
    if shop and "." not in shop:
        shop = f"{shop}.myshopify.com"
    if not SHOP_RE.match(shop):
        raise CredentialError("Informe o domínio da loja no formato loja.myshopify.com.")
    return shop


def clear_cache() -> None:
    _CACHE.clear()


async def for_shop(shop_domain: str) -> Optional[Dict[str, str]]:
    """{client_id, client_secret} do app desta loja, ou None (usa o app padrão). Erro de leitura = None + log."""
    try:
        shop = _shop(shop_domain)
    except CredentialError:
        return None
    hit = _CACHE.get(shop)
    if hit and time.monotonic() - hit[0] < TTL:
        return hit[1]
    try:
        rows = await sb_select(TABLE, select="client_id,app_client_id,client_secret_encrypted",
                               filters={"shop_domain": f"eq.{shop}"}, limit=1)
    except Exception as exc:  # noqa: BLE001 — sem a migração 000166: segue o app padrão
        print(f"[shopify_app] lookup_unavailable shop={shop} {type(exc).__name__}")
        return None
    found: Optional[Dict[str, str]] = None
    if rows:
        from .crypto import decrypt_secret
        try:
            found = {"client_id": rows[0]["app_client_id"], "client_secret": decrypt_secret(rows[0]["client_secret_encrypted"]),
                     "tenant": str(rows[0].get("client_id") or "")}
        except Exception as exc:  # noqa: BLE001
            print(f"[shopify_app] decrypt_failed shop={shop} {type(exc).__name__}")
            found = None
    _CACHE[shop] = (time.monotonic(), found)
    return found


async def save(client_id: str, *, shop_domain: Any, app_client_id: Any, client_secret: Any, actor_id: str) -> Dict[str, Any]:
    from .crypto import encrypt_secret
    shop = _shop(shop_domain)
    app_id = str(app_client_id or "").strip()
    secret = str(client_secret or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,120}", app_id):
        raise CredentialError("Client ID inválido: copie do Dev Dashboard (Configurações do app).")
    if len(secret) < 16 or len(secret) > 200 or any(c.isspace() for c in secret):
        raise CredentialError("Client Secret inválido: copie do Dev Dashboard (Configurações do app).")
    existing = await sb_select(TABLE, select="client_id", filters={"shop_domain": f"eq.{shop}"}, limit=1)
    if existing and str(existing[0].get("client_id")) != client_id:
        # Uma loja pertence a uma empresa só: não deixa outra empresa trocar o app dela.
        raise CredentialError("Esta loja já está cadastrada em outra empresa.")
    await sb_upsert(TABLE, [{"shop_domain": shop, "client_id": client_id, "app_client_id": app_id,
                             "client_secret_encrypted": encrypt_secret(secret), "updated_by": actor_id}],
                    on_conflict="shop_domain")
    _CACHE.pop(shop, None)
    print(f"[shopify_app] saved client_id={client_id} shop={shop} app=...{app_id[-6:]}")
    return await view(client_id)


async def view(client_id: str) -> Dict[str, Any]:
    """O que a tela pode ver: lojas com app próprio e o fim do Client ID. Nunca o segredo."""
    try:
        rows = await sb_select(TABLE, select="shop_domain,app_client_id,updated_at", filters={"client_id": f"eq.{client_id}"}, limit=20)
    except Exception:  # noqa: BLE001
        rows = []
    return {"apps": [{"shop_domain": r["shop_domain"], "client_id_hint": f"...{str(r['app_client_id'])[-6:]}",
                      "updated_at": r.get("updated_at")} for r in rows]}
