"""Publicacao Google SEARCH: validacao, atomicidade, idempotencia e tenant guard."""
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException
from routes import google_ads_drafts as routes
from services import google_ad_publisher as publisher
from services import team_access
from services.studio_calendar import StudioError


PAYLOAD = {
    "platform": "google_ads", "name": "Search Alto Verao", "objective": "vendas", "type": "SEARCH",
    "daily_budget": 50, "start_date": "2099-11-20", "end_date": "2099-11-30",
    "final_url": "https://example.com/colecao", "locations": ["Sao Paulo"],
    "keywords": ["alfaiataria de luxo"],
    "headlines": ["Alfaiataria Autoral", "Conheca a Colecao", "Maison Valenne"],
    "descriptions": ["Descubra pecas autorais para o alto verao.", "Agende sua visita privada."],
    "contains_eu_political_advertising": False,
    "notes": "",
}
ROW = {"id": "11111111-1111-4111-8111-111111111111", "client_id": "tenant-a", "status": "rascunho", "payload": PAYLOAD}
CONTEXT = SimpleNamespace(connection_id="conn-a", customer_id="1234567890", login_customer_id=None)


def response(status: int, body: dict) -> httpx.Response:
    return httpx.Response(status, json=body, request=httpx.Request("POST", "https://google.test"))


class FakeHttp:
    calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, url, *, headers, json):
        self.calls.append((url, headers, json))
        if url.endswith("geoTargetConstants:suggest"):
            return response(200, {"geoTargetConstantSuggestions": [{"geoTargetConstant": {"resourceName": "geoTargetConstants/20123"}}]})
        if json["validateOnly"]:
            return response(200, {})
        return response(200, {"mutateOperationResponses": [
            {"campaignBudgetResult": {"resourceName": "customers/1234567890/campaignBudgets/10"}},
            {"campaignResult": {"resourceName": "customers/1234567890/campaigns/20"}},
            {"adGroupResult": {"resourceName": "customers/1234567890/adGroups/30"}},
            {"adGroupAdResult": {"resourceName": "customers/1234567890/adGroupAds/30~40"}},
        ]})


class TimeoutOnMutate(FakeHttp):
    async def post(self, url, *, headers, json):
        if url.endswith("googleAds:mutate") and not json["validateOnly"]:
            raise httpx.ReadTimeout("timeout", request=httpx.Request("POST", url))
        return await super().post(url, headers=headers, json=json)


class PublishTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        FakeHttp.calls = []

    async def test_validates_then_creates_one_atomic_paused_search_campaign(self):
        updates = AsyncMock(side_effect=[[ROW], [{**ROW, "status": "publicada", "meta_ids": {"campaign_id": "20", "customer_id": "1234567890"}}]])
        with patch.object(publisher.drafts, "owned", AsyncMock(return_value=ROW)), \
             patch.object(publisher, "resolve_google_ads_context", AsyncMock(return_value=CONTEXT)), \
             patch.object(publisher, "get_google_access_token", AsyncMock(return_value="access-token")), \
             patch.object(publisher, "sb_update", updates), \
             patch.object(publisher.httpx, "AsyncClient", return_value=FakeHttp()), \
             redirect_stdout(io.StringIO()):
            result = await publisher.publish("tenant-a", ROW["id"])

        mutate = [call for call in FakeHttp.calls if call[0].endswith("googleAds:mutate")]
        self.assertEqual([call[2]["validateOnly"] for call in mutate], [True, False])
        for call in mutate:
            operations = call[2]["mutateOperations"]
            self.assertFalse(call[2]["partialFailure"])
            self.assertEqual(operations[1]["campaignOperation"]["create"]["status"], "PAUSED")
            self.assertEqual(operations[1]["campaignOperation"]["create"]["containsEuPoliticalAdvertising"], "DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING")
            self.assertEqual(operations[2]["adGroupOperation"]["create"]["status"], "PAUSED")
            self.assertEqual(operations[-1]["adGroupAdOperation"]["create"]["status"], "PAUSED")
        claim = updates.await_args_list[0].kwargs
        self.assertEqual(claim["filters"]["status"], "in.(rascunho,erro)")
        self.assertEqual(result["status"], "publicada")

    async def test_failed_atomic_claim_blocks_duplicate_without_google_call(self):
        with patch.object(publisher.drafts, "owned", AsyncMock(return_value=ROW)), \
             patch.object(publisher, "resolve_google_ads_context", AsyncMock(return_value=CONTEXT)), \
             patch.object(publisher, "sb_update", AsyncMock(return_value=[])), \
             patch.object(publisher, "get_google_access_token", AsyncMock()) as token:
            with self.assertRaises(StudioError) as raised:
                await publisher.publish("tenant-a", ROW["id"])
        self.assertEqual(raised.exception.code, "AD_PUBLICATION_IN_PROGRESS")
        token.assert_not_awaited()

    async def test_incomplete_payload_is_refused_before_oauth_or_database_claim(self):
        bad = {**ROW, "payload": {**PAYLOAD, "headlines": ["Somente um"]}}
        with patch.object(publisher.drafts, "owned", AsyncMock(return_value=bad)), \
             patch.object(publisher, "resolve_google_ads_context", AsyncMock()) as context:
            with self.assertRaises(StudioError) as raised:
                await publisher.publish("tenant-a", ROW["id"])
        self.assertEqual(raised.exception.code, "AD_NOT_READY")
        context.assert_not_awaited()

    async def test_ambiguous_mutate_timeout_stays_locked_against_retry(self):
        updates = AsyncMock(side_effect=[[ROW], [ROW]])
        with patch.object(publisher.drafts, "owned", AsyncMock(return_value=ROW)), \
             patch.object(publisher, "resolve_google_ads_context", AsyncMock(return_value=CONTEXT)), \
             patch.object(publisher, "get_google_access_token", AsyncMock(return_value="access-token")), \
             patch.object(publisher, "sb_update", updates), \
             patch.object(publisher.httpx, "AsyncClient", return_value=TimeoutOnMutate()):
            with self.assertRaises(StudioError) as raised:
                await publisher.publish("tenant-a", ROW["id"])
        self.assertEqual(raised.exception.code, "AD_PUBLICATION_UNCERTAIN")
        failure = updates.await_args_list[-1].kwargs["patch"]
        self.assertEqual(failure["status"], "publicando")
        self.assertIn("AD_PUBLICATION_UNCERTAIN", failure["error"])

    async def test_route_denies_before_privileged_operation(self):
        denied = HTTPException(status_code=403, detail="denied")
        with patch.object(routes, "require_client_role", AsyncMock(side_effect=denied)), \
             patch.object(routes.publisher, "publish", AsyncMock()) as publish:
            with self.assertRaises(HTTPException) as raised:
                await routes.publish_campaign("tenant-b", ROW["id"], "Bearer user")
        self.assertEqual(raised.exception.status_code, 403)
        publish.assert_not_awaited()

    async def test_client_admin_is_an_explicit_writer_role(self):
        self.assertIn("client_admin", routes.WRITERS)
        self.assertEqual(
            team_access.route_module("POST", "/api/clients/tenant-a/studio/google-ads/draft/publish"),
            ("media", "media.edit"),
        )
