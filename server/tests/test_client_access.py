"""Administração de acessos: criar, redefinir senha e remover, por empresa.

Sem rede e sem banco. O que se prova aqui: a senha nunca sai nem é registrada,
papel global não é concedido por payload, a conta é reaproveitada entre
empresas, remover acesso preserva a outra empresa, e uma falha de vínculo não
deixa conta órfã.
"""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from services import client_access
from services.client_access import AccessError

# Valor de fixture, não credencial: existe para provar que a senha não vaza.
PASSWORD = "fixture-senha-nao-real-1"
EMAIL = "pessoa@empresa.com.br"
COMPANY = "empresa-a"
OTHER = "empresa-b"


def auth_user(user_id="user-1", email=EMAIL, name="Pessoa Teste") -> Dict[str, Any]:
    return {
        "id": user_id, "email": email,
        "user_metadata": {"full_name": name},
        "email_confirmed_at": "2026-10-02T12:00:00Z",
        "last_sign_in_at": "2026-10-02T13:00:00Z",
        # Campos que nunca devem chegar à tela.
        "identities": [{"provider": "email", "identity_data": {"sub": "x"}}],
        "app_metadata": {"provider": "email"},
    }


def membership(user_id="user-1", client_id=COMPANY, role="viewer") -> Dict[str, Any]:
    return {
        "id": f"m-{user_id}-{client_id}", "user_id": user_id, "client_id": client_id,
        "role": role, "created_at": "2026-10-01T10:00:00Z",
    }


class AccessHarness(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Quem é platform_admin: consultado ao reaproveitar uma conta, para
        # impedir que esta tela redefina a senha da equipe Mugô.
        self.platform_admins: set[str] = set()
        self.memberships: List[Dict[str, Any]] = []
        self.auth_users: List[Dict[str, Any]] = []
        self.admin_calls: List[Dict[str, Any]] = []
        self.inserts: List[Dict[str, Any]] = []
        self.deletes: List[Dict[str, Any]] = []
        self.insert_fails = False
        self.env = patch.dict(
            "os.environ",
            {"SUPABASE_URL": "https://projeto.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "chave-de-servico"},
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    async def _admin(self, method, path, *, json=None, params=None):
        self.admin_calls.append({"method": method, "path": path, "json": json, "params": params})
        if method == "GET" and path == "/users":
            return {"users": [dict(user) for user in self.auth_users]}
        if method == "POST" and path == "/users":
            created = auth_user(user_id="user-novo", email=(json or {}).get("email"), name=((json or {}).get("user_metadata") or {}).get("full_name") or "")
            self.auth_users.append(created)
            return created
        return {}

    async def _select(self, table, *, select="*", filters=None, order=None, limit=None, offset=None):
        filters = filters or {}
        rows = [dict(row) for row in self.memberships]
        for column, value in filters.items():
            if value.startswith("eq."):
                wanted = value.removeprefix("eq.")
                rows = [row for row in rows if str(row.get(column) or "") == wanted]
        return rows

    async def _insert(self, table, row, returning="representation"):
        self.inserts.append({"table": table, "row": dict(row)})
        if self.insert_fails:
            raise RuntimeError("violacao de constraint")
        self.memberships.append({**row, "id": "m-novo", "created_at": "2026-10-02T18:00:00Z"})
        return {"ok": True}

    async def _delete(self, table, *, filters, returning="representation"):
        self.deletes.append({"table": table, "filters": dict(filters)})
        cid = filters["client_id"].removeprefix("eq.")
        uid = filters["user_id"].removeprefix("eq.")
        self.memberships = [
            row for row in self.memberships
            if not (str(row.get("client_id")) == cid and str(row.get("user_id")) == uid)
        ]
        return []

    async def run_action(self, coroutine_factory):
        output = io.StringIO()
        with (
            patch.object(client_access, "_admin_request", AsyncMock(side_effect=self._admin)),
            patch(
                "services.platform_admin.is_platform_admin",
                AsyncMock(side_effect=lambda uid: str(uid) in self.platform_admins),
            ),
            patch.object(client_access, "sb_select", AsyncMock(side_effect=self._select)),
            patch.object(client_access, "sb_insert", AsyncMock(side_effect=self._insert)),
            patch.object(client_access, "sb_delete", AsyncMock(side_effect=self._delete)),
            redirect_stdout(output),
        ):
            try:
                result, error = await coroutine_factory(), None
            except Exception as exc:  # noqa: BLE001
                result, error = None, exc
        self.log = output.getvalue()
        return result, error

    def create(self, **overrides):
        payload = {
            "client_id": COMPANY, "actor_user_id": "admin-1", "name": "Pessoa Teste",
            "email": EMAIL, "password": PASSWORD, "password_confirmation": PASSWORD,
            "role": "viewer",
        }
        payload.update(overrides)
        return lambda: client_access.create_client_access(**payload)


class CreateAccessTests(AccessHarness):
    async def test_creates_account_and_membership_in_the_company(self):
        result, error = await self.run_action(self.create())
        self.assertIsNone(error)
        self.assertEqual(result["access"]["email"], EMAIL)
        self.assertEqual(result["access"]["role"], "viewer")
        self.assertEqual(result["access"]["role_label"], "Visualizador")
        self.assertTrue(result["access"]["account_created"])
        self.assertEqual(self.inserts[0]["row"], {"user_id": "user-novo", "client_id": COMPANY, "role": "viewer"})

    async def test_email_is_normalized_and_validated(self):
        result, _error = await self.run_action(self.create(email="  PESSOA@Empresa.COM.BR "))
        self.assertEqual(result["access"]["email"], EMAIL)
        for invalid in ("", "sem-arroba", "a@b", "a@b.", "@b.com"):
            with self.subTest(email=invalid):
                _result, error = await self.run_action(self.create(email=invalid))
                self.assertEqual(error.code, "ACCESS_EMAIL_INVALID")

    async def test_password_is_never_returned_logged_or_persisted(self):
        result, _error = await self.run_action(self.create())
        self.assertNotIn(PASSWORD, str(result))
        self.assertNotIn(PASSWORD, self.log)
        # Nem no vínculo, nem em metadata da conta.
        self.assertNotIn(PASSWORD, str(self.inserts))
        created = next(call for call in self.admin_calls if call["method"] == "POST")
        self.assertEqual(created["json"]["password"], PASSWORD)
        self.assertNotIn(PASSWORD, str(created["json"]["user_metadata"]))

    async def test_weak_or_mismatched_password_is_refused(self):
        _result, error = await self.run_action(self.create(password="curta", password_confirmation="curta"))
        self.assertEqual(error.code, "ACCESS_PASSWORD_TOO_SHORT")
        _result, error = await self.run_action(self.create(password_confirmation="fixture-senha-nao-real-2"))
        self.assertEqual(error.code, "ACCESS_PASSWORD_MISMATCH")
        self.assertEqual(self.inserts, [])

    async def test_only_client_roles_are_allowed(self):
        for role in ("viewer", "client_admin"):
            with self.subTest(role=role):
                result, error = await self.run_action(self.create(role=role, email=f"{role}@empresa.com.br"))
                self.assertIsNone(error)
                self.assertEqual(result["access"]["role"], role)

    async def test_role_escalation_by_payload_is_blocked(self):
        for role in ("agency_admin", "platform_admin", "owner", "admin"):
            with self.subTest(role=role):
                _result, error = await self.run_action(self.create(role=role))
                self.assertEqual(error.code, "ACCESS_ROLE_NOT_ALLOWED")
                self.assertEqual(error.status_code, 403)
        self.assertEqual(self.inserts, [])

    async def test_unknown_role_is_refused(self):
        _result, error = await self.run_action(self.create(role="superusuario"))
        self.assertEqual(error.code, "ACCESS_ROLE_INVALID")

    async def test_existing_account_is_reused_for_a_second_company(self):
        self.auth_users = [auth_user()]
        self.memberships = [membership(client_id=OTHER)]
        result, error = await self.run_action(self.create())
        self.assertIsNone(error)
        self.assertFalse(result["access"]["account_created"])
        # Nenhuma conta nova foi criada.
        self.assertFalse(any(call["method"] == "POST" for call in self.admin_calls))
        self.assertEqual(self.inserts[0]["row"]["user_id"], "user-1")
        self.assertEqual({row["client_id"] for row in self.memberships}, {OTHER, COMPANY})

    async def test_duplicated_membership_is_refused(self):
        self.auth_users = [auth_user()]
        self.memberships = [membership(client_id=COMPANY)]
        _result, error = await self.run_action(self.create())
        self.assertEqual(error.code, "ACCESS_ALREADY_EXISTS")
        self.assertEqual(error.status_code, 409)
        self.assertEqual(self.inserts, [])

    async def test_membership_failure_removes_the_account_just_created(self):
        self.insert_fails = True
        _result, error = await self.run_action(self.create())
        self.assertEqual(error.code, "ACCESS_MEMBERSHIP_FAILED")
        # Compensação: a conta recém-criada é apagada, não fica órfã.
        deleted = [call for call in self.admin_calls if call["method"] == "DELETE"]
        self.assertEqual(deleted[0]["path"], "/users/user-novo")

    async def test_membership_failure_never_deletes_a_preexisting_account(self):
        self.auth_users = [auth_user()]
        self.insert_fails = True
        _result, error = await self.run_action(self.create())
        self.assertEqual(error.code, "ACCESS_MEMBERSHIP_FAILED")
        self.assertFalse(any(call["method"] == "DELETE" for call in self.admin_calls))

    async def test_company_is_required(self):
        _result, error = await self.run_action(self.create(client_id=""))
        self.assertEqual(error.code, "ACCESS_CLIENT_REQUIRED")


class ImmediatelyUsableAccessTests(AccessHarness):
    """O acesso criado pelo painel precisa servir no primeiro login.

    Sem convite, sem magic link, sem confirmação pendente.
    """

    def created_call(self) -> Dict[str, Any]:
        return next(call for call in self.admin_calls if call["method"] == "POST")

    def updated_call(self) -> Dict[str, Any]:
        return next(call for call in self.admin_calls if call["method"] == "PUT")

    async def test_a_new_account_is_born_with_the_email_already_confirmed(self):
        _result, error = await self.run_action(self.create())
        self.assertIsNone(error)
        self.assertTrue(self.created_call()["json"]["email_confirm"])

    async def test_a_new_account_is_born_with_the_password_the_admin_typed(self):
        _result, error = await self.run_action(self.create())
        self.assertIsNone(error)
        self.assertEqual(self.created_call()["json"]["password"], PASSWORD)

    async def test_nothing_in_the_flow_sends_an_invitation_or_magic_link(self):
        await self.run_action(self.create())
        for call in self.admin_calls:
            with self.subTest(path=call["path"]):
                for invite in ("invite", "magiclink", "magic_link", "recover", "otp", "generate_link"):
                    self.assertNotIn(invite, call["path"].lower())

    async def test_the_default_profile_for_an_external_client_is_viewer(self):
        result, _error = await self.run_action(self.create())
        self.assertEqual(result["access"]["role"], "viewer")
        self.assertEqual(self.inserts[0]["row"]["role"], "viewer")

    async def test_the_membership_points_at_the_authorized_company(self):
        result, _error = await self.run_action(self.create())
        self.assertEqual(self.inserts[0]["row"]["client_id"], COMPANY)
        self.assertEqual(result["client_id"], COMPANY)

    async def test_the_response_says_the_password_is_valid_now(self):
        result, _error = await self.run_action(self.create())
        self.assertTrue(result["access"]["password_applied"])


class ReusedAccountBecomesUsableTests(AccessHarness):
    """E-mail que já existe no Auth: sem duplicar, mas utilizável agora."""

    def setUp(self):
        super().setUp()
        self.auth_users = [auth_user()]
        self.memberships = [membership(client_id=OTHER)]

    async def test_no_duplicate_auth_user_is_created(self):
        _result, error = await self.run_action(self.create())
        self.assertIsNone(error)
        self.assertFalse(any(call["method"] == "POST" for call in self.admin_calls))

    async def test_the_password_the_admin_typed_is_applied_to_the_existing_account(self):
        _result, error = await self.run_action(self.create())
        self.assertIsNone(error)
        update = next(call for call in self.admin_calls if call["method"] == "PUT")
        self.assertEqual(update["path"], "/users/user-1")
        self.assertEqual(update["json"]["password"], PASSWORD)

    async def test_the_existing_account_has_the_email_confirmed_administratively(self):
        await self.run_action(self.create())
        update = next(call for call in self.admin_calls if call["method"] == "PUT")
        self.assertTrue(update["json"]["email_confirm"])

    async def test_the_existing_name_is_not_overwritten(self):
        await self.run_action(self.create(name="Outro Nome"))
        update = next(call for call in self.admin_calls if call["method"] == "PUT")
        self.assertNotIn("user_metadata", update["json"])

    async def test_the_password_is_applied_only_after_the_membership_succeeds(self):
        # Um vínculo que falha não pode deixar a senha de alguém trocada.
        self.insert_fails = True
        _result, error = await self.run_action(self.create())
        self.assertIsNotNone(error)
        self.assertFalse(any(call["method"] == "PUT" for call in self.admin_calls))

    async def test_the_preexisting_account_is_never_deleted_on_failure(self):
        self.insert_fails = True
        await self.run_action(self.create())
        self.assertFalse(any(call["method"] == "DELETE" for call in self.admin_calls))

    async def test_the_password_never_leaks_in_the_reuse_path(self):
        result, _error = await self.run_action(self.create())
        self.assertNotIn(PASSWORD, str(result))
        self.assertNotIn(PASSWORD, self.log)
        self.assertNotIn(PASSWORD, str(self.inserts))

    async def test_the_other_company_membership_is_untouched(self):
        await self.run_action(self.create())
        self.assertEqual({row["client_id"] for row in self.memberships}, {OTHER, COMPANY})


class TeamAccountsCannotBeTakenOverTests(AccessHarness):
    """Reaproveitar conta não pode virar escalonamento de privilégio.

    Um client_admin que digite o e-mail de alguém da equipe Mugô definiria a
    senha dessa pessoa se o fluxo apenas reaproveitasse a conta.
    """

    def setUp(self):
        super().setUp()
        self.auth_users = [auth_user()]

    async def assert_refused(self) -> None:
        _result, error = await self.run_action(self.create())
        self.assertIsNotNone(error)
        self.assertEqual(error.code, "ACCESS_ROLE_NOT_ALLOWED")
        self.assertEqual(error.status_code, 403)
        self.assertEqual(self.inserts, [])
        self.assertFalse(any(call["method"] == "PUT" for call in self.admin_calls))

    async def test_an_agency_admin_of_another_company_is_refused(self):
        self.memberships = [membership(client_id=OTHER, role="agency_admin")]
        await self.assert_refused()

    async def test_a_platform_admin_is_refused(self):
        self.platform_admins = {"user-1"}
        await self.assert_refused()

    async def test_a_legacy_owner_role_is_refused(self):
        self.memberships = [membership(client_id=OTHER, role="owner")]
        await self.assert_refused()

    async def test_an_ordinary_client_account_is_still_reused(self):
        self.memberships = [membership(client_id=OTHER, role="client_admin")]
        _result, error = await self.run_action(self.create())
        self.assertIsNone(error)
        self.assertTrue(any(call["method"] == "PUT" for call in self.admin_calls))


class ServiceRoleNeverLeavesTheBackendTests(unittest.TestCase):
    def test_the_admin_key_is_read_only_on_the_server(self):
        source = (SERVER_DIR / "services" / "client_access.py").read_text(encoding="utf-8")
        self.assertIn("SUPABASE_SERVICE_ROLE_KEY", source)

    def test_no_response_field_carries_the_admin_key(self):
        source = (SERVER_DIR / "services" / "client_access.py").read_text(encoding="utf-8")
        returns = [line for line in source.splitlines() if "return {" in line or '"ok": True' in line]
        self.assertTrue(returns)
        for line in returns:
            self.assertNotIn("SERVICE_ROLE", line.upper())

    def test_the_frontend_never_mentions_the_service_role(self):
        src = SERVER_DIR.parent / "src"
        for path in src.rglob("*.ts*"):
            body = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertNotIn("SERVICE_ROLE", body.upper())
                self.assertNotIn("service_role", body)

    def test_the_frontend_talks_only_to_the_backend_endpoint(self):
        api = (SERVER_DIR.parent / "src" / "app" / "api.ts").read_text(encoding="utf-8")
        self.assertIn('"/api/client-access"', api)
        # Nada de Admin API do Supabase a partir do browser.
        self.assertNotIn("/auth/v1/admin", api)


class ListAccessTests(AccessHarness):
    async def test_lists_only_this_company_with_sanitized_fields(self):
        self.auth_users = [auth_user(), auth_user(user_id="user-2", email="outro@empresa.com.br", name="Outro")]
        self.memberships = [membership(), membership(user_id="user-2", client_id=OTHER, role="client_admin")]
        result, error = await self.run_action(lambda: client_access.list_client_access(COMPANY))
        self.assertIsNone(error)
        self.assertEqual([item["user_id"] for item in result["items"]], ["user-1"])
        item = result["items"][0]
        self.assertEqual(item["email"], EMAIL)
        self.assertEqual(item["role_label"], "Visualizador")
        self.assertTrue(item["email_confirmed"])
        # Nada de identidade, app_metadata ou token na resposta.
        for forbidden in ("identities", "app_metadata", "identity_data"):
            self.assertNotIn(forbidden, str(result))

    async def test_global_role_is_flagged_not_hidden(self):
        self.auth_users = [auth_user()]
        self.memberships = [membership(role="agency_admin")]
        result, _error = await self.run_action(lambda: client_access.list_client_access(COMPANY))
        self.assertTrue(result["items"][0]["is_global_role"])

    async def test_list_survives_admin_api_unavailable(self):
        self.memberships = [membership()]

        async def failing_admin(method, path, **_kwargs):
            raise AccessError("ACCESS_ADMIN_API_UNAVAILABLE", "fora", status_code=502)

        output = io.StringIO()
        with (
            patch.object(client_access, "_admin_request", AsyncMock(side_effect=failing_admin)),
            patch.object(client_access, "sb_select", AsyncMock(side_effect=self._select)),
            redirect_stdout(output),
        ):
            result = await client_access.list_client_access(COMPANY)
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["role"], "viewer")
        self.assertIsNone(result["items"][0]["email"])


class ResetPasswordTests(AccessHarness):
    def reset(self, **overrides):
        payload = {
            "client_id": COMPANY, "actor_user_id": "admin-1", "user_id": "user-1",
            "password": "fixture-senha-nova-nao-real", "password_confirmation": "fixture-senha-nova-nao-real",
        }
        payload.update(overrides)
        return lambda: client_access.reset_client_access_password(**payload)

    async def test_sets_a_new_password_without_exposing_it(self):
        self.memberships = [membership()]
        result, error = await self.run_action(self.reset())
        self.assertIsNone(error)
        self.assertEqual(result["user_id"], "user-1")
        self.assertNotIn("fixture-senha-nova-nao-real", str(result))
        self.assertNotIn("fixture-senha-nova-nao-real", self.log)
        call = next(c for c in self.admin_calls if c["method"] == "PUT")
        self.assertEqual(call["path"], "/users/user-1")
        self.assertEqual(set(call["json"]), {"password"})

    async def test_cannot_reset_someone_from_another_company(self):
        self.memberships = [membership(client_id=OTHER)]
        _result, error = await self.run_action(self.reset())
        self.assertEqual(error.code, "ACCESS_NOT_FOUND")
        self.assertFalse(any(c["method"] == "PUT" for c in self.admin_calls))

    async def test_cannot_reset_a_global_role_account(self):
        self.memberships = [membership(role="platform_admin")]
        _result, error = await self.run_action(self.reset())
        self.assertEqual(error.code, "ACCESS_ROLE_NOT_ALLOWED")

    async def test_mismatched_confirmation_is_refused(self):
        self.memberships = [membership()]
        _result, error = await self.run_action(self.reset(password_confirmation="fixture-senha-divergente"))
        self.assertEqual(error.code, "ACCESS_PASSWORD_MISMATCH")


class RemoveAccessTests(AccessHarness):
    def remove(self, **overrides):
        payload = {"client_id": COMPANY, "actor_user_id": "admin-1", "user_id": "user-1"}
        payload.update(overrides)
        return lambda: client_access.remove_client_access(**payload)

    async def test_removing_one_company_preserves_the_other(self):
        self.memberships = [membership(client_id=COMPANY), membership(client_id=OTHER)]
        result, error = await self.run_action(self.remove())
        self.assertIsNone(error)
        self.assertTrue(result["account_preserved"])
        self.assertEqual(result["remaining_memberships"], 1)
        self.assertEqual([row["client_id"] for row in self.memberships], [OTHER])
        # A conta Auth nunca é apagada por remoção de acesso.
        self.assertFalse(any(call["method"] == "DELETE" for call in self.admin_calls))

    async def test_delete_is_scoped_to_company_and_user(self):
        self.memberships = [membership()]
        await self.run_action(self.remove())
        self.assertEqual(self.deletes[0]["filters"], {"client_id": f"eq.{COMPANY}", "user_id": "eq.user-1"})

    async def test_cannot_remove_from_another_company(self):
        self.memberships = [membership(client_id=OTHER)]
        _result, error = await self.run_action(self.remove())
        self.assertEqual(error.code, "ACCESS_NOT_FOUND")
        self.assertEqual(self.deletes, [])

    async def test_cannot_remove_a_global_role_account(self):
        self.memberships = [membership(role="agency_admin")]
        _result, error = await self.run_action(self.remove())
        self.assertEqual(error.code, "ACCESS_ROLE_NOT_ALLOWED")
        self.assertEqual(self.deletes, [])


class ConfigurationTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_admin_configuration_is_reported_not_crashed(self):
        with patch.dict("os.environ", {"SUPABASE_URL": "", "SUPABASE_SERVICE_ROLE_KEY": ""}, clear=False):
            with self.assertRaises(AccessError) as ctx:
                await client_access._admin_request("GET", "/users")
        self.assertEqual(ctx.exception.code, "ACCESS_ADMIN_API_NOT_CONFIGURED")
        self.assertEqual(ctx.exception.status_code, 503)


class RouteAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.source = (SERVER_DIR / "routes" / "client_access.py").read_text(encoding="utf-8")

    def test_mutations_require_a_management_role(self):
        # require_client_role recusa viewer e resolve a empresa autorizada.
        self.assertIn("require_client_role(client_id or x_client_id, authorization)", self.source)
        for handler in ("access_create", "access_reset_password", "access_remove"):
            block = self.source[self.source.index(f"async def {handler}"):]
            self.assertIn("_manage_context(", block[:900], handler)

    def test_reading_is_allowed_for_any_member(self):
        block = self.source[self.source.index("async def access_list"):self.source.index("async def access_create")]
        self.assertIn("resolve_client_id(", block)
        self.assertNotIn("_manage_context(", block)

    def test_company_never_comes_from_the_payload(self):
        # client_id aparece como query/header, nunca lido do corpo.
        self.assertNotIn('payload.get("client_id")', self.source)
        self.assertNotIn('payload.get("role_scope")', self.source)


class PasswordSecrecyContractTests(unittest.TestCase):
    def test_service_never_persists_or_logs_the_password(self):
        source = (SERVER_DIR / "services" / "client_access.py").read_text(encoding="utf-8")
        # Nenhum print carrega a senha; nenhum insert/metadata recebe o valor.
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("print(") or "sb_insert(" in stripped:
                self.assertNotIn("secret", stripped, stripped)
                self.assertNotIn("password=", stripped, stripped)
        self.assertIn("_admin_request(\"POST\", \"/users\", json={", source)


if __name__ == "__main__":
    unittest.main()
