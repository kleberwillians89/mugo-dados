"""Bloco 1.1 — hardening de dois defeitos pré-existentes em routes/meta_legacy.py.

1. `api_link_assets` referencia `IntegrationError` sem importar: quando
   `save_connections` levanta um `RuntimeError` de isolamento (handoff de outro
   tenant), o `except IntegrationError:` estoura `NameError` -> 500 não
   controlado. Esperado: erro 400 controlado, sem nenhuma escrita.

2. `POST /api/meta/connections/{id}/refresh-token` é uma mutação (renova e
   persiste token) mas hoje só passa por `resolve_client_id` (nível leitura),
   deixando `viewer` disparar. Esperado: guard de mutação
   (`require_client_role`) — viewer negado, client_admin só no próprio tenant.

Os guards são exercitados de verdade; apenas folhas de banco e efeitos
colaterais são mockados.
"""

import sys
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

SERVER_DIR = str(Path(__file__).parents[1])
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

import api_support  # noqa: E402
from routes import meta_legacy  # noqa: E402
from services import meta_oauth, tenant  # noqa: E402
from services.runtime_cache import invalidate_namespace  # noqa: E402

AMALIE = "amalie"
ROOVE = "roove"


@contextmanager
def acting_as(user_id, *, role, tenant_id=AMALIE):
    """Usuário real com UMA membership `role` em `tenant_id` (sem agency/platform)."""
    memberships = [{"client_id": tenant_id, "role": role}]

    async def id_for_user(uid, requested_client_id=None):
        assert uid == user_id
        req = (requested_client_id or "").strip()
        if req and req != tenant_id:
            raise PermissionError("Usuário sem acesso ao client_id informado")
        return tenant_id

    with ExitStack() as stack:
        p = stack.enter_context
        p(patch.object(tenant, "get_user_id_from_bearer", AsyncMock(return_value=user_id)))
        p(patch.object(api_support, "get_user_id_from_bearer", AsyncMock(return_value=user_id)))
        p(patch("services.platform_admin.is_platform_admin", AsyncMock(return_value=False)))
        p(patch.object(tenant, "sb_get_client_memberships", AsyncMock(return_value=memberships)))
        p(patch.object(tenant, "sb_get_client_id_for_user", id_for_user))
        p(patch("services.ig_supabase.sb_select", AsyncMock(return_value=[{"id": tenant_id}])))
        yield


@contextmanager
def acting_as_agency(user_id="agency-user"):
    memberships = [{"client_id": "outra-empresa", "role": "agency_admin"}]
    with ExitStack() as stack:
        p = stack.enter_context
        p(patch.object(tenant, "get_user_id_from_bearer", AsyncMock(return_value=user_id)))
        p(patch.object(api_support, "get_user_id_from_bearer", AsyncMock(return_value=user_id)))
        p(patch("services.platform_admin.is_platform_admin", AsyncMock(return_value=False)))
        p(patch.object(tenant, "sb_get_client_memberships", AsyncMock(return_value=memberships)))
        p(patch("services.ig_supabase.sb_select", AsyncMock(return_value=[{"id": ROOVE}])))
        yield


class _Base(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await invalidate_namespace("client_integrations")
        await invalidate_namespace("integration_connections")


# ---------------------------------------------------------------------------
# Defeito 1 — IntegrationError sem import em api_link_assets
# ---------------------------------------------------------------------------
class LinkAssetsIntegrationErrorImport(_Base):
    async def test_cross_tenant_handoff_returns_controlled_400_without_writes(self):
        """client_admin de amalie (autorizado no tenant) + handoff de roove:
        `save_connections` levanta RuntimeError de isolamento; a rota deve
        devolver HTTPException 400 controlada e não escrever nada."""
        handoff_row = {
            "handoff": "handoff-roove", "user_id": "admin-amalie", "client_id": ROOVE,
            "encrypted_access_token": "enc", "instagram_accounts_json": [],
            "ad_accounts_json": [], "pages_json": [], "scopes_json": [], "meta_user_json": {},
        }
        insert = AsyncMock()
        update = AsyncMock()
        with ExitStack() as stack:
            stack.enter_context(acting_as("admin-amalie", role="client_admin", tenant_id=AMALIE))
            stack.enter_context(patch.object(meta_oauth, "_load_handoff_row", AsyncMock(return_value=handoff_row)))
            stack.enter_context(patch.object(meta_oauth, "decrypt_secret", return_value="tok"))
            stack.enter_context(patch.object(meta_oauth, "sb_insert", insert))
            stack.enter_context(patch.object(meta_oauth, "sb_update", update))
            with self.assertRaises(HTTPException) as raised:
                await meta_legacy.api_link_assets(
                    client_id=AMALIE,
                    payload={
                        "handoff": "handoff-roove",
                        "instagram_ig_user_ids": ["ig"], "page_ids": ["p"], "ad_account_ids": [],
                    },
                    authorization="Bearer valid",
                )
        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("cliente", str(raised.exception.detail).lower())
        insert.assert_not_awaited()
        update.assert_not_awaited()

    async def test_integration_error_is_importable_in_meta_legacy(self):
        """Garante que o símbolo referenciado no except existe no módulo."""
        self.assertTrue(hasattr(meta_legacy, "IntegrationError"))
        from services.integration_errors import IntegrationError as canonical
        self.assertIs(meta_legacy.IntegrationError, canonical)


# ---------------------------------------------------------------------------
# Defeito 2 — refresh-token é mutação e precisa de guard de mutação
# ---------------------------------------------------------------------------
class RefreshTokenRequiresMutationGuard(_Base):
    @contextmanager
    def _no_side_effects(self):
        with ExitStack() as stack:
            self.start_job = stack.enter_context(
                patch.object(meta_legacy, "start_job_run", AsyncMock(return_value={"id": "run-1"}))
            )
            self.finish_job = stack.enter_context(patch.object(meta_legacy, "finish_job_run", AsyncMock()))
            self.refresh = stack.enter_context(
                patch.object(
                    meta_legacy, "refresh_meta_token_for_connection",
                    AsyncMock(return_value={"ok": True, "connection": {"id": "conn-1"}}),
                )
            )
            yield

    async def test_viewer_cannot_trigger_refresh(self):
        with ExitStack() as stack:
            stack.enter_context(acting_as("viewer-amalie", role="viewer", tenant_id=AMALIE))
            stack.enter_context(patch.object(tenant, "sb_get_connection_for_client", AsyncMock(return_value={"id": "conn-1"})))
            stack.enter_context(self._no_side_effects())
            with self.assertRaises(HTTPException) as raised:
                await meta_legacy.api_meta_connection_refresh_token(
                    connection_id="conn-1", client_id=AMALIE, x_client_id=None, authorization="Bearer valid",
                )
        self.assertEqual(raised.exception.status_code, 403)
        self.refresh.assert_not_awaited()
        self.start_job.assert_not_awaited()

    async def test_client_admin_can_trigger_refresh_in_own_tenant(self):
        with ExitStack() as stack:
            stack.enter_context(acting_as("admin-amalie", role="client_admin", tenant_id=AMALIE))
            stack.enter_context(patch.object(tenant, "sb_get_connection_for_client", AsyncMock(return_value={"id": "conn-1"})))
            stack.enter_context(self._no_side_effects())
            result = await meta_legacy.api_meta_connection_refresh_token(
                connection_id="conn-1", client_id=AMALIE, x_client_id=None, authorization="Bearer valid",
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["job_run_id"], "run-1")
        self.refresh.assert_awaited_once()

    async def test_client_admin_cannot_trigger_refresh_for_other_tenant(self):
        with ExitStack() as stack:
            stack.enter_context(acting_as("admin-amalie", role="client_admin", tenant_id=AMALIE))
            stack.enter_context(patch.object(tenant, "sb_get_connection_for_client", AsyncMock(return_value=None)))
            stack.enter_context(self._no_side_effects())
            with self.assertRaises(HTTPException) as raised:
                await meta_legacy.api_meta_connection_refresh_token(
                    connection_id="conn-b", client_id=ROOVE, x_client_id=None, authorization="Bearer valid",
                )
        self.assertEqual(raised.exception.status_code, 403)
        self.refresh.assert_not_awaited()
        self.start_job.assert_not_awaited()

    async def test_agency_admin_can_trigger_refresh_for_explicit_tenant(self):
        with ExitStack() as stack:
            stack.enter_context(acting_as_agency())
            stack.enter_context(patch.object(tenant, "sb_get_connection_for_client", AsyncMock(return_value={"id": "conn-b"})))
            stack.enter_context(self._no_side_effects())
            result = await meta_legacy.api_meta_connection_refresh_token(
                connection_id="conn-b", client_id=ROOVE, x_client_id=None, authorization="Bearer valid",
            )
        self.assertTrue(result["ok"])
        self.refresh.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
