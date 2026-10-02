"""Autorização do fluxo Meta para o Bloco 1 (client_admin gerencia o PRÓPRIO tenant).

Estes testes exercitam os guards REAIS (`require_client_role` / `resolve_client_id`
/ `require_platform_admin`): apenas as folhas de banco (`sb_*`, `is_platform_admin`,
`get_user_id_from_bearer`) e os efeitos colaterais (OAuth settings, discovery,
persistência) são mockados. Nenhum mock finge negar/permitir autorização —
por isso a falha de um mock nunca é lida como evidência de autorização.

Convenção de nomes:
  - Cenários sem prefixo travam comportamento que já é correto hoje e deve
    continuar (agência funciona; cross-tenant negado; viewer sem mutação;
    sem membership negado; handoff de outro tenant recusado).
  - Testes com `EXPECTED_FAIL_BEFORE_FIX` no nome só passam depois de liberar
    `client_admin` nos endpoints necessários. É esse conjunto que prova que
    hoje `client_admin` não tem permissão.
"""

import io
import sys
import unittest
from contextlib import ExitStack, contextmanager, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from fastapi.responses import JSONResponse

SERVER_DIR = str(Path(__file__).parents[1])
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

import api_support  # noqa: E402
from routes import integrations, meta_legacy  # noqa: E402
from services import tenant  # noqa: E402
from services import meta_oauth  # noqa: E402
from services.runtime_cache import invalidate_namespace  # noqa: E402


AMALIE = "amalie"
ROOVE = "roove"


def _base_patches(stack, user_id):
    # Folhas de identidade e a checagem de platform_admin. `services.*` é o
    # pacote sob o qual `tenant.py` resolve seus imports relativos neste
    # ambiente de teste (SERVER_DIR no sys.path).
    p = stack.enter_context
    p(patch.object(tenant, "get_user_id_from_bearer", AsyncMock(return_value=user_id)))
    p(patch.object(api_support, "get_user_id_from_bearer", AsyncMock(return_value=user_id)))
    p(patch("services.platform_admin.is_platform_admin", AsyncMock(return_value=False)))


@contextmanager
def acting_as(user_id, *, role, tenant_id=AMALIE):
    """Ator real: usuário com UMA membership `role` em `tenant_id`.

    Sem papel agency_admin em lugar nenhum e sem platform_admin, de forma que
    os guards seguem exatamente o caminho de membership.
    """
    memberships = [{"client_id": tenant_id, "role": role}]

    async def id_for_user(uid, requested_client_id=None):
        assert uid == user_id
        req = (requested_client_id or "").strip()
        if req and req != tenant_id:
            raise PermissionError("Usuário sem acesso ao client_id informado")
        return tenant_id

    with ExitStack() as stack:
        _base_patches(stack, user_id)
        stack.enter_context(patch.object(tenant, "sb_get_client_memberships", AsyncMock(return_value=memberships)))
        stack.enter_context(patch.object(tenant, "sb_get_client_id_for_user", id_for_user))
        stack.enter_context(patch("services.ig_supabase.sb_select", AsyncMock(return_value=[{"id": tenant_id}])))
        yield


@contextmanager
def acting_as_agency(user_id="agency-user"):
    memberships = [{"client_id": "outra-empresa", "role": "agency_admin"}]
    with ExitStack() as stack:
        _base_patches(stack, user_id)
        stack.enter_context(patch.object(tenant, "sb_get_client_memberships", AsyncMock(return_value=memberships)))
        # branch platform/agency de resolve_client_id valida existência da empresa
        stack.enter_context(patch("services.ig_supabase.sb_select", AsyncMock(return_value=[{"id": ROOVE}])))
        yield


@contextmanager
def acting_as_stranger(user_id="stranger"):
    with ExitStack() as stack:
        _base_patches(stack, user_id)
        stack.enter_context(patch.object(tenant, "sb_get_client_memberships", AsyncMock(return_value=[])))
        stack.enter_context(patch.object(
            tenant, "sb_get_client_id_for_user",
            AsyncMock(side_effect=PermissionError("Usuário sem acesso ao client_id informado")),
        ))
        yield


def _request():
    return SimpleNamespace(state=SimpleNamespace(request_id="test-req"))


_OAUTH_SETTINGS = {
    "app_id": "app", "app_secret": "sec",
    "redirect_uri": "https://api.example/callback", "login_config_id": "cfg",
}


@contextmanager
def _stub_meta_oauth_side_effects():
    with ExitStack() as stack:
        stack.enter_context(patch.object(meta_legacy, "get_meta_oauth_settings", return_value=_OAUTH_SETTINGS))
        stack.enter_context(patch.object(meta_legacy, "create_oauth_state", AsyncMock(return_value="signed-state")))
        stack.enter_context(patch.object(
            meta_legacy, "build_oauth_url",
            return_value={"url": "https://www.facebook.com/dialog/oauth?x=1"},
        ))
        yield


async def _route_status(coro):
    """Executa uma rota; devolve ('raise', code) | ('json', code) | ('ok', value)."""
    try:
        result = await coro
    except HTTPException as exc:
        return "raise", exc.status_code
    if isinstance(result, JSONResponse):
        return "json", result.status_code
    return "ok", result


class _Base(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await invalidate_namespace("client_integrations")
        await invalidate_namespace("integration_connections")


# ---------------------------------------------------------------------------
# Cenário 1 — agency_admin inicia/gerencia Meta para tenant explícito
# ---------------------------------------------------------------------------
class AgencyAdminCanManageMeta(_Base):
    async def test_agency_admin_starts_meta_oauth_for_explicit_tenant(self):
        with ExitStack() as stack:
            stack.enter_context(acting_as_agency())
            stack.enter_context(_stub_meta_oauth_side_effects())
            result = await meta_legacy.api_oauth_meta_start(
                request=_request(), client_id=ROOVE, x_client_id=None, authorization="Bearer valid",
            )
        self.assertEqual(result["client_id"], ROOVE)
        self.assertIn("authorization_url", result)

    async def test_meta_oauth_start_logs_safe_runtime_configuration(self):
        output = io.StringIO()
        with ExitStack() as stack:
            stack.enter_context(acting_as_agency())
            stack.enter_context(_stub_meta_oauth_side_effects())
            with redirect_stdout(output):
                await meta_legacy.api_oauth_meta_start(
                    request=_request(), client_id=ROOVE, x_client_id=None, authorization="Bearer valid",
                )
        logs = output.getvalue()
        self.assertIn(
            "[meta_oauth][config] request_id=test-req client_id=roove app_id=app "
            "login_config_id=cfg redirect_uri=https://api.example/callback response_type=code state_present=1",
            logs,
        )
        self.assertNotIn("app_secret", logs)
        self.assertNotIn("signed-state", logs)

    async def test_meta_provider_denial_logs_callback_signal_without_state_value(self):
        request = SimpleNamespace(
            state=SimpleNamespace(request_id="test-req"),
            query_params={"error_code": "200", "error_subcode": "2018001", "error_reason": "user_denied"},
        )
        output = io.StringIO()
        with redirect_stdout(output):
            response = await meta_legacy.api_oauth_meta_callback(
                request, state="secret-state", error="access_denied", error_description="Denied",
            )
        self.assertEqual(response.status_code, 302)
        logs = output.getvalue()
        self.assertIn("stage=provider_denied error_code=access_denied state_present=1", logs)
        self.assertIn("provider_error_code=200", logs)
        self.assertIn("provider_error_subcode=2018001", logs)
        self.assertIn("provider_error_reason=user_denied", logs)
        self.assertNotIn("secret-state", logs)

    async def test_agency_admin_links_assets_for_explicit_tenant(self):
        save = AsyncMock(return_value={"ok": True, "saved_count": 1})
        with ExitStack() as stack:
            stack.enter_context(acting_as_agency())
            stack.enter_context(patch.object(meta_legacy, "save_connections", save))
            result = await meta_legacy.api_link_assets(
                client_id=ROOVE,
                payload={"handoff": "h", "instagram_ig_user_ids": ["ig-1"], "page_ids": ["page-1"], "ad_account_ids": []},
                authorization="Bearer valid",
            )
        self.assertTrue(result["ok"])
        self.assertEqual(save.await_args.kwargs["client_id"], ROOVE)

    async def test_agency_admin_reads_integrations_contract_for_explicit_tenant(self):
        with ExitStack() as stack:
            stack.enter_context(acting_as_agency())
            stack.enter_context(patch.object(
                integrations, "get_client_connections",
                AsyncMock(return_value={"client_id": ROOVE, "connections": []}),
            ))
            result = await integrations.get_client_integrations(
                client_id=ROOVE, x_client_id=None, authorization="Bearer valid",
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["client_id"], ROOVE)

    async def test_agency_admin_can_enqueue_backfill_for_explicit_tenant(self):
        enqueue = AsyncMock(return_value={"ok": True, "backfill_job_id": "job-1", "client_id": ROOVE})
        with ExitStack() as stack:
            stack.enter_context(acting_as_agency())
            stack.enter_context(patch.object(meta_legacy, "enqueue_backfill", enqueue))
            stack.enter_context(patch.object(meta_legacy, "_validated_connection_id", AsyncMock(return_value="conn-b")))
            resp = await meta_legacy.api_enqueue_meta_ads_backfill(
                payload={"client_id": ROOVE, "connection_id": "conn-b", "since": "2026-01-01", "until": "2026-01-07"},
                authorization="Bearer valid",
            )
        self.assertEqual(getattr(resp, "status_code", 202), 202)
        enqueue.assert_awaited_once()


# ---------------------------------------------------------------------------
# Cenário 2 — client_admin gerencia Meta no PRÓPRIO tenant
# ---------------------------------------------------------------------------
class ClientAdminCanManageOwnTenant(_Base):
    async def test_client_admin_links_assets_in_own_tenant(self):
        # Endpoint sem allowed_roles restrito: já funciona hoje.
        save = AsyncMock(return_value={"ok": True, "saved_count": 1})
        with ExitStack() as stack:
            stack.enter_context(acting_as("admin-amalie", role="client_admin"))
            stack.enter_context(patch.object(meta_legacy, "save_connections", save))
            result = await meta_legacy.api_link_assets(
                client_id=AMALIE,
                payload={"handoff": "h", "instagram_ig_user_ids": ["ig-1"], "page_ids": ["page-1"], "ad_account_ids": []},
                authorization="Bearer valid",
            )
        self.assertTrue(result["ok"])
        self.assertEqual(save.await_args.kwargs["client_id"], AMALIE)

    async def test_client_admin_selects_meta_ads_account_in_own_tenant(self):
        select = AsyncMock(return_value={"connection_id": "c", "ad_account_id": "act_1"})
        with ExitStack() as stack:
            stack.enter_context(acting_as("admin-amalie", role="client_admin"))
            stack.enter_context(patch.object(meta_legacy, "select_paid_connection", select))
            result = await meta_legacy.api_select_meta_ads_account(
                client_id=AMALIE, payload={"ad_account_id": "act_1"}, authorization="Bearer valid",
            )
        self.assertTrue(result["ok"])
        self.assertEqual(select.await_args.kwargs["client_id"], AMALIE)

    async def test_client_admin_disconnects_connection_in_own_tenant(self):
        disc = AsyncMock(return_value={"ok": True})
        with ExitStack() as stack:
            stack.enter_context(acting_as("admin-amalie", role="client_admin"))
            stack.enter_context(patch.object(tenant, "sb_get_connection_for_client", AsyncMock(return_value={"id": "conn-1"})))
            stack.enter_context(patch.object(meta_legacy, "disconnect_connection", disc))
            result = await meta_legacy.api_disconnect_connection(
                client_id=AMALIE, connection_id="conn-1", authorization="Bearer valid",
            )
        self.assertTrue(result["ok"])
        self.assertEqual(disc.await_args.args[0], AMALIE)

    # ---- EXPECTED-FAIL-BEFORE-FIX ---------------------------------------
    async def test_EXPECTED_FAIL_BEFORE_FIX_client_admin_starts_meta_oauth_in_own_tenant(self):
        with ExitStack() as stack:
            stack.enter_context(acting_as("admin-amalie", role="client_admin"))
            stack.enter_context(_stub_meta_oauth_side_effects())
            result = await meta_legacy.api_oauth_meta_start(
                request=_request(), client_id=AMALIE, x_client_id=None, authorization="Bearer valid",
            )
        self.assertEqual(result["client_id"], AMALIE)
        self.assertIn("authorization_url", result)

    async def test_EXPECTED_FAIL_BEFORE_FIX_owner_starts_meta_oauth_in_own_tenant(self):
        with ExitStack() as stack:
            stack.enter_context(acting_as("owner-amalie", role="owner"))
            stack.enter_context(_stub_meta_oauth_side_effects())
            result = await meta_legacy.api_oauth_meta_start(
                request=_request(), client_id=AMALIE, x_client_id=None, authorization="Bearer valid",
            )
        self.assertEqual(result["client_id"], AMALIE)

    async def test_EXPECTED_FAIL_BEFORE_FIX_client_admin_reads_own_integrations_contract(self):
        with ExitStack() as stack:
            stack.enter_context(acting_as("admin-amalie", role="client_admin"))
            stack.enter_context(patch.object(
                integrations, "get_client_connections",
                AsyncMock(return_value={"client_id": AMALIE, "connections": []}),
            ))
            result = await integrations.get_client_integrations(
                client_id=AMALIE, x_client_id=None, authorization="Bearer valid",
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["client_id"], AMALIE)


# ---------------------------------------------------------------------------
# Cenário 3 — client_admin A NÃO consegue operar o tenant B
# ---------------------------------------------------------------------------
class ClientAdminCannotCrossTenant(_Base):
    """Ator: client_admin de `amalie`. Alvo: `roove`."""

    def actor(self):
        return acting_as("admin-amalie", role="client_admin", tenant_id=AMALIE)

    async def test_cannot_start_oauth_for_other_tenant(self):
        with ExitStack() as stack:
            stack.enter_context(self.actor())
            stack.enter_context(_stub_meta_oauth_side_effects())
            with self.assertRaises(HTTPException) as raised:
                await meta_legacy.api_oauth_meta_start(
                    request=_request(), client_id=ROOVE, x_client_id=None, authorization="Bearer valid",
                )
        self.assertEqual(raised.exception.status_code, 403)

    async def test_cannot_select_assets_for_other_tenant(self):
        save = AsyncMock()
        with ExitStack() as stack:
            stack.enter_context(self.actor())
            stack.enter_context(patch.object(meta_legacy, "save_connections", save))
            with self.assertRaises(HTTPException) as raised:
                await meta_legacy.api_link_assets(
                    client_id=ROOVE,
                    payload={"handoff": "h", "instagram_ig_user_ids": ["ig-1"], "page_ids": ["p"], "ad_account_ids": []},
                    authorization="Bearer valid",
                )
        self.assertEqual(raised.exception.status_code, 403)
        save.assert_not_awaited()

    async def test_cannot_change_connection_for_other_tenant(self):
        select = AsyncMock()
        with ExitStack() as stack:
            stack.enter_context(self.actor())
            stack.enter_context(patch.object(meta_legacy, "select_paid_connection", select))
            with self.assertRaises(HTTPException) as raised:
                await meta_legacy.api_select_meta_ads_account(
                    client_id=ROOVE, payload={"ad_account_id": "act_1"}, authorization="Bearer valid",
                )
        self.assertEqual(raised.exception.status_code, 403)
        select.assert_not_awaited()

    async def test_cannot_start_backfill_for_other_tenant(self):
        enqueue = AsyncMock()
        with ExitStack() as stack:
            stack.enter_context(self.actor())
            stack.enter_context(patch.object(meta_legacy, "enqueue_backfill", enqueue))
            with self.assertRaises(HTTPException) as raised:
                await meta_legacy.api_enqueue_meta_ads_backfill(
                    payload={"client_id": ROOVE, "connection_id": "conn-b", "since": "2026-01-01", "until": "2026-01-07"},
                    authorization="Bearer valid",
                )
        self.assertEqual(raised.exception.status_code, 403)
        enqueue.assert_not_awaited()

    async def test_cannot_disconnect_connection_for_other_tenant(self):
        disc = AsyncMock()
        with ExitStack() as stack:
            stack.enter_context(self.actor())
            stack.enter_context(patch.object(tenant, "sb_get_connection_for_client", AsyncMock(return_value=None)))
            stack.enter_context(patch.object(meta_legacy, "disconnect_connection", disc))
            with self.assertRaises(HTTPException) as raised:
                await meta_legacy.api_disconnect_connection(
                    client_id=ROOVE, connection_id="conn-b", authorization="Bearer valid",
                )
        self.assertEqual(raised.exception.status_code, 403)
        disc.assert_not_awaited()

    async def test_cannot_read_other_tenant_private_connections(self):
        with self.actor():
            kind, code = await _route_status(meta_legacy.api_list_connections(
                client_id=ROOVE, authorization="Bearer valid",
            ))
        self.assertEqual(code, 403)

    async def test_cannot_read_other_tenant_meta_connection_status(self):
        with ExitStack() as stack:
            stack.enter_context(self.actor())
            stack.enter_context(patch.object(tenant, "sb_get_connection_for_client", AsyncMock(return_value=None)))
            with self.assertRaises(HTTPException) as raised:
                await meta_legacy.api_meta_connection_status(
                    connection_id="conn-b", client_id=ROOVE, x_client_id=None, authorization="Bearer valid",
                )
        self.assertEqual(raised.exception.status_code, 403)

    async def test_cannot_read_other_tenant_integrations_contract(self):
        with ExitStack() as stack:
            stack.enter_context(self.actor())
            stack.enter_context(patch.object(
                integrations, "get_client_connections",
                AsyncMock(return_value={"client_id": ROOVE, "connections": []}),
            ))
            with self.assertRaises(HTTPException) as raised:
                await integrations.get_client_integrations(
                    client_id=ROOVE, x_client_id=None, authorization="Bearer valid",
                )
        self.assertEqual(raised.exception.status_code, 403)


# ---------------------------------------------------------------------------
# Cenário 4 — viewer: leitura permitida, nunca mutação
# ---------------------------------------------------------------------------
class ViewerIsReadOnly(_Base):
    def actor(self):
        return acting_as("viewer-amalie", role="viewer", tenant_id=AMALIE)

    async def test_viewer_cannot_start_meta_oauth(self):
        with ExitStack() as stack:
            stack.enter_context(self.actor())
            stack.enter_context(_stub_meta_oauth_side_effects())
            with self.assertRaises(HTTPException) as raised:
                await meta_legacy.api_oauth_meta_start(
                    request=_request(), client_id=AMALIE, x_client_id=None, authorization="Bearer valid",
                )
        self.assertEqual(raised.exception.status_code, 403)

    async def test_viewer_cannot_link_assets(self):
        save = AsyncMock()
        with ExitStack() as stack:
            stack.enter_context(self.actor())
            stack.enter_context(patch.object(meta_legacy, "save_connections", save))
            with self.assertRaises(HTTPException) as raised:
                await meta_legacy.api_link_assets(
                    client_id=AMALIE,
                    payload={"handoff": "h", "instagram_ig_user_ids": ["ig"], "page_ids": ["p"], "ad_account_ids": []},
                    authorization="Bearer valid",
                )
        self.assertEqual(raised.exception.status_code, 403)
        save.assert_not_awaited()

    async def test_viewer_cannot_select_meta_ads_account(self):
        select = AsyncMock()
        with ExitStack() as stack:
            stack.enter_context(self.actor())
            stack.enter_context(patch.object(meta_legacy, "select_paid_connection", select))
            with self.assertRaises(HTTPException) as raised:
                await meta_legacy.api_select_meta_ads_account(
                    client_id=AMALIE, payload={"ad_account_id": "act_1"}, authorization="Bearer valid",
                )
        self.assertEqual(raised.exception.status_code, 403)
        select.assert_not_awaited()

    async def test_viewer_cannot_disconnect_connection(self):
        disc = AsyncMock()
        with ExitStack() as stack:
            stack.enter_context(self.actor())
            stack.enter_context(patch.object(tenant, "sb_get_connection_for_client", AsyncMock(return_value={"id": "conn-1"})))
            stack.enter_context(patch.object(meta_legacy, "disconnect_connection", disc))
            with self.assertRaises(HTTPException) as raised:
                await meta_legacy.api_disconnect_connection(
                    client_id=AMALIE, connection_id="conn-1", authorization="Bearer valid",
                )
        self.assertEqual(raised.exception.status_code, 403)
        disc.assert_not_awaited()

    async def test_viewer_can_read_own_connections(self):
        with ExitStack() as stack:
            stack.enter_context(self.actor())
            stack.enter_context(patch.object(meta_legacy, "list_connections", AsyncMock(return_value=[])))
            kind, result = await _route_status(meta_legacy.api_list_connections(
                client_id=AMALIE, authorization="Bearer valid",
            ))
        self.assertEqual(kind, "ok")
        self.assertTrue(result["ok"])
        self.assertEqual(result["client_id"], AMALIE)


# ---------------------------------------------------------------------------
# Cenário 5 — usuário sem membership não opera o tenant
# ---------------------------------------------------------------------------
class NoMembershipCannotOperate(_Base):
    async def test_stranger_cannot_start_meta_oauth(self):
        with ExitStack() as stack:
            stack.enter_context(acting_as_stranger())
            stack.enter_context(_stub_meta_oauth_side_effects())
            with self.assertRaises(HTTPException) as raised:
                await meta_legacy.api_oauth_meta_start(
                    request=_request(), client_id=AMALIE, x_client_id=None, authorization="Bearer valid",
                )
        self.assertEqual(raised.exception.status_code, 403)

    async def test_stranger_cannot_read_connections(self):
        with acting_as_stranger():
            kind, code = await _route_status(meta_legacy.api_list_connections(
                client_id=AMALIE, authorization="Bearer valid",
            ))
        self.assertEqual(code, 403)

    async def test_stranger_cannot_link_assets(self):
        save = AsyncMock()
        with ExitStack() as stack:
            stack.enter_context(acting_as_stranger())
            stack.enter_context(patch.object(meta_legacy, "save_connections", save))
            with self.assertRaises(HTTPException) as raised:
                await meta_legacy.api_link_assets(
                    client_id=AMALIE,
                    payload={"handoff": "h", "instagram_ig_user_ids": ["ig"], "page_ids": ["p"], "ad_account_ids": []},
                    authorization="Bearer valid",
                )
        self.assertEqual(raised.exception.status_code, 403)
        save.assert_not_awaited()


# ---------------------------------------------------------------------------
# Cenário 6 — handoff / state OAuth de outro tenant ou usuário é recusado
# ---------------------------------------------------------------------------
class OAuthHandoffAndStateOwnership(_Base):
    async def test_save_connections_rejects_handoff_bound_to_another_tenant(self):
        # Nível de serviço: mesmo que a rota resolva o tenant `amalie`, o handoff
        # persistido para `roove` é recusado antes de qualquer escrita.
        handoff_row = {
            "handoff": "handoff-roove", "user_id": "admin-amalie", "client_id": ROOVE,
            "encrypted_access_token": "enc", "instagram_accounts_json": [], "ad_accounts_json": [],
            "pages_json": [], "scopes_json": [], "meta_user_json": {},
        }
        insert = AsyncMock()
        update = AsyncMock()
        with ExitStack() as stack:
            stack.enter_context(patch.object(meta_oauth, "_load_handoff_row", AsyncMock(return_value=handoff_row)))
            stack.enter_context(patch.object(meta_oauth, "decrypt_secret", return_value="tok"))
            stack.enter_context(patch.object(meta_oauth, "sb_insert", insert))
            stack.enter_context(patch.object(meta_oauth, "sb_update", update))
            with self.assertRaisesRegex(RuntimeError, "cliente"):
                await meta_oauth.save_connections(
                    user_id="admin-amalie", client_id=AMALIE, handoff="handoff-roove",
                    page_ids=["p"], instagram_ig_user_ids=["ig"], ad_account_ids=[],
                )
        insert.assert_not_awaited()
        update.assert_not_awaited()

    async def test_save_connections_rejects_handoff_bound_to_another_user(self):
        handoff_row = {
            "handoff": "handoff-1", "user_id": "user-amalie", "client_id": AMALIE,
            "encrypted_access_token": "enc", "instagram_accounts_json": [], "ad_accounts_json": [],
            "pages_json": [], "scopes_json": [], "meta_user_json": {},
        }
        with ExitStack() as stack:
            stack.enter_context(patch.object(meta_oauth, "_load_handoff_row", AsyncMock(return_value=handoff_row)))
            stack.enter_context(patch.object(meta_oauth, "decrypt_secret", return_value="tok"))
            with self.assertRaisesRegex(RuntimeError, "usuário"):
                await meta_oauth.save_connections(
                    user_id="intruder", client_id=AMALIE, handoff="handoff-1",
                    page_ids=["p"], instagram_ig_user_ids=["ig"], ad_account_ids=[],
                )

    async def test_discovery_handoff_rejects_mismatched_user(self):
        row = {
            "handoff": "h1", "user_id": "user-amalie", "client_id": AMALIE,
            "instagram_accounts_json": [], "ad_accounts_json": [], "pages_json": [],
            "scopes_json": [], "meta_user_json": {},
        }
        with patch.object(meta_oauth, "_load_handoff_row", AsyncMock(return_value=row)):
            with self.assertRaisesRegex(RuntimeError, "usuário autenticado"):
                await meta_oauth.read_discovery_handoff(handoff="h1", user_id="intruder", client_id=AMALIE)

    async def test_discovery_handoff_rejects_mismatched_client(self):
        row = {
            "handoff": "h1", "user_id": "user-amalie", "client_id": AMALIE,
            "instagram_accounts_json": [], "ad_accounts_json": [], "pages_json": [],
            "scopes_json": [], "meta_user_json": {},
        }
        with patch.object(meta_oauth, "_load_handoff_row", AsyncMock(return_value=row)):
            with self.assertRaisesRegex(RuntimeError, "cliente informado"):
                await meta_oauth.read_discovery_handoff(handoff="h1", user_id="user-amalie", client_id=ROOVE)

    async def test_oauth_callback_state_tenant_is_revalidated_against_membership(self):
        # client_admin de amalie cujo state carrega client_id=roove:
        # require_user_client_access deve recusar (sem poder global).
        with ExitStack() as stack:
            stack.enter_context(patch("server.services.platform_admin.is_platform_admin", AsyncMock(return_value=False)))
            stack.enter_context(patch("services.platform_admin.is_platform_admin", AsyncMock(return_value=False)))
            stack.enter_context(patch.object(
                tenant, "sb_get_client_memberships",
                AsyncMock(return_value=[{"client_id": AMALIE, "role": "client_admin"}]),
            ))
            stack.enter_context(patch.object(
                tenant, "sb_get_client_id_for_user",
                AsyncMock(side_effect=PermissionError("Usuário sem acesso ao client_id informado")),
            ))
            with self.assertRaises(PermissionError):
                await tenant.require_user_client_access("admin-amalie", ROOVE)


if __name__ == "__main__":
    unittest.main()
