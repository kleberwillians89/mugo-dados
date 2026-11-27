"""Mídia On: visão geral deve incluir arquivadas sem alterar o seletor antigo."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json
import unittest
from unittest.mock import AsyncMock, patch

from services import meta_ad_publisher as pub


class MetaOverviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_overview_includes_archived_and_paginates_per_tenant(self):
        requests = []

        async def graph(method, path, *, token, params):
            requests.append((path, dict(params)))
            if path.endswith("/ads"):
                return {"data": [{"id": "ad1", "effective_status": "ADSET_PAUSED"}]}
            if params.get("after") == "cursor2":
                return {"data": [{"id": "2", "name": "Campanha encerrada", "effective_status": "ARCHIVED",
                                 "stop_time": "2026-11-01T00:00:00-0300"}]}
            return {"data": [{"id": "1", "name": "Campanha ativa", "effective_status": "ACTIVE"}],
                    "paging": {"cursors": {"after": "cursor2"}, "next": "has-more"}}

        with patch.object(pub, "_ad_account", AsyncMock(return_value={"act": "act_ruah", "token": "secret"})), \
             patch.object(pub, "_imported_ids", AsyncMock(return_value=set())), \
             patch.object(pub, "_graph", graph):
            campaigns = await pub.list_meta_campaigns("ruah", include_finished=True)

        self.assertEqual([item["id"] for item in campaigns], ["1", "2"])
        self.assertEqual(campaigns[1]["stop_time"], "2026-11-01T00:00:00-0300")
        self.assertTrue(all(path == "/act_ruah/campaigns" for path, _ in requests[:2]))
        self.assertEqual(campaigns[0]["status"], "PAUSED")
        self.assertIn("ARCHIVED", json.loads(requests[0][1]["effective_status"]))
        self.assertEqual(requests[1][1]["after"], "cursor2")

    async def test_only_active_ad_makes_campaign_eligible(self):
        async def graph(method, path, *, token, params):
            if path.endswith("/ads"):
                return {"data": [{"id": "ad1", "effective_status": "ACTIVE"}]}
            return {"data": [{"id": "camp1", "name": "Campanha ativa", "effective_status": "ACTIVE"}]}

        with patch.object(pub, "_ad_account", AsyncMock(return_value={"act": "act_ruah", "token": "secret"})), \
             patch.object(pub, "_imported_ids", AsyncMock(return_value=set())), \
             patch.object(pub, "_graph", graph):
            campaigns = await pub.list_meta_campaigns("ruah", include_finished=True)
        self.assertEqual(campaigns[0]["status"], "ACTIVE")
        self.assertTrue(campaigns[0]["delivery_checked"])

    async def test_failed_ad_check_must_not_claim_active(self):
        async def graph(method, path, *, token, params):
            if path.endswith("/ads"):
                raise pub.StudioError("AD_PERMISSION_MISSING")
            return {"data": [{"id": "camp1", "name": "Ativa sem verificação", "effective_status": "ACTIVE"}]}

        with patch.object(pub, "_ad_account", AsyncMock(return_value={"act": "act_ruah", "token": "secret"})), \
             patch.object(pub, "_imported_ids", AsyncMock(return_value=set())), \
             patch.object(pub, "_graph", graph):
            campaigns = await pub.list_meta_campaigns("ruah", include_finished=True)
        self.assertEqual(campaigns[0]["status"], "UNKNOWN")
        self.assertFalse(campaigns[0]["delivery_checked"])

    async def test_no_ads_does_not_claim_active(self):
        graph = AsyncMock(side_effect=[
            {"data": [{"id": "camp1", "name": "Sem anúncios", "effective_status": "ACTIVE"}]},
            {"data": []},
        ])
        with patch.object(pub, "_ad_account", AsyncMock(return_value={"act": "act_ruah", "token": "secret"})), \
             patch.object(pub, "_imported_ids", AsyncMock(return_value=set())), \
             patch.object(pub, "_graph", graph):
            campaigns = await pub.list_meta_campaigns("ruah", include_finished=True)
        self.assertEqual(campaigns[0]["status"], "NO_ACTIVE_AD")

    async def test_existing_import_picker_keeps_default_behavior(self):
        graph = AsyncMock(return_value={"data": []})
        with patch.object(pub, "_ad_account", AsyncMock(return_value={"act": "act_ruah", "token": "secret"})), \
             patch.object(pub, "_imported_ids", AsyncMock(return_value=set())), \
             patch.object(pub, "_graph", graph):
            await pub.list_meta_campaigns("ruah")

        self.assertNotIn("ARCHIVED", json.loads(graph.await_args.kwargs["params"]["effective_status"]))
        self.assertEqual(graph.await_count, 1)


if __name__ == "__main__":
    unittest.main()
