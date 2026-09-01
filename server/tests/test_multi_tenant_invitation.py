"""Bloco 2.1 — usuário já existente + multi-tenant no fluxo de convite.

Comportamento desejado:
  - usuário NOVO continua sendo vinculado pelo trigger na 1ª confirmação;
  - usuário EXISTENTE aceita explicitamente UMA invitation específica
    (`POST /api/invitations/{id}/accept`) e ganha membership adicional,
    mantendo as memberships anteriores;
  - o tenant/role vêm SEMPRE da invitation (nunca de payload do frontend);
  - a membership só é criada se o e-mail da invitation bate com o do
    usuário autenticado, e a invitation está utilizável;
  - nenhuma escolha implícita "pelo convite mais recente" no caminho explícito.

Migrations não são aplicadas aqui: a RPC é validada por testes de contrato
sobre o SQL (como já feito para a migration 020).
"""

import os
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException

SERVER_DIR = str(Path(__file__).parents[1])
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from routes import invitations as routes  # noqa: E402
from services import invitations, auth as auth_service  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "supabase/migrations/20260819_000034_multi_tenant_invitation_acceptance.sql"

SUPA_ENV = {
    "SUPABASE_URL": "https://proj.supabase.co",
    "SUPABASE_SERVICE_ROLE_KEY": "service-role-key-longer-than-20-chars",
    "SUPABASE_INVITE_REDIRECT_URL": "https://dados.mugoagencia.com.br/?type=invite",
}


def _http_error(status, body):
    request = httpx.Request("POST", "https://proj.supabase.co/rest/v1/rpc/accept_user_invitation")
    response = httpx.Response(status, json=body, request=request)
    return httpx.HTTPStatusError("err", request=request, response=response)


class _FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body
        self.content = b"x" if body is not None else b""

    def json(self):
        if self._body is None:
            raise ValueError("no body")
        return self._body


class _FakeClient:
    """Devolve respostas em sequência (uma por POST).

    `responses` é uma lista mutável COMPARTILHADA entre instâncias — cada
    `generate_supabase_action_link` abre um `AsyncClient` novo, mas todos
    consomem a mesma fila.
    """

    def __init__(self, responses, sink):
        self._responses = responses
        self._sink = sink

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    async def post(self, url, *, params=None, headers=None, json=None):
        self._sink.setdefault("calls", []).append({"url": url, "params": params or {}, "json": json or {}})
        return self._responses.pop(0)


# ---------------------------------------------------------------------------
# RPC de aceitação explícita — serviço
# ---------------------------------------------------------------------------
class AcceptInvitationService(unittest.IsolatedAsyncioTestCase):
    async def test_passes_actor_and_invitation_id_only_never_client_id_or_role(self):
        rpc = AsyncMock(return_value={"client_id": "empresa-b", "role": "owner"})
        with patch.object(invitations, "sb_rpc", rpc):
            result = await invitations.accept_user_invitation(
                actor_user_id="user-1", invitation_id="inv-b",
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["client_id"], "empresa-b")
        self.assertEqual(result["role"], "owner")
        self.assertEqual(rpc.await_args.args[0], "accept_user_invitation")
        args = rpc.await_args.args[1]
        self.assertEqual(args, {"p_actor_user_id": "user-1", "p_invitation_id": "inv-b"})
        self.assertNotIn("p_client_id", args)
        self.assertNotIn("p_role", args)

    async def test_email_mismatch_is_403(self):
        with patch.object(invitations, "sb_rpc", AsyncMock(side_effect=_http_error(403, {"message": "invitation_email_mismatch"}))):
            with self.assertRaises(invitations.InvitationError) as raised:
                await invitations.accept_user_invitation(actor_user_id="intruder", invitation_id="inv-b")
        self.assertEqual(raised.exception.status_code, 403)

    async def test_expired_is_409(self):
        with patch.object(invitations, "sb_rpc", AsyncMock(side_effect=_http_error(409, {"message": "invitation_expired"}))):
            with self.assertRaises(invitations.InvitationError) as raised:
                await invitations.accept_user_invitation(actor_user_id="user-1", invitation_id="inv-b")
        self.assertEqual(raised.exception.status_code, 409)

    async def test_revoked_is_409(self):
        with patch.object(invitations, "sb_rpc", AsyncMock(side_effect=_http_error(409, {"message": "invitation_revoked"}))):
            with self.assertRaises(invitations.InvitationError) as raised:
                await invitations.accept_user_invitation(actor_user_id="user-1", invitation_id="inv-b")
        self.assertEqual(raised.exception.status_code, 409)

    async def test_already_accepted_is_409(self):
        with patch.object(invitations, "sb_rpc", AsyncMock(side_effect=_http_error(409, {"message": "invitation_already_accepted"}))):
            with self.assertRaises(invitations.InvitationError) as raised:
                await invitations.accept_user_invitation(actor_user_id="user-1", invitation_id="inv-b")
        self.assertEqual(raised.exception.status_code, 409)

    async def test_not_found_is_404(self):
        with patch.object(invitations, "sb_rpc", AsyncMock(side_effect=_http_error(404, {"message": "invitation_not_found"}))):
            with self.assertRaises(invitations.InvitationError) as raised:
                await invitations.accept_user_invitation(actor_user_id="user-1", invitation_id="ghost")
        self.assertEqual(raised.exception.status_code, 404)


# ---------------------------------------------------------------------------
# Rota de aceitação
# ---------------------------------------------------------------------------
class AcceptInvitationRoute(unittest.IsolatedAsyncioTestCase):
    async def test_requires_authenticated_user(self):
        with patch.object(routes, "require_user_id", AsyncMock(side_effect=HTTPException(status_code=401, detail="x"))):
            with self.assertRaises(HTTPException) as raised:
                await routes.accept_invitation("inv-b", "")
        self.assertEqual(raised.exception.status_code, 401)

    async def test_actor_comes_from_jwt_and_invitation_id_from_path(self):
        svc = AsyncMock(return_value={"ok": True, "client_id": "empresa-b", "role": "owner"})
        with (
            patch.object(routes, "require_user_id", AsyncMock(return_value="user-jwt")),
            patch.object(routes, "accept_user_invitation", svc),
        ):
            result = await routes.accept_invitation("inv-b", "Bearer token")
        self.assertEqual(result["client_id"], "empresa-b")
        self.assertEqual(svc.await_args.kwargs, {"actor_user_id": "user-jwt", "invitation_id": "inv-b"})

    async def test_body_client_id_is_ignored_route_has_no_body(self):
        # a assinatura da rota não aceita corpo: nada do frontend define tenant.
        import inspect
        params = inspect.signature(routes.accept_invitation).parameters
        self.assertNotIn("payload", params)
        self.assertIn("invitation_id", params)

    async def test_invitation_error_status_is_preserved(self):
        with (
            patch.object(routes, "require_user_id", AsyncMock(return_value="user-1")),
            patch.object(
                routes, "accept_user_invitation",
                AsyncMock(side_effect=invitations.InvitationError("mismatch", status_code=403)),
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                await routes.accept_invitation("inv-b", "Bearer token")
        self.assertEqual(raised.exception.status_code, 403)


# ---------------------------------------------------------------------------
# GET /api/invitations/mine — convites pendentes do usuário autenticado
# ---------------------------------------------------------------------------
class MyPendingInvitations(unittest.IsolatedAsyncioTestCase):
    def _rows(self):
        return [
            {
                "id": "inv-b", "email": "user@cliente.com", "client_id": "empresa-b", "role": "owner",
                "accepted_at": None, "revoked_at": None, "expires_at": "2099-01-01T00:00:00Z",
                "token_hash": "SECRET-HASH", "invited_by": "master",
            },
            {
                "id": "inv-old", "email": "user@cliente.com", "client_id": "empresa-x", "role": "viewer",
                "accepted_at": None, "revoked_at": None, "expires_at": "2000-01-01T00:00:00Z",
                "token_hash": "SECRET-HASH-2", "invited_by": "master",
            },
        ]

    async def test_returns_only_usable_invitations_and_never_leaks_token_hash(self):
        with (
            patch.object(invitations, "sb_select", AsyncMock(side_effect=[self._rows(), [{"id": "empresa-b", "name": "Empresa B", "trade_name": "B"}]])),
        ):
            result = await invitations.list_pending_invitations_for_email("User@Cliente.com")
        ids = [item["id"] for item in result]
        self.assertEqual(ids, ["inv-b"])  # expirada excluída
        blob = repr(result)
        self.assertNotIn("SECRET-HASH", blob)
        self.assertNotIn("token_hash", blob)
        self.assertNotIn("invited_by", blob)
        self.assertEqual(result[0]["client_id"], "empresa-b")
        self.assertEqual(result[0]["role"], "owner")

    async def test_route_uses_authenticated_email_not_a_parameter(self):
        with (
            patch.object(routes, "get_user_from_bearer", AsyncMock(return_value={"id": "u1", "email": "user@cliente.com"})),
            patch.object(routes, "list_pending_invitations_for_email", AsyncMock(return_value=[{"id": "inv-b"}])) as lister,
        ):
            result = await routes.my_pending_invitations("Bearer token")
        self.assertTrue(result["ok"])
        self.assertEqual(lister.await_args.args[0], "user@cliente.com")

    async def test_route_requires_authentication(self):
        with patch.object(routes, "get_user_from_bearer", AsyncMock(return_value=None)):
            with self.assertRaises(HTTPException) as raised:
                await routes.my_pending_invitations("")
        self.assertEqual(raised.exception.status_code, 401)


# ---------------------------------------------------------------------------
# Link de ativação para usuário já existente (invite -> magiclink)
# ---------------------------------------------------------------------------
class ActivationLinkExistingUser(unittest.IsolatedAsyncioTestCase):
    async def _generate(self, responses):
        sink = {}
        with (
            patch.dict(os.environ, SUPA_ENV, clear=False),
            patch.object(invitations.httpx, "AsyncClient", lambda *a, **k: _FakeClient(responses, sink)),
        ):
            out = await invitations.generate_company_activation_link(
                email="owner@acme.test", invitation_id="inv-1", client_id="company-1", role="owner",
            )
        return out, sink

    async def test_new_user_uses_invite_type(self):
        out, sink = await self._generate([_FakeResponse(200, {"action_link": "https://x/verify?token=a"})])
        self.assertEqual(out["account_exists"], False)
        self.assertEqual(out["activation_url"], "https://x/verify?token=a")
        self.assertEqual(sink["calls"][0]["json"]["type"], "invite")

    async def test_existing_confirmed_user_falls_back_to_magiclink(self):
        out, sink = await self._generate([
            _FakeResponse(422, {"error_code": "email_exists"}),
            _FakeResponse(200, {"action_link": "https://x/verify?token=magic"}),
        ])
        self.assertEqual(out["account_exists"], True)
        self.assertEqual(out["activation_url"], "https://x/verify?token=magic")
        self.assertEqual(sink["calls"][0]["json"]["type"], "invite")
        self.assertEqual(sink["calls"][1]["json"]["type"], "magiclink")

    async def test_no_raw_error_about_existing_account_is_surfaced(self):
        out, _ = await self._generate([
            _FakeResponse(422, {"error_code": "email_exists"}),
            _FakeResponse(200, {"action_link": "https://x/verify?token=magic"}),
        ])
        self.assertTrue(out["activation_url"])  # não levanta

    async def test_both_types_failing_is_controlled_error(self):
        with self.assertRaisesRegex(RuntimeError, "link de ativação"):
            await self._generate([
                _FakeResponse(422, {"error_code": "email_exists"}),
                _FakeResponse(500, {"msg": "boom"}),
            ])

    async def test_invitation_id_is_carried_in_data_for_both_types(self):
        _, sink = await self._generate([
            _FakeResponse(422, {"error_code": "email_exists"}),
            _FakeResponse(200, {"action_link": "https://x/verify?token=magic"}),
        ])
        for call in sink["calls"]:
            self.assertEqual(call["json"]["data"]["invitation_id"], "inv-1")
            self.assertEqual(call["json"]["data"]["client_id"], "company-1")

    async def test_platform_service_exposes_account_exists(self):
        from services import platform_admin
        with (
            patch.object(platform_admin, "sb_select", AsyncMock(return_value=[{"id": "company-1", "responsible_email": "owner@acme.test"}])),
            patch.object(
                platform_admin, "get_or_create_company_activation_invitation",
                AsyncMock(return_value={"id": "inv-1", "role": "owner"}),
            ),
            patch.object(
                platform_admin, "generate_company_activation_link",
                AsyncMock(return_value={"activation_url": "https://x", "account_exists": True}),
            ),
            patch.object(platform_admin, "sb_insert", AsyncMock()),
        ):
            result = await platform_admin.create_company_activation_link("master", "company-1")
        self.assertEqual(result["account_exists"], True)
        self.assertEqual(result["activation_url"], "https://x")


# ---------------------------------------------------------------------------
# Contrato da migration local — RPC segura + trigger sem regressão
# ---------------------------------------------------------------------------
class InvitationAcceptanceMigrationContract(unittest.TestCase):
    def setUp(self):
        self.sql = MIGRATION.read_text().lower()

    def test_migration_file_exists_and_is_local_only(self):
        self.assertTrue(MIGRATION.exists())

    def test_accept_rpc_is_security_definer_with_fixed_search_path(self):
        self.assertIn("create or replace function public.accept_user_invitation", self.sql)
        self.assertIn("security definer", self.sql)
        self.assertIn("set search_path", self.sql)

    def test_accept_rpc_takes_actor_and_invitation_id(self):
        self.assertIn("p_actor_user_id uuid", self.sql)
        self.assertIn("p_invitation_id uuid", self.sql)

    def test_accept_rpc_derives_email_from_auth_users_and_requires_match(self):
        self.assertIn("from auth.users", self.sql)
        self.assertIn("lower(", self.sql)
        self.assertIn("invitation_email_mismatch", self.sql)

    def test_accept_rpc_rejects_expired_revoked_and_used(self):
        self.assertIn("invitation_expired", self.sql)
        self.assertIn("invitation_revoked", self.sql)
        self.assertIn("invitation_already_accepted", self.sql)
        self.assertIn("expires_at", self.sql)

    def test_accept_rpc_membership_comes_from_invitation_row_only(self):
        self.assertIn("insert into public.client_memberships", self.sql)
        self.assertIn("invitation.client_id", self.sql)
        self.assertIn("invitation.role", self.sql)
        # nunca aceita client_id/role como parâmetro
        self.assertNotIn("p_client_id", self.sql)
        self.assertNotIn("p_role", self.sql)

    def test_accept_rpc_is_additive_never_deletes_memberships(self):
        self.assertIn("on conflict", self.sql)
        self.assertNotIn("delete from public.client_memberships", self.sql)

    def test_accept_rpc_consumes_invitation_exactly_once_and_audits(self):
        self.assertIn("set accepted_at = now(), accepted_by = p_actor_user_id", self.sql)
        self.assertIn("and accepted_at is null", self.sql)
        self.assertIn("platform_audit_events", self.sql)
        self.assertIn("invitation_accepted", self.sql)

    def test_accept_rpc_is_service_role_only(self):
        self.assertIn("revoke all on function public.accept_user_invitation", self.sql)
        self.assertIn("from public, anon, authenticated", self.sql)
        self.assertIn("grant execute on function public.accept_user_invitation", self.sql)
        self.assertIn("to service_role", self.sql)

    def test_trigger_new_user_path_preserved(self):
        # o guard de "só primeira confirmação" continua (usuário existente NÃO
        # é vinculado pelo trigger — usa a RPC explícita).
        self.assertIn("old.email_confirmed_at is not null", self.sql)
        self.assertIn("when (new.email_confirmed_at is not null)", self.sql)

    def test_trigger_prefers_explicit_invitation_id_from_metadata(self):
        self.assertIn("raw_user_meta_data", self.sql)
        self.assertIn("invitation_id", self.sql)

    def test_trigger_still_binds_membership_to_invitation_tenant_and_role(self):
        self.assertIn("values(new.id, invitation.client_id, invitation.role)", self.sql)

    def test_migration_does_not_drop_tables_or_memberships(self):
        self.assertNotIn("drop table", self.sql)
        self.assertNotIn("truncate", self.sql)
        self.assertNotIn("delete from public.client_memberships", self.sql)


if __name__ == "__main__":
    unittest.main()
