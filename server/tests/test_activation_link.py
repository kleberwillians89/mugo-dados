"""Bloco 2 — link de ativação da empresa (GoTrue Admin generate_link).

Comportamento desejado:
  - só usuário Mugô autorizado (`require_platform_admin`) gera o link;
  - o tenant vem SEMPRE do path, validado contra `clients`;
  - o link é atrelado à invitation correta da empresa;
  - reaproveita convite pendente válido, sem duplicar;
  - nenhum token bruto é persistido (só `token_hash` do token interno);
  - request bate exatamente no contrato do GoTrue Admin API instalado
    (`supabase-auth` 2.31.0: POST /auth/v1/admin/generate_link, redirect_to em
    query, body {type,email,data}, resposta com `action_link`);
  - o vínculo usuário→tenant continua sendo o trigger `accept_pending_user_invitation`.
"""

import os
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

SERVER_DIR = str(Path(__file__).parents[1])
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from routes import platform_admin as routes  # noqa: E402
from services import invitations, platform_admin, tenant  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SUPA_ENV = {
    "SUPABASE_URL": "https://proj.supabase.co",
    "SUPABASE_SERVICE_ROLE_KEY": "service-role-key-longer-than-20-chars",
    "SUPABASE_INVITE_REDIRECT_URL": "https://dados.mugoagencia.com.br/?type=invite",
}


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
    def __init__(self, response, sink):
        self._response = response
        self._sink = sink

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def post(self, url, *, params=None, headers=None, json=None):
        self._sink.update({"url": url, "params": params or {}, "headers": headers or {}, "json": json or {}})
        return self._response


# ---------------------------------------------------------------------------
# Autorização — só Mugô gera o link
# ---------------------------------------------------------------------------
class ActivationLinkAuthorization(unittest.IsolatedAsyncioTestCase):
    async def test_platform_admin_generates_link_for_explicit_tenant(self):
        payload = {"ok": True, "invitation": {"id": "inv-1"}, "activation_url": "https://link"}
        with (
            patch.object(routes, "require_platform_admin", AsyncMock(return_value="master")),
            patch.object(routes, "create_company_activation_link", AsyncMock(return_value=payload)) as svc,
        ):
            result = await routes.platform_company_activation_link("company-1", "Bearer token")
        self.assertEqual(result["activation_url"], "https://link")
        svc.assert_awaited_once_with("master", "company-1")

    async def test_common_user_cannot_generate_activation_link(self):
        with (
            patch.object(platform_admin, "require_user_id", AsyncMock(return_value="common")),
            patch.object(platform_admin, "is_platform_admin", AsyncMock(return_value=False)),
            patch("services.tenant._has_agency_admin_membership", AsyncMock(return_value=False)),
            patch.object(routes, "create_company_activation_link", AsyncMock()) as svc,
        ):
            with self.assertRaises(HTTPException) as raised:
                await routes.platform_company_activation_link("company-1", "Bearer token")
        self.assertEqual(raised.exception.status_code, 403)
        svc.assert_not_awaited()

    async def test_viewer_or_client_admin_cannot_generate_link_for_other_tenant(self):
        # papel comum de tenant (sem platform_admin, sem agency_admin) -> 403
        for role in ("viewer", "client_admin"):
            with self.subTest(role=role):
                with (
                    patch.object(platform_admin, "require_user_id", AsyncMock(return_value=f"{role}-amalie")),
                    patch.object(platform_admin, "is_platform_admin", AsyncMock(return_value=False)),
                    patch.object(
                        tenant, "sb_get_client_memberships",
                        AsyncMock(return_value=[{"client_id": "amalie", "role": role}]),
                    ),
                    patch.object(routes, "create_company_activation_link", AsyncMock()) as svc,
                ):
                    with self.assertRaises(HTTPException) as raised:
                        await routes.platform_company_activation_link("roove", "Bearer token")
                self.assertEqual(raised.exception.status_code, 403)
                svc.assert_not_awaited()


# ---------------------------------------------------------------------------
# Orquestração — create_company_activation_link
# ---------------------------------------------------------------------------
class ActivationLinkService(unittest.IsolatedAsyncioTestCase):
    def _company_row(self):
        return [{"id": "company-1", "name": "Acme", "responsible_email": "Owner@Acme.test", "status": "invitation_pending"}]

    async def test_tenant_and_email_come_from_persisted_company_not_frontend(self):
        gen = AsyncMock(return_value={
            "activation_url": "https://proj.supabase.co/auth/v1/verify?token=abc",
            "account_exists": False,
        })
        with (
            patch.object(platform_admin, "sb_select", AsyncMock(return_value=self._company_row())),
            patch.object(
                platform_admin, "get_or_create_company_activation_invitation",
                AsyncMock(return_value={"id": "inv-1", "role": "owner", "expires_at": "2099-01-01T00:00:00Z"}),
            ) as ensure,
            patch.object(platform_admin, "generate_company_activation_link", gen),
            patch.object(platform_admin, "sb_insert", AsyncMock()),
        ):
            result = await platform_admin.create_company_activation_link("master", "company-1")
        self.assertEqual(result["invitation"]["id"], "inv-1")
        self.assertEqual(result["invitation"]["client_id"], "company-1")
        self.assertEqual(result["invitation"]["email"], "owner@acme.test")
        self.assertEqual(result["activation_url"], "https://proj.supabase.co/auth/v1/verify?token=abc")
        self.assertEqual(ensure.await_args.kwargs["client_id"], "company-1")
        self.assertEqual(ensure.await_args.kwargs["email"], "owner@acme.test")
        self.assertEqual(gen.await_args.kwargs["invitation_id"], "inv-1")
        self.assertEqual(gen.await_args.kwargs["client_id"], "company-1")

    async def test_unknown_company_raises_controlled_error(self):
        with patch.object(platform_admin, "sb_select", AsyncMock(return_value=[])):
            with self.assertRaisesRegex(RuntimeError, "não encontrada"):
                await platform_admin.create_company_activation_link("master", "ghost")

    async def test_company_without_responsible_email_raises_controlled_error(self):
        with patch.object(
            platform_admin, "sb_select",
            AsyncMock(return_value=[{"id": "company-1", "responsible_email": ""}]),
        ):
            with self.assertRaisesRegex(RuntimeError, "e-mail"):
                await platform_admin.create_company_activation_link("master", "company-1")

    async def test_generation_is_audited(self):
        audit = AsyncMock()
        with (
            patch.object(platform_admin, "sb_select", AsyncMock(return_value=self._company_row())),
            patch.object(
                platform_admin, "get_or_create_company_activation_invitation",
                AsyncMock(return_value={"id": "inv-1", "role": "owner"}),
            ),
            patch.object(
                platform_admin, "generate_company_activation_link",
                AsyncMock(return_value={"activation_url": "https://x", "account_exists": False}),
            ),
            patch.object(platform_admin, "sb_insert", audit),
        ):
            await platform_admin.create_company_activation_link("master", "company-1")
        self.assertEqual(audit.await_args.args[0], "platform_audit_events")
        self.assertEqual(audit.await_args.args[1]["event_type"], "activation_link_generated")
        self.assertEqual(audit.await_args.args[1]["client_id"], "company-1")

    async def test_existing_account_error_surfaces_as_http_400(self):
        with (
            patch.object(routes, "require_platform_admin", AsyncMock(return_value="master")),
            patch.object(
                routes, "create_company_activation_link",
                AsyncMock(side_effect=RuntimeError("Este e-mail já possui uma conta ativa na Mugô.")),
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                await routes.platform_company_activation_link("company-1", "Bearer token")
        self.assertEqual(raised.exception.status_code, 400)


# ---------------------------------------------------------------------------
# Reuso / criação de convite — sem duplicar
# ---------------------------------------------------------------------------
class ActivationInvitationReuse(unittest.IsolatedAsyncioTestCase):
    async def test_reuses_valid_pending_invitation_without_new_insert(self):
        usable = {
            "id": "inv-existing", "email": "owner@acme.test", "client_id": "company-1",
            "role": "owner", "accepted_at": None, "revoked_at": None,
            "expires_at": "2099-01-01T00:00:00Z",
        }
        insert = AsyncMock()
        with (
            patch.object(invitations, "sb_select", AsyncMock(return_value=[usable])),
            patch.object(invitations, "sb_insert", insert),
        ):
            result = await invitations.get_or_create_company_activation_invitation(
                client_id="company-1", email="owner@acme.test", invited_by="master",
            )
        self.assertEqual(result["id"], "inv-existing")
        insert.assert_not_awaited()

    async def test_creates_invitation_when_none_usable_and_stores_only_hash(self):
        insert = AsyncMock(return_value={"id": "inv-new", "role": "owner", "expires_at": "x"})
        with (
            patch.object(invitations, "sb_select", AsyncMock(return_value=[])),
            patch.object(invitations, "sb_insert", insert),
        ):
            result = await invitations.get_or_create_company_activation_invitation(
                client_id="company-1", email="owner@acme.test", invited_by="master",
            )
        self.assertEqual(result["id"], "inv-new")
        row = insert.await_args.args[1]
        self.assertIn("token_hash", row)
        self.assertNotIn("token", row)
        self.assertEqual(len(row["token_hash"]), 64)  # sha256 hex
        self.assertEqual(row["client_id"], "company-1")
        self.assertEqual(row["role"], "owner")

    async def test_expired_pending_invitation_is_not_reused(self):
        expired = {
            "id": "inv-old", "accepted_at": None, "revoked_at": None,
            "expires_at": "2000-01-01T00:00:00Z",
        }
        insert = AsyncMock(return_value={"id": "inv-new", "role": "owner"})
        with (
            patch.object(invitations, "sb_select", AsyncMock(return_value=[expired])),
            patch.object(invitations, "sb_insert", insert),
        ):
            result = await invitations.get_or_create_company_activation_invitation(
                client_id="company-1", email="owner@acme.test", invited_by="master",
            )
        self.assertEqual(result["id"], "inv-new")
        insert.assert_awaited_once()

    async def test_invalid_role_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "Função"):
            await invitations.get_or_create_company_activation_invitation(
                client_id="company-1", email="owner@acme.test", invited_by="master", role="superuser",
            )


# ---------------------------------------------------------------------------
# Contrato do GoTrue Admin generate_link + ausência de token bruto
# ---------------------------------------------------------------------------
class GenerateSupabaseActionLink(unittest.IsolatedAsyncioTestCase):
    async def _call(self, response, sink):
        with (
            patch.dict(os.environ, SUPA_ENV, clear=False),
            patch.object(invitations.httpx, "AsyncClient", lambda *a, **k: _FakeClient(response, sink)),
        ):
            return await invitations.generate_supabase_action_link(
                email="Owner@Acme.test", invitation_id="inv-1", client_id="company-1", role="owner",
            )

    async def test_request_matches_gotrue_admin_api_contract(self):
        sink = {}
        link = await self._call(
            _FakeResponse(200, {
                "action_link": "https://proj.supabase.co/auth/v1/verify?type=invite&token=hashed&redirect_to=x",
                "hashed_token": "hashed", "verification_type": "invite", "email_otp": "123456",
                "id": "user-uuid", "email": "owner@acme.test",
            }),
            sink,
        )
        self.assertTrue(link.endswith("token=hashed&redirect_to=x"))
        self.assertTrue(sink["url"].endswith("/auth/v1/admin/generate_link"))
        self.assertEqual(sink["params"]["redirect_to"], SUPA_ENV["SUPABASE_INVITE_REDIRECT_URL"])
        self.assertEqual(sink["headers"]["apikey"], SUPA_ENV["SUPABASE_SERVICE_ROLE_KEY"])
        self.assertEqual(sink["headers"]["Authorization"], f"Bearer {SUPA_ENV['SUPABASE_SERVICE_ROLE_KEY']}")
        self.assertEqual(sink["json"]["type"], "invite")
        self.assertEqual(sink["json"]["email"], "owner@acme.test")
        self.assertEqual(sink["json"]["data"], {"invitation_id": "inv-1", "client_id": "company-1", "role": "owner"})
        self.assertNotIn("password", sink["json"].get("data", {}))

    async def test_never_persists_anything(self):
        sink = {}
        with patch.object(invitations, "sb_insert", AsyncMock()) as ins, patch.object(invitations, "sb_select", AsyncMock()) as sel:
            await self._call(_FakeResponse(200, {"action_link": "https://x/verify?token=y"}), sink)
        ins.assert_not_awaited()
        sel.assert_not_awaited()

    async def test_existing_confirmed_user_returns_controlled_error(self):
        with self.assertRaisesRegex(RuntimeError, "conta ativa"):
            await self._call(_FakeResponse(422, {"error_code": "email_exists"}), {})

    async def test_other_supabase_error_is_controlled(self):
        with self.assertRaisesRegex(RuntimeError, "link de ativação"):
            await self._call(_FakeResponse(500, {"msg": "boom"}), {})

    async def test_missing_action_link_is_controlled(self):
        with self.assertRaisesRegex(RuntimeError, "não retornou"):
            await self._call(_FakeResponse(200, {"hashed_token": "h"}), {})

    async def test_unconfigured_backend_is_controlled(self):
        with (
            patch.dict(os.environ, {"SUPABASE_URL": "", "SUPABASE_SERVICE_ROLE_KEY": "", "SUPABASE_INVITE_REDIRECT_URL": ""}, clear=False),
        ):
            with self.assertRaisesRegex(RuntimeError, "não configurado"):
                await invitations.generate_supabase_action_link(
                    email="a@b.test", invitation_id="i", client_id="c", role="owner",
                )


# ---------------------------------------------------------------------------
# Contrato do trigger que garante usuário -> convite -> client_id -> membership
# ---------------------------------------------------------------------------
class InvitationTriggerContract(unittest.TestCase):
    def setUp(self):
        self.sql = "\n".join(
            (ROOT / "supabase/migrations" / name).read_text().lower()
            for name in (
                "20260731_000019_auth_oauth_connections.sql",
                "20260801_000020_platform_admin_companies.sql",
            )
        )

    def test_membership_is_bound_to_invitation_tenant_and_role(self):
        self.assertIn("insert into public.client_memberships(user_id, client_id, role)", self.sql)
        self.assertIn("values(new.id, invitation.client_id, invitation.role)", self.sql)

    def test_invitation_is_matched_by_email_only(self):
        self.assertIn("where lower(email) = lower(new.email)", self.sql)

    def test_expired_used_or_revoked_invitations_are_excluded(self):
        self.assertIn("accepted_at is null", self.sql)
        self.assertIn("revoked_at is null", self.sql)
        self.assertIn("expires_at > now()", self.sql)

    def test_invitation_is_consumed_exactly_once(self):
        self.assertIn("set accepted_at = now(), accepted_by = new.id", self.sql)
        self.assertIn("where id = invitation.id and accepted_at is null", self.sql)

    def test_trigger_only_fires_on_first_confirmation(self):
        # documenta o gap conhecido para usuário JÁ confirmado: o trigger sai
        # cedo e não cria membership nesse caso (correção futura = migration).
        self.assertIn("if tg_op = 'update' and old.email_confirmed_at is not null then", self.sql)
        self.assertIn("when (new.email_confirmed_at is not null)", self.sql)

    def test_no_client_id_from_request_body_influences_membership(self):
        # a função só usa invitation.client_id; nunca um valor externo/arbitrário.
        self.assertNotIn("new.raw_user_meta_data", self.sql.split("accept_pending_user_invitation")[1] if "accept_pending_user_invitation" in self.sql else self.sql)


if __name__ == "__main__":
    unittest.main()
