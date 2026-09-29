import os
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException

SERVER_DIR = str(Path(__file__).parents[1])
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from routes import platform_admin as routes
from routes import meta_legacy
from services import platform_admin, tenant
from services import invitations


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
        self.text = "" if body is None else str(body)

    def json(self):
        if self._body is None:
            raise ValueError("no body")
        return self._body


class _FakeClient:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def post(self, url, *, params=None, headers=None, json=None):
        return self._response


class PlatformAdminAuthorizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_unauthenticated_platform_request_returns_401(self):
        os.environ["ALLOW_NO_AUTH"] = "false"
        with patch.object(tenant, "get_user_id_from_bearer", AsyncMock(return_value=None)):
            with self.assertRaises(HTTPException) as raised:
                await platform_admin.require_platform_admin(None)
        self.assertEqual(raised.exception.status_code, 401)

    async def test_common_user_returns_403(self):
        with (
            patch.object(platform_admin, "require_user_id", AsyncMock(return_value="common")),
            patch.object(platform_admin, "is_platform_admin", AsyncMock(return_value=False)),
        ):
            with self.assertRaises(HTTPException) as raised:
                await platform_admin.require_platform_admin("Bearer token")
        self.assertEqual(raised.exception.status_code, 403)

    async def test_master_user_is_authorized_without_membership(self):
        with (
            patch.object(platform_admin, "require_user_id", AsyncMock(return_value="master")),
            patch.object(platform_admin, "is_platform_admin", AsyncMock(return_value=True)),
        ):
            self.assertEqual(
                await platform_admin.require_platform_admin("Bearer token"), "master"
            )

    async def test_platform_me_does_not_depend_on_email_or_metadata(self):
        with (
            patch.object(routes, "require_user_id", AsyncMock(return_value="uid")),
            patch.object(routes, "is_platform_admin", AsyncMock(return_value=True)),
        ):
            result = await routes.platform_me("Bearer token")
        self.assertTrue(result["is_platform_admin"])


class PlatformCompanyTests(unittest.IsolatedAsyncioTestCase):
    async def test_creation_uses_atomic_database_rpc_then_invites_owner(self):
        created = {
            "client": {"id": "company-1", "name": "Acme"},
            "invitation": {"id": "invite-1", "role": "owner"},
        }
        rpc = AsyncMock(return_value=created)
        invite = AsyncMock(return_value=None)
        with (
            patch.object(platform_admin, "sb_rpc", rpc),
            patch.object(platform_admin, "send_supabase_invite", invite),
        ):
            result = await platform_admin.create_platform_company(
                "master", {"name": "Acme", "responsible_email": "owner@acme.test"}
            )
        self.assertTrue(result["ok"])
        self.assertEqual(rpc.await_args.args[0], "create_platform_company")
        self.assertEqual(invite.await_args.kwargs["role"], "owner")

    async def test_invite_failure_compensates_without_orphan_company(self):
        rpc = AsyncMock(
            side_effect=[
                {"client": {"id": "company-1"}, "invitation": {"id": "invite-1"}},
                True,
            ]
        )
        with (
            patch.object(platform_admin, "sb_rpc", rpc),
            patch.object(
                platform_admin,
                "send_supabase_invite",
                AsyncMock(side_effect=RuntimeError("invite failed")),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "invite failed"):
                await platform_admin.create_platform_company(
                    "master", {"name": "Acme", "responsible_email": "owner@acme.test"}
                )
        self.assertEqual(rpc.await_args_list[1].args[0], "rollback_platform_company_creation")

    async def test_common_user_cannot_use_legacy_post_clients(self):
        with patch(
            "services.platform_admin.require_platform_admin",
            AsyncMock(side_effect=HTTPException(status_code=403, detail="denied")),
        ):
            with self.assertRaises(HTTPException) as raised:
                await meta_legacy.api_create_client(
                    {"name": "Acme", "responsible_email": "a@b.test"}, "Bearer token"
                )
        self.assertEqual(raised.exception.status_code, 403)

    async def test_company_list_is_global_only_after_route_guard(self):
        with (
            patch.object(routes, "require_platform_admin", AsyncMock(return_value="master")),
            patch.object(
                routes,
                "list_platform_companies",
                AsyncMock(return_value={"ok": True, "companies": [{"id": "a"}, {"id": "b"}]}),
            ),
        ):
            result = await routes.platform_companies("Bearer token")
        self.assertEqual(len(result["companies"]), 2)

    async def test_support_access_is_explicit_and_audited(self):
        rpc = AsyncMock(return_value=True)
        with (
            patch.object(routes, "require_platform_admin", AsyncMock(return_value="master")),
            patch.object(routes, "sb_select", AsyncMock(return_value=[{"id": "company-1"}])),
            patch.object(routes, "sb_rpc", rpc),
        ):
            result = await routes.platform_open_company("company-1", "Bearer token")
        self.assertTrue(result["ok"])
        self.assertEqual(rpc.await_args.args[0], "audit_platform_company_access")

    async def test_platform_admin_updates_company_with_audit(self):
        with (
            patch.object(
                platform_admin,
                "sb_update",
                AsyncMock(return_value=[{"id": "company-1", "status": "inactive"}]),
            ),
            patch.object(platform_admin, "sb_insert", AsyncMock(return_value={"ok": True})) as audit,
        ):
            result = await platform_admin.update_platform_company(
                "master", "company-1", {"status": "inactive"}
            )
        self.assertEqual(result["company"]["status"], "inactive")
        self.assertEqual(audit.await_args.args[0], "platform_audit_events")


class ResponsibleAlreadyHasAccountTests(unittest.IsolatedAsyncioTestCase):
    """BLOCO estabilização — responsável com conta Supabase já existente.

    Criar uma 2ª empresa para um cliente existente (ou usar um e-mail já
    cadastrado) é cenário comercial normal. Hoje o GoTrue /invite recusa e a
    criação inteira é revertida com um erro genérico e enganoso.
    """

    async def test_send_invite_flags_existing_account_instead_of_generic_failure(self):
        resp = _FakeResponse(
            422,
            {"code": 422, "error_code": "email_exists",
             "msg": "A user with this email address has already been registered"},
        )
        with (
            patch.dict(os.environ, SUPA_ENV, clear=False),
            patch.object(invitations.httpx, "AsyncClient", lambda *a, **k: _FakeClient(resp)),
        ):
            with self.assertRaises(invitations.SupabaseAccountExistsError):
                await invitations.send_supabase_invite(
                    email="owner@acme.test", invitation_id="i1", client_id="c1", role="owner"
                )

    async def test_company_survives_when_responsible_already_has_account(self):
        created = {
            "client": {"id": "company-1", "name": "Acme"},
            "invitation": {"id": "invite-1", "role": "owner"},
        }
        rpc = AsyncMock(return_value=created)
        with (
            patch.object(platform_admin, "sb_rpc", rpc),
            patch.object(
                platform_admin, "send_supabase_invite",
                AsyncMock(side_effect=invitations.SupabaseAccountExistsError("exists")),
            ),
            patch.object(platform_admin, "sb_insert", AsyncMock(return_value={"ok": True})),
        ):
            result = await platform_admin.create_platform_company(
                "master", {"name": "Acme", "responsible_email": "Owner@Acme.test"}
            )
        self.assertTrue(result["ok"])
        self.assertIs(result.get("responsible_account_exists"), True)
        self.assertEqual(result["company"]["id"], "company-1")
        # Nunca reverte: a empresa e a invitation continuam válidas.
        self.assertEqual([c.args[0] for c in rpc.await_args_list], ["create_platform_company"])


class CreateCompanyRpcErrorTests(unittest.IsolatedAsyncioTestCase):
    """BLOCO estabilização — falha na RPC não pode virar 500 opaco."""

    async def test_rpc_error_becomes_clean_4xx_not_500(self):
        req = httpx.Request("POST", "https://proj.supabase.co/rest/v1/rpc/create_platform_company")
        resp = httpx.Response(403, request=req, json={"message": "platform_admin_required"})
        with patch.object(
            platform_admin, "sb_rpc",
            AsyncMock(side_effect=httpx.HTTPStatusError("403", request=req, response=resp)),
        ):
            with self.assertRaises(RuntimeError) as raised:
                await platform_admin.create_platform_company(
                    "agency-user", {"name": "Acme", "responsible_email": "a@b.test"}
                )
        self.assertNotIn("INTERNAL", str(raised.exception).upper())


class CreateInvitationRoleTests(unittest.IsolatedAsyncioTestCase):
    """BLOCO estabilização — `owner` é papel válido de convite (painel oferece)."""

    async def test_owner_role_is_accepted_by_create_invitation(self):
        with (
            patch.object(invitations, "sb_select", AsyncMock(return_value=[])),
            patch.object(invitations, "sb_insert", AsyncMock(return_value={"id": "inv-1"})),
            patch.object(invitations, "send_supabase_invite", AsyncMock(return_value=None)),
        ):
            result = await invitations.create_invitation(
                email="owner@acme.test", client_id="c1", role="owner", invited_by="u1"
            )
        self.assertEqual(result["role"], "owner")


class IdempotentCompanyCreationTests(unittest.IsolatedAsyncioTestCase):
    """BLOCO 1.2 — idempotência server-side na criação de empresa.

    Retry da mesma operação devolve a MESMA empresa; double-click/concorrência
    nunca cria duplicata. Chave é por request (não por e-mail/nome), então
    duas empresas legítimas com o mesmo responsável continuam possíveis.
    """

    def _created(self, *, replay: bool = False):
        return {
            "client": {"id": "company-1", "name": "Acme"},
            "invitation": {"id": "invite-1", "role": "owner"},
            "idempotent_replay": replay,
        }

    async def test_creation_request_id_is_forwarded_to_the_rpc(self):
        rpc = AsyncMock(return_value=self._created())
        with (
            patch.object(platform_admin, "sb_rpc", rpc),
            patch.object(platform_admin, "send_supabase_invite", AsyncMock(return_value=None)),
        ):
            await platform_admin.create_platform_company(
                "master",
                {"name": "Acme", "responsible_email": "owner@acme.test", "idempotency_key": "req-abc"},
            )
        args = rpc.await_args.args[1]
        self.assertEqual(args.get("p_creation_request_id"), "req-abc")
        self.assertEqual(
            set(args),
            {
                "p_actor_user_id",
                "p_name",
                "p_trade_name",
                "p_cnpj",
                "p_responsible_email",
                "p_token_hash",
                "p_expires_at",
                "p_creation_request_id",
            },
        )

    async def test_missing_idempotency_key_is_replaced_by_a_generated_one(self):
        rpc = AsyncMock(return_value=self._created())
        with (
            patch.object(platform_admin, "sb_rpc", rpc),
            patch.object(platform_admin, "send_supabase_invite", AsyncMock(return_value=None)),
        ):
            await platform_admin.create_platform_company(
                "master", {"name": "Acme", "responsible_email": "owner@acme.test"}
            )
        generated = rpc.await_args.args[1].get("p_creation_request_id")
        self.assertTrue(generated)
        self.assertGreaterEqual(len(str(generated)), 16)

    async def test_idempotent_replay_returns_same_company_and_does_not_reinvite(self):
        rpc = AsyncMock(return_value=self._created(replay=True))
        invite = AsyncMock(return_value=None)
        with (
            patch.object(platform_admin, "sb_rpc", rpc),
            patch.object(platform_admin, "send_supabase_invite", invite),
        ):
            result = await platform_admin.create_platform_company(
                "master",
                {"name": "Acme", "responsible_email": "owner@acme.test", "idempotency_key": "req-abc"},
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["company"]["id"], "company-1")
        self.assertIs(result.get("idempotent_replay"), True)
        invite.assert_not_awaited()


class CompanyCreationAuthorityTests(unittest.IsolatedAsyncioTestCase):
    """BLOCO 1.2 — autoridade de criação de empresa = platform_admin.

    A RPC `create_platform_company` (security definer) sempre exigiu
    `is_platform_admin`. O guard Python precisa concordar: agency_admin (sem
    platform_admin) não cria empresa, mas continua com acesso de suporte.
    """

    async def test_agency_admin_without_platform_role_cannot_create_company(self):
        with (
            patch.object(platform_admin, "require_user_id", AsyncMock(return_value="agency-user")),
            patch.object(platform_admin, "is_platform_admin", AsyncMock(return_value=False)),
            patch("services.tenant._has_agency_admin_membership", AsyncMock(return_value=True)),
        ):
            with self.assertRaises(HTTPException) as raised:
                await platform_admin.require_platform_admin("Bearer token", allow_agency_admin=False)
        self.assertEqual(raised.exception.status_code, 403)

    async def test_platform_admin_can_create_company(self):
        with (
            patch.object(platform_admin, "require_user_id", AsyncMock(return_value="master")),
            patch.object(platform_admin, "is_platform_admin", AsyncMock(return_value=True)),
        ):
            self.assertEqual(
                await platform_admin.require_platform_admin("Bearer token", allow_agency_admin=False),
                "master",
            )

    async def test_agency_admin_still_allowed_for_support_endpoints(self):
        with (
            patch.object(platform_admin, "require_user_id", AsyncMock(return_value="agency-user")),
            patch.object(platform_admin, "is_platform_admin", AsyncMock(return_value=False)),
            patch("services.tenant._has_agency_admin_membership", AsyncMock(return_value=True)),
        ):
            self.assertEqual(
                await platform_admin.require_platform_admin("Bearer token"), "agency-user"
            )

    async def test_create_company_route_uses_strict_guard(self):
        with (
            patch.object(routes, "require_platform_admin", AsyncMock(return_value="master")) as guard,
            patch.object(routes, "create_platform_company", AsyncMock(return_value={"ok": True})),
        ):
            await routes.platform_create_company(
                {"name": "Acme", "responsible_email": "a@b.test"}, "Bearer token"
            )
        self.assertEqual(guard.await_args.kwargs.get("allow_agency_admin"), False)


class PermanentCompanyDeletionTests(unittest.IsolatedAsyncioTestCase):
    async def test_service_scopes_rpc_to_path_company_and_confirmation(self):
        rpc = AsyncMock(return_value={
            "deleted_client_id": "tenant-a",
            "deleted_company_name": "Tenant A",
        })
        with patch.object(platform_admin, "sb_rpc", rpc):
            result = await platform_admin.delete_platform_company(
                "master", "tenant-a", "Tenant A"
            )
        self.assertTrue(result["ok"])
        self.assertEqual(rpc.await_args.args[0], "delete_platform_company")
        self.assertEqual(
            rpc.await_args.args[1],
            {
                "p_actor_user_id": "master",
                "p_client_id": "tenant-a",
                "p_confirmation_name": "Tenant A",
            },
        )
        self.assertNotIn("tenant-b", str(rpc.await_args))

    async def test_delete_route_uses_strict_platform_admin_guard(self):
        with (
            patch.object(routes, "require_platform_admin", AsyncMock(return_value="master")) as guard,
            patch.object(
                routes,
                "delete_platform_company",
                AsyncMock(return_value={"ok": True, "deleted_client_id": "tenant-a"}),
            ),
        ):
            await routes.platform_delete_company(
                "tenant-a", {"confirmation_name": "Tenant A"}, "Bearer token", "tenant-b"
            )
        self.assertEqual(guard.await_args.kwargs.get("allow_agency_admin"), False)

    async def test_viewer_client_admin_and_agency_admin_are_denied(self):
        for role in ("viewer", "client_admin", "agency_admin"):
            with self.subTest(role=role):
                with (
                    patch.object(
                        platform_admin, "require_user_id", AsyncMock(return_value=f"{role}-user")
                    ),
                    patch.object(platform_admin, "is_platform_admin", AsyncMock(return_value=False)),
                    patch(
                        "services.tenant._has_agency_admin_membership",
                        AsyncMock(return_value=role == "agency_admin"),
                    ),
                ):
                    with self.assertRaises(HTTPException) as raised:
                        await platform_admin.require_platform_admin(
                            "Bearer token", allow_agency_admin=False
                        )
                self.assertEqual(raised.exception.status_code, 403)

    async def test_missing_company_is_returned_as_404(self):
        with (
            patch.object(routes, "require_platform_admin", AsyncMock(return_value="master")),
            patch.object(
                routes,
                "delete_platform_company",
                AsyncMock(side_effect=platform_admin.PlatformCompanyNotFoundError("Empresa não encontrada.")),
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                await routes.platform_delete_company(
                    "missing", {"confirmation_name": "Missing"}, "Bearer token", "tenant-b"
                )
        self.assertEqual(raised.exception.status_code, 404)

    async def test_currently_open_company_is_rejected_before_rpc(self):
        delete = AsyncMock()
        with (
            patch.object(routes, "require_platform_admin", AsyncMock(return_value="master")),
            patch.object(routes, "delete_platform_company", delete),
        ):
            with self.assertRaises(HTTPException) as raised:
                await routes.platform_delete_company(
                    "tenant-a", {"confirmation_name": "Tenant A"}, "Bearer token", "tenant-a"
                )
        self.assertEqual(raised.exception.status_code, 409)
        delete.assert_not_awaited()


class PermanentCompanyDeletionMigrationContract(unittest.TestCase):
    def setUp(self):
        self.path = (
            Path(__file__).parents[2]
            / "supabase/migrations/20260929_000036_platform_company_permanent_deletion.sql"
        )
        self.sql = self.path.read_text().lower()

    def test_all_mapped_tenant_tables_are_deleted(self):
        mapped_tables = {
            "ad_account_daily_stats", "ad_daily_stats", "ai_analyses", "ai_conversations",
            "ai_messages", "campaign_daily_stats", "client_memberships", "client_notes", "client_users", "clients",
            "connection_audit_events", "cron_job_runs", "cron_locks", "dashboard_campaign_metrics",
            "dashboard_daily_metrics", "dashboard_product_metrics", "dashboard_source_snapshots",
            "fbits_order_daily_stats", "fbits_order_items", "fbits_orders", "ga4_campaign_stats",
            "ga4_channel_stats", "ga4_daily_stats", "ga4_event_stats", "ga4_landing_page_stats",
            "google_ads_daily_stats", "ig_comments", "ig_media", "ig_profile_snapshots",
            "integration_connections", "meta_ads_backfill_jobs", "meta_ads_backfill_slices",
            "meta_connections", "meta_oauth_handoffs", "meta_token_events", "oauth_sessions",
            "platform_audit_events", "promoted_post_daily_stats", "shopify_customers",
            "shopify_order_items", "shopify_orders", "shopify_refunds", "shopify_stores",
            "shopify_webhook_events", "sync_checkpoints", "user_invitations",
        }
        deleted_tables = set(re.findall(r"delete from public\.(\w+)", self.sql))
        self.assertEqual(mapped_tables, deleted_tables)

    def test_tenant_a_deletes_are_scoped_so_tenant_b_is_not_targeted(self):
        direct_deletes = re.findall(
            r"delete from public\.(\w+)\s+where client_id\s*=\s*p_client_id",
            self.sql,
        )
        self.assertGreaterEqual(len(direct_deletes), 40)
        self.assertNotIn("tenant-a", self.sql)
        self.assertNotIn("tenant-b", self.sql)
        self.assertIn("delete from public.clients where id = p_client_id", self.sql)
        self.assertIn(
            "delete from public.client_users where client_id::text = $1",
            self.sql,
        )
        self.assertIn("using p_client_id", self.sql)

    def test_every_delete_has_an_explicit_tenant_scope(self):
        statements = re.findall(
            r"delete from public\.(\w+)(.*?);",
            self.sql,
            flags=re.DOTALL,
        )
        self.assertTrue(statements)
        for table, clause in statements:
            normalized = " ".join(clause.split())
            if table == "meta_ads_backfill_slices":
                self.assertIn(
                    "select id from public.meta_ads_backfill_jobs where client_id = p_client_id",
                    normalized,
                )
            elif table == "clients":
                self.assertIn("where id = p_client_id", normalized)
            elif table == "client_users":
                self.assertIn("where client_id::text = $1", normalized)
                self.assertIn("using p_client_id", normalized)
            else:
                self.assertIn(
                    "where client_id = p_client_id",
                    normalized,
                    msg=f"delete sem escopo de tenant: {table}",
                )

    def test_auth_users_are_preserved_and_company_is_deleted_last(self):
        self.assertNotRegex(self.sql, r"delete\s+from\s+auth\.users")
        self.assertNotRegex(self.sql, r"delete\s+from\s+public\.users")
        company_delete = self.sql.index(
            "delete from public.clients where id = p_client_id"
        )
        delete_positions = [
            match.start()
            for match in re.finditer(r"delete from public\.", self.sql)
            if not self.sql.startswith("delete from public.clients ", match.start())
        ]
        self.assertTrue(delete_positions)
        self.assertLess(max(delete_positions), company_delete)
        self.assertNotIn("delete from", self.sql[company_delete + 1:])

    def test_rpc_is_transactional_platform_admin_only_and_service_role_only(self):
        normalized = " ".join(self.sql.split())
        self.assertIn("is_platform_admin(p_actor_user_id)", self.sql)
        self.assertIn("for update", self.sql)
        self.assertIn("company_name_confirmation_mismatch", self.sql)
        self.assertIn(
            "revoke all on function public.delete_platform_company(uuid,text,text) from public, anon, authenticated;",
            normalized,
        )
        self.assertIn(
            "grant execute on function public.delete_platform_company(uuid,text,text) to service_role;",
            normalized,
        )

    def test_audit_event_contains_no_email_token_or_credential(self):
        audit = self.sql.split("'company_permanently_deleted'", 1)[1]
        self.assertNotIn("email", audit)
        self.assertNotIn("token", audit)
        self.assertNotIn("credential", audit)


class CompanyCreationIdempotencyMigrationContract(unittest.TestCase):
    """BLOCOS 1.2/1.4 — idempotência e overload retrocompatível da RPC."""

    def setUp(self):
        self.path = (
            Path(__file__).parents[2]
            / "supabase/migrations/20260820_000035_company_creation_idempotency.sql"
        )
        self.sql = self.path.read_text().lower()
        matches = re.findall(
            r"create or replace function public\.create_platform_company\s*"
            r"\((.*?)\)\s*returns jsonb\s*language\s+\w+\s*security definer\s*"
            r"set search_path = public\s*as \$\$(.*?)\$\$;",
            self.sql,
            flags=re.DOTALL,
        )
        self.functions = {
            tuple(re.findall(r"\b(p_\w+)\s+(?:uuid|text|timestamptz)\b", signature)): {
                "signature": signature,
                "body": body,
            }
            for signature, body in matches
        }
        self.legacy_args = (
            "p_actor_user_id",
            "p_name",
            "p_trade_name",
            "p_cnpj",
            "p_responsible_email",
            "p_token_hash",
            "p_expires_at",
        )
        self.new_args = (*self.legacy_args, "p_creation_request_id")

    def test_adds_creation_request_id_column_and_unique_index(self):
        self.assertIn("add column if not exists creation_request_id text", self.sql)
        self.assertIn("clients_creation_request_id_uq", self.sql)
        self.assertIn("unique index", self.sql)

    def test_rpc_is_idempotent_and_concurrency_safe(self):
        self.assertIn("p_creation_request_id", self.sql)
        self.assertIn("on conflict (creation_request_id) do nothing", self.sql)
        self.assertIn("idempotent_replay", self.sql)

    def test_rpc_still_requires_platform_admin_and_is_service_role_only(self):
        new_body = self.functions[self.new_args]["body"]
        self.assertIn("is_platform_admin(p_actor_user_id)", new_body)
        self.assertIn("platform_admin_required", new_body)

        normalized = " ".join(self.sql.split())
        for types in (
            "uuid,text,text,text,text,text,timestamptz",
            "uuid,text,text,text,text,text,timestamptz,text",
        ):
            function = f"public.create_platform_company({types})"
            self.assertIn(
                f"revoke all on function {function} from public, anon, authenticated;",
                normalized,
            )
            self.assertIn(
                f"grant execute on function {function} to service_role;",
                normalized,
            )

    def test_has_unambiguous_seven_and_eight_argument_signatures(self):
        self.assertEqual(set(self.functions), {self.legacy_args, self.new_args})
        self.assertNotIn("default", self.functions[self.new_args]["signature"])

    def test_seven_argument_shim_generates_request_id_and_delegates(self):
        shim_body = self.functions[self.legacy_args]["body"]
        self.assertIn("select public.create_platform_company(", shim_body)
        self.assertIn(
            "p_creation_request_id => gen_random_uuid()::text",
            shim_body,
        )
        for statement in ("insert ", "update ", "delete "):
            self.assertNotIn(statement, shim_body)

    def test_migration_is_local_only(self):
        self.assertIn("migration local", self.sql)


class PlatformMigrationContractTests(unittest.TestCase):
    def setUp(self):
        self.sql = (
            Path(__file__).parents[2]
            / "supabase/migrations/20260801_000020_platform_admin_companies.sql"
        ).read_text()

    def test_migration_does_not_hardcode_an_administrator_identity(self):
        lowered = self.sql.lower()
        self.assertNotIn("insert into public.platform_admins", lowered)
        self.assertIn("concedido explicitamente", lowered)

    def test_rls_has_no_self_elevation_write_policy(self):
        lowered = self.sql.lower()
        self.assertIn("enable row level security", lowered)
        self.assertNotIn("platform_admins_insert", lowered)
        self.assertIn("revoke all on public.platform_admins", lowered)

    def test_creation_and_rollback_are_service_role_only(self):
        lowered = self.sql.lower()
        self.assertIn("create_platform_company", lowered)
        self.assertIn("rollback_platform_company_creation", lowered)
        self.assertIn("grant execute", lowered)
        self.assertIn("to service_role", lowered)


if __name__ == "__main__":
    unittest.main()
