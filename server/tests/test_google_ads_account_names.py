from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from services import google_oauth


class GoogleAdsAccountNameEnrichmentTests(unittest.IsolatedAsyncioTestCase):
    async def test_enriches_accounts_with_descriptive_name_from_gaql(self):
        async def fake_customer_info(*, customer_id, **_kwargs):
            if customer_id == "111":
                return {
                    "descriptive_name": "Amalie", "currency_code": "BRL",
                    "time_zone": "America/Sao_Paulo", "is_manager": False, "is_test_account": False,
                }
            return None

        accounts = [{"resource_name": "customers/111", "customer_id": "111"}]
        with patch.object(google_oauth, "_fetch_google_ads_customer_info", fake_customer_info):
            enriched = await google_oauth._enrich_google_ads_account_names(
                accounts, token="t", developer_token="d", api_version="v25",
                login_customer_id=None, request_id="req-1",
            )

        self.assertEqual(enriched[0]["descriptive_name"], "Amalie")
        self.assertEqual(enriched[0]["customer_id"], "111")
        self.assertIn("updated_at", enriched[0])

    async def test_one_account_failing_name_lookup_does_not_break_the_others(self):
        """
        Fallback visual obrigatório: uma conta sem permissão de leitura (ou
        qualquer outra falha na consulta GAQL extra) nunca pode derrubar a
        listagem inteira nem as outras contas — só ela cai para
        customer_id puro.
        """
        async def flaky_customer_info(*, customer_id, **_kwargs):
            if customer_id == "111":
                raise RuntimeError("PERMISSION_DENIED")
            return {
                "descriptive_name": "Roove", "currency_code": "BRL",
                "time_zone": "America/Sao_Paulo", "is_manager": False, "is_test_account": False,
            }

        accounts = [
            {"resource_name": "customers/111", "customer_id": "111"},
            {"resource_name": "customers/222", "customer_id": "222"},
        ]
        with patch.object(google_oauth, "_fetch_google_ads_customer_info", flaky_customer_info):
            enriched = await google_oauth._enrich_google_ads_account_names(
                accounts, token="t", developer_token="d", api_version="v25",
                login_customer_id=None, request_id="req-1",
            )

        self.assertEqual(len(enriched), 2)
        self.assertNotIn("descriptive_name", enriched[0])
        self.assertEqual(enriched[0]["customer_id"], "111")
        self.assertEqual(enriched[1]["descriptive_name"], "Roove")

    async def test_fetch_customer_info_never_raises_on_transport_or_http_failure(self):
        class FailingClient:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return None
            async def post(self, *args, **kwargs):
                raise RuntimeError("boom")

        with patch.object(google_oauth.httpx, "AsyncClient", return_value=FailingClient()):
            result = await google_oauth._fetch_google_ads_customer_info(
                customer_id="111", token="t", developer_token="d",
                api_version="v25", login_customer_id=None,
            )
        self.assertIsNone(result)

    async def test_persist_cache_failure_does_not_raise(self):
        with patch.object(google_oauth, "get_connection", AsyncMock(side_effect=RuntimeError("db down"))):
            # Não deve lançar — apenas registrar e seguir.
            await google_oauth._persist_google_ads_accounts_cache(
                client_id="amalie", connection_id="conn-1", accounts=[{"customer_id": "111"}],
            )


if __name__ == "__main__":
    unittest.main()
