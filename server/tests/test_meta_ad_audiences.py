"""Campanhas: públicos que já existem na conta de anúncios do cliente (escolher em vez de escrever)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import io
import json
import unittest
from contextlib import redirect_stdout
from datetime import date
from unittest.mock import AsyncMock, patch

from services import meta_ad_publisher as pub

BASE = {"name": "Black Friday", "objective": "trafego", "daily_budget": 50, "start_date": "2026-11-20", "end_date": "2026-11-30",
        "audience": {"age_min": 25, "age_max": 45, "gender": "mulheres", "regions": [], "interests": ["Perfume"], "advantage": True},
        "ad": {"primary_text": "Seu perfume certo.", "headline": "Oud", "description": "", "cta": "SHOP_NOW",
               "link": "https://roove.com.br", "image_url": "https://cdn/x.jpg"}}
CTX = {"token": "t", "act": "act_123", "page_id": "999", "ig_id": "1784"}


def with_audience(**aud):
    return {**BASE, "audience": {**BASE["audience"], **aud}}


class CleanTests(unittest.TestCase):
    def test_keeps_valid_refs_and_exclusion_wins(self):
        p = pub.clean_payload(with_audience(
            saved_audience={"id": "238500000001", "name": "Mulheres SP 25-45"},
            custom_audiences=[{"id": "238500000002", "name": "Compradores"}, {"id": "238500000003", "name": "Semelhante 1%"},
                              {"id": "abc", "name": "inválido"}, {"id": "238500000002", "name": "repetido"}],
            excluded_audiences=[{"id": "238500000003", "name": "Semelhante 1%"}]), today=date(2026, 11, 10))
        aud = p["audience"]
        self.assertEqual(aud["saved_audience"], {"id": "238500000001", "name": "Mulheres SP 25-45"})
        self.assertEqual(aud["custom_audiences"], [{"id": "238500000002", "name": "Compradores"}])
        self.assertEqual(aud["excluded_audiences"], [{"id": "238500000003", "name": "Semelhante 1%"}])

    def test_old_drafts_have_no_account_audiences(self):
        aud = pub.clean_payload(BASE, today=date(2026, 11, 10))["audience"]
        self.assertEqual((aud["saved_audience"], aud["custom_audiences"], aud["excluded_audiences"]), (None, [], []))

    def test_size_labels(self):
        self.assertEqual(pub.size_label(-1, -1), "menos de 1 mil pessoas")
        self.assertEqual(pub.size_label(12000, 15000), "12 mil a 15 mil pessoas")
        self.assertEqual(pub.size_label(1_200_000, 1_500_000), "1,2 mi a 1,5 mi pessoas")


class ListTests(unittest.IsolatedAsyncioTestCase):
    async def test_lists_custom_lookalike_and_saved(self):
        async def graph(method, path, *, token, data=None, params=None):
            if path.endswith("/customaudiences"):
                return {"data": [
                    {"id": "1", "name": "Visitantes 30d", "subtype": "WEBSITE", "approximate_count_lower_bound": 5000, "approximate_count_upper_bound": 6000},
                    {"id": "2", "name": "Semelhante compradores 1%", "subtype": "LOOKALIKE", "approximate_count_lower_bound": 1_500_000, "approximate_count_upper_bound": 1_800_000},
                    {"id": "3", "name": "Lista pequena", "subtype": "CUSTOM", "approximate_count_lower_bound": -1,
                     "delivery_status": {"code": 300, "description": "Público pequeno demais"}}]}
            if path.endswith("/saved_audiences"):
                return {"data": [{"id": "9", "name": "Mulheres SP", "approximate_count_lower_bound": 800000, "approximate_count_upper_bound": 900000}]}
            raise AssertionError(path)
        with patch.object(pub, "_ad_account", AsyncMock(return_value={"token": "t", "act": "act_123"})), patch.object(pub, "_graph", graph):
            out = await pub.list_account_audiences("roove")
        self.assertEqual([a["name"] for a in out["custom"]], ["Semelhante compradores 1%", "Visitantes 30d", "Lista pequena"])
        self.assertEqual(out["custom"][0]["kind_label"], "Semelhante")
        self.assertFalse(out["custom"][2]["ready"])
        self.assertEqual(out["custom"][2]["status"], "Público pequeno demais")
        self.assertEqual(out["saved"][0]["kind_label"], "Público salvo")

    async def test_saved_audiences_failure_keeps_custom(self):
        async def graph(method, path, *, token, data=None, params=None):
            if path.endswith("/saved_audiences"):
                raise pub.MetaAdError("AD_META_REJECTED", "sem acesso")
            return {"data": [{"id": "1", "name": "Visitantes", "subtype": "WEBSITE"}]}
        with patch.object(pub, "_ad_account", AsyncMock(return_value={"token": "t", "act": "act_123"})), patch.object(pub, "_graph", graph):
            out = await pub.list_account_audiences("roove")
        self.assertEqual((len(out["custom"]), out["saved"]), (1, []))


class PublishTests(unittest.IsolatedAsyncioTestCase):
    async def _publish(self, payload, extra=None):
        row = {"id": "d1", "client_id": "roove", "status": "rascunho", "meta_ids": {}, "payload": payload}
        calls = []

        async def graph(method, path, *, token, data=None, params=None):
            calls.append((method, path, data or {}, params or {}))
            if extra and path in extra:
                return extra[path]
            if path == "/search":
                return {"data": [{"id": "6003", "name": "Perfume"}]}
            if method == "GET":
                return {"data": []}
            return {"id": f"id{len(calls)}"}
        with patch.object(pub, "_draft", AsyncMock(return_value=row)), patch.object(pub, "_context", AsyncMock(return_value=CTX)), \
             patch.object(pub, "_graph", graph), patch.object(pub, "_image_hash", AsyncMock(return_value="h")), \
             patch.object(pub, "sb_update", AsyncMock(return_value=[row])), redirect_stdout(io.StringIO()):
            await pub.publish("roove", "d1")
        adset = next(d for m, p, d, _ in calls if p.endswith("/adsets"))
        return json.loads(adset["targeting"]), calls

    async def test_saved_audience_replaces_written_targeting(self):
        saved = {"geo_locations": {"cities": [{"key": "269969"}]}, "age_min": 30, "age_max": 50, "flexible_spec": [{"interests": [{"id": "77"}]}]}
        targeting, calls = await self._publish(
            with_audience(saved_audience={"id": "238500000009", "name": "Mulheres SP"},
                          custom_audiences=[{"id": "238500000002", "name": "Compradores"}],
                          excluded_audiences=[{"id": "238500000004", "name": "Clientes atuais"}]),
            extra={"/238500000009": {"targeting": saved}})
        self.assertEqual(targeting["geo_locations"], {"cities": [{"key": "269969"}]})
        self.assertEqual(targeting["age_min"], 30)
        self.assertEqual(targeting["custom_audiences"], [{"id": "238500000002"}])
        self.assertEqual(targeting["excluded_custom_audiences"], [{"id": "238500000004"}])
        self.assertFalse(any(p == "/search" for _, p, _, _ in calls))  # não procura interesses escritos

    async def test_custom_audiences_join_written_targeting(self):
        targeting, _ = await self._publish(with_audience(custom_audiences=[{"id": "238500000002", "name": "Semelhante 1%"}]))
        self.assertEqual(targeting["custom_audiences"], [{"id": "238500000002"}])
        self.assertEqual(targeting["flexible_spec"][0]["interests"][0]["id"], "6003")
        self.assertEqual(targeting["genders"], [2])

    async def test_without_choices_targeting_is_unchanged(self):
        targeting, _ = await self._publish(BASE)
        self.assertNotIn("custom_audiences", targeting)
        self.assertNotIn("excluded_custom_audiences", targeting)

    def test_merge_does_not_duplicate_objective_audiences(self):
        t = pub.apply_account_audiences({"custom_audiences": [{"id": "1"}], "excluded_custom_audiences": [{"id": "2"}]},
                                        {"custom_audiences": [{"id": "1", "name": "a"}, {"id": "3", "name": "b"}],
                                         "excluded_audiences": [{"id": "2", "name": "c"}, {"id": "3", "name": "b"}]})
        self.assertEqual(t["custom_audiences"], [{"id": "1"}])
        self.assertEqual(t["excluded_custom_audiences"], [{"id": "2"}, {"id": "3"}])


if __name__ == "__main__":
    unittest.main()
