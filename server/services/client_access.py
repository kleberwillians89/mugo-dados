"""Acessos de usuário por empresa, administrados dentro do Mugô Dados.

Reaproveita a autenticação que já existe: Supabase Auth como dono da conta e
`client_memberships` como vínculo com a empresa. Não há segundo sistema de
login, nem tabela de perfil nova — o nome fica no `user_metadata` do próprio
Auth, que é onde o Supabase guarda isso.

Regras que o código garante:

- **Papéis de cliente são uma allowlist**: só `viewer` e `client_admin`. Um
  payload pedindo `agency_admin` ou `platform_admin` é recusado aqui, no
  servidor, independentemente do que a tela ofereça.
- **A empresa vem do contexto autorizado** pela rota, nunca de um `client_id`
  solto do browser.
- **A senha nunca é persistida, logada, devolvida nem guardada em metadata.**
  Ela existe apenas dentro da chamada ao Admin API.
- **Conta é reaproveitada**: o mesmo e-mail pode ter acesso legítimo a mais de
  uma empresa, então nunca se cria um segundo usuário Auth para ele.
- **Remover acesso age na membership**, não na conta: quem também pertence a
  outra empresa continua entrando normalmente.
- Auth e Postgres não compartilham transação. Se a membership falhar depois de
  criar a conta, a conta recém-criada é removida para não ficar órfã; uma
  conta que já existia nunca é apagada.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

import httpx

from .ig_supabase import sb_delete, sb_insert, sb_select

# Papéis que uma tela de usuário de CLIENTE pode conceder.
CLIENT_ROLES = ("viewer", "client_admin")
ROLE_LABELS = {"viewer": "Visualizador", "client_admin": "Administrador do cliente"}
# Papéis globais da equipe Mugô: nunca concedidos por este caminho.
GLOBAL_ROLES = ("agency_admin", "platform_admin", "owner", "admin")
MIN_PASSWORD_LENGTH = 8
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]+$")


class AccessError(RuntimeError):
    """Erro de negócio com código estável para a rota traduzir."""

    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.message = message
        self.status_code = status_code


def _text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _env(name: str) -> str:
    return _text(os.getenv(name))


def normalize_email(value: Any) -> str:
    email = _text(value).lower()
    if not EMAIL_PATTERN.match(email):
        raise AccessError("ACCESS_EMAIL_INVALID", "Informe um e-mail válido.")
    return email


def normalize_client_role(value: Any) -> str:
    """Allowlist no servidor: escalonar papel por payload é recusado."""
    role = _text(value).lower()
    if role in GLOBAL_ROLES:
        raise AccessError(
            "ACCESS_ROLE_NOT_ALLOWED",
            "Perfis da equipe Mugô não são concedidos nesta tela.",
            status_code=403,
        )
    if role not in CLIENT_ROLES:
        raise AccessError("ACCESS_ROLE_INVALID", "Escolha um perfil válido para o acesso.")
    return role


def validate_password(password: Any, confirmation: Any) -> str:
    """Valida sem registrar: a senha não aparece em erro, log ou retorno."""
    value = str(password or "")
    confirm = str(confirmation or "")
    if len(value) < MIN_PASSWORD_LENGTH:
        raise AccessError(
            "ACCESS_PASSWORD_TOO_SHORT",
            f"A senha precisa ter pelo menos {MIN_PASSWORD_LENGTH} caracteres.",
        )
    if value != confirm:
        raise AccessError("ACCESS_PASSWORD_MISMATCH", "As senhas não coincidem.")
    return value


def _admin_headers() -> Dict[str, str]:
    service_key = _env("SUPABASE_SERVICE_ROLE_KEY")
    if not service_key or not _env("SUPABASE_URL"):
        raise AccessError(
            "ACCESS_ADMIN_API_NOT_CONFIGURED",
            "A administração de acessos não está configurada no backend.",
            status_code=503,
        )
    return {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
    }


def _auth_base() -> str:
    return f"{_env('SUPABASE_URL').rstrip('/')}/auth/v1/admin"


async def _admin_request(
    method: str, path: str, *, json: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None,
) -> Any:
    """Chamada ao Admin API. O corpo nunca é logado: pode conter senha."""
    headers = _admin_headers()
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.request(
                method, f"{_auth_base()}{path}", headers=headers, json=json, params=params,
            )
    except httpx.HTTPError as exc:
        print(f"[access][admin_api] path={path} status=network_error error_type={exc.__class__.__name__}")
        raise AccessError(
            "ACCESS_ADMIN_API_UNAVAILABLE",
            "Não foi possível falar com o serviço de contas agora.",
            status_code=502,
        ) from None
    if response.status_code >= 400:
        print(f"[access][admin_api] path={path} status={response.status_code}")
        if response.status_code in {401, 403}:
            raise AccessError(
                "ACCESS_ADMIN_API_FORBIDDEN",
                "O backend não tem permissão para administrar contas.",
                status_code=503,
            )
        raise AccessError(
            "ACCESS_ADMIN_API_REJECTED",
            "O serviço de contas recusou a operação.",
            status_code=502,
        )
    try:
        return response.json()
    except ValueError:
        return {}


def _auth_user_view(user: Dict[str, Any]) -> Dict[str, Any]:
    """Só o que a tela precisa. Nenhum token, identidade ou metadado cru."""
    metadata = user.get("user_metadata") if isinstance(user.get("user_metadata"), dict) else {}
    return {
        "user_id": _text(user.get("id")),
        "email": _text(user.get("email")).lower(),
        "name": _text(metadata.get("full_name")) or _text(metadata.get("name")) or None,
        "email_confirmed": bool(user.get("email_confirmed_at") or user.get("confirmed_at")),
        "last_sign_in_at": user.get("last_sign_in_at"),
    }


async def find_auth_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    payload = await _admin_request("GET", "/users", params={"page": 1, "per_page": 200, "filter": email})
    users = payload.get("users") if isinstance(payload, dict) else payload
    for user in users if isinstance(users, list) else []:
        if isinstance(user, dict) and _text(user.get("email")).lower() == email:
            return user
    return None


async def _create_auth_user(*, email: str, password: str, name: str) -> Dict[str, Any]:
    # email_confirm: o acesso é criado pela equipe com senha definida, então
    # não há e-mail de confirmação a aguardar. A senha não vai em metadata.
    created = await _admin_request("POST", "/users", json={
        "email": email,
        "password": password,
        "email_confirm": True,
        "user_metadata": {"full_name": name} if name else {},
    })
    if not isinstance(created, dict) or not _text(created.get("id")):
        raise AccessError(
            "ACCESS_USER_CREATE_FAILED", "Não foi possível criar a conta agora.", status_code=502,
        )
    return created


async def _delete_auth_user(user_id: str) -> None:
    try:
        await _admin_request("DELETE", f"/users/{user_id}")
    except AccessError as exc:
        # Compensação falhou: registra para alguém poder agir, sem segredo.
        print(f"[access][compensation] user_id={user_id} status=failed code={exc.code}")


async def _membership(client_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    rows = await sb_select(
        "client_memberships", select="id,user_id,client_id,role,created_at",
        filters={"client_id": f"eq.{client_id}", "user_id": f"eq.{user_id}"}, limit=1,
    )
    row = rows[0] if rows else None
    return row if row and _text(row.get("client_id")) == client_id else None


async def list_client_access(client_id: str) -> Dict[str, Any]:
    """Acessos da empresa. Só membros desta empresa, com dados sanitizados."""
    cid = _text(client_id)
    memberships = await sb_select(
        "client_memberships", select="id,user_id,client_id,role,created_at",
        filters={"client_id": f"eq.{cid}"}, order="created_at.asc", limit=500,
    )
    rows = [row for row in memberships if _text(row.get("client_id")) == cid]
    users: Dict[str, Dict[str, Any]] = {}
    try:
        payload = await _admin_request("GET", "/users", params={"page": 1, "per_page": 500})
        listed = payload.get("users") if isinstance(payload, dict) else payload
        for user in listed if isinstance(listed, list) else []:
            if isinstance(user, dict) and _text(user.get("id")):
                users[_text(user.get("id"))] = _auth_user_view(user)
    except AccessError as exc:
        # Sem o Admin API, a lista ainda mostra papel e vínculo.
        print(f"[access][list] client_id={cid} status=auth_unavailable code={exc.code}")

    items: List[Dict[str, Any]] = []
    for row in rows:
        user_id = _text(row.get("user_id"))
        role = _text(row.get("role")).lower()
        detail = users.get(user_id, {})
        items.append({
            "membership_id": _text(row.get("id")),
            "user_id": user_id,
            "email": detail.get("email"),
            "name": detail.get("name"),
            "role": role,
            "role_label": ROLE_LABELS.get(role, role),
            # Papel global aparece como tal: não é acesso de cliente.
            "is_global_role": role in GLOBAL_ROLES,
            "email_confirmed": detail.get("email_confirmed"),
            "last_sign_in_at": detail.get("last_sign_in_at"),
            "created_at": row.get("created_at"),
        })
    return {"ok": True, "client_id": cid, "items": items}


async def create_client_access(
    *, client_id: str, actor_user_id: str, name: Any, email: Any, password: Any, password_confirmation: Any, role: Any,
) -> Dict[str, Any]:
    """Cria (ou reaproveita) a conta e dá acesso à empresa autorizada."""
    cid = _text(client_id)
    if not cid:
        raise AccessError("ACCESS_CLIENT_REQUIRED", "Empresa não identificada.")
    safe_email = normalize_email(email)
    safe_role = normalize_client_role(role)
    safe_name = _text(name)[:120]
    secret = validate_password(password, password_confirmation)

    existing = await find_auth_user_by_email(safe_email)
    created_now = False
    if existing:
        user_id = _text(existing.get("id"))
        if await _membership(cid, user_id):
            raise AccessError(
                "ACCESS_ALREADY_EXISTS",
                "Este e-mail já tem acesso a esta empresa.",
                status_code=409,
            )
        if await _holds_global_role(user_id):
            raise AccessError(
                "ACCESS_ROLE_NOT_ALLOWED",
                "Contas da equipe Mugô não são administradas nesta tela.",
                status_code=403,
            )
    else:
        created = await _create_auth_user(email=safe_email, password=secret, name=safe_name)
        user_id = _text(created.get("id"))
        created_now = True

    try:
        await sb_insert(
            "client_memberships",
            {"user_id": user_id, "client_id": cid, "role": safe_role},
            returning="minimal",
        )
    except Exception as exc:
        print(
            f"[access][create] client_id={cid} actor={actor_user_id} stage=membership "
            f"status=error error_type={exc.__class__.__name__} created_now={str(created_now).lower()}"
        )
        if created_now:
            # Conta acabou de nascer e ficou sem vínculo: não deixar órfã.
            await _delete_auth_user(user_id)
        raise AccessError(
            "ACCESS_MEMBERSHIP_FAILED",
            "A conta não pôde ser vinculada à empresa. Tente novamente.",
            status_code=502,
        ) from None

    if not created_now:
        # Conta reaproveitada: o acesso precisa ser utilizável agora, com a
        # senha que o administrador acabou de definir e sem e-mail pendente.
        # Só depois do vínculo — um vínculo que falhasse não pode deixar a
        # senha de alguém trocada. O nome existente não é sobrescrito.
        await _admin_request(
            "PUT", f"/users/{user_id}", json={"password": secret, "email_confirm": True},
        )

    print(
        f"[access][create] client_id={cid} actor={actor_user_id} role={safe_role} "
        f"reused_account={str(not created_now).lower()} status=ok"
    )
    # Resposta sanitizada: nunca a senha.
    return {
        "ok": True,
        "client_id": cid,
        "access": {
            "user_id": user_id, "email": safe_email, "name": safe_name or None,
            "role": safe_role, "role_label": ROLE_LABELS[safe_role],
            "account_created": created_now,
            # A senha informada vale para os dois caminhos; a interface
            # precisa saber para instruir a pessoa corretamente.
            "password_applied": True,
        },
    }


async def _holds_global_role(user_id: str) -> bool:
    """A conta pertence à equipe Mugô, em qualquer empresa?

    `reset_client_access_password` já olhava o papel na empresa do contexto.
    Aqui a pergunta é mais ampla de propósito: ao reaproveitar uma conta que
    já existe, um client_admin não pode definir a senha de alguém que é
    agency_admin ou platform_admin em OUTRO lugar — isso seria tomar a conta.
    """
    uid = _text(user_id)
    if not uid:
        return False
    from .platform_admin import is_platform_admin

    if await is_platform_admin(uid):
        return True
    rows = await sb_select(
        "client_memberships", select="user_id,role",
        filters={"user_id": f"eq.{uid}"}, limit=200,
    )
    return any(
        _text(row.get("role")).lower() in GLOBAL_ROLES
        for row in rows
        if _text(row.get("user_id")) == uid
    )


async def _require_membership(client_id: str, user_id: str) -> Dict[str, Any]:
    membership = await _membership(_text(client_id), _text(user_id))
    if not membership:
        raise AccessError(
            "ACCESS_NOT_FOUND", "Este usuário não tem acesso a esta empresa.", status_code=404,
        )
    return membership


async def reset_client_access_password(
    *, client_id: str, actor_user_id: str, user_id: str, password: Any, password_confirmation: Any,
) -> Dict[str, Any]:
    """Define uma senha NOVA. A antiga nunca é recuperada nem exibida."""
    membership = await _require_membership(client_id, user_id)
    if _text(membership.get("role")).lower() in GLOBAL_ROLES:
        raise AccessError(
            "ACCESS_ROLE_NOT_ALLOWED",
            "Contas da equipe Mugô não são administradas nesta tela.",
            status_code=403,
        )
    secret = validate_password(password, password_confirmation)
    await _admin_request("PUT", f"/users/{_text(user_id)}", json={"password": secret})
    print(f"[access][reset_password] client_id={_text(client_id)} actor={actor_user_id} status=ok")
    return {"ok": True, "client_id": _text(client_id), "user_id": _text(user_id)}


async def remove_client_access(
    *, client_id: str, actor_user_id: str, user_id: str,
) -> Dict[str, Any]:
    """Remove o vínculo com ESTA empresa. A conta e os outros acessos ficam."""
    cid = _text(client_id)
    membership = await _require_membership(cid, user_id)
    if _text(membership.get("role")).lower() in GLOBAL_ROLES:
        raise AccessError(
            "ACCESS_ROLE_NOT_ALLOWED",
            "Contas da equipe Mugô não são administradas nesta tela.",
            status_code=403,
        )
    await sb_delete(
        "client_memberships",
        filters={"client_id": f"eq.{cid}", "user_id": f"eq.{_text(user_id)}"},
    )
    remaining = await sb_select(
        "client_memberships", select="client_id",
        filters={"user_id": f"eq.{_text(user_id)}"}, limit=50,
    )
    print(
        f"[access][remove] client_id={cid} actor={actor_user_id} status=ok "
        f"remaining_memberships={len(remaining)}"
    )
    return {
        "ok": True, "client_id": cid, "user_id": _text(user_id),
        # A conta segue existindo; só o acesso a esta empresa saiu.
        "account_preserved": True,
        "remaining_memberships": len(remaining),
    }
