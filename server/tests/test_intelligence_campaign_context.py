"""Persisted campaign grounding and updated business context, with all IO mocked."""
import copy
import io
import sys
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import intelligence as service

START = date(2026, 1, 1)
END = date(2026, 1, 2)


def row(**changes):
    return {"client_id": "tenant-a", "ad_account_id": "account-a", "campaign_id": "campaign-a",
            "campaign_name": "Campanha persistida", "stat_date": "2026-01-01", "spend": 100,
            "revenue": 200, "conversions": 2, **changes}


def content(metric_id, source_id):
    return {"executive": {"overall": "Acompanhe a campanha observada.", "main_change": "Investimento observado.",
            "opportunity": "", "attention": "", "priority_action": "Revisar a campanha."},
            "insights": [{"category": "attention", "title": "Campanha persistida", "interpretation": "Investimento observado.",
                "metric_ids": [metric_id], "sources": [source_id], "impact": "medium", "confidence": "medium",
                "action": "Revisar a campanha.", "reason": "Evidência persistida."}],
            "actions": [{"priority": "investigate", "recommendation": "Revisar a campanha.", "justification": "Investimento observado.",
                "sources": [source_id], "impact_expected": "Hipótese a verificar", "confidence": "medium", "metric_id": metric_id}]}


class CampaignContextTests(unittest.IsolatedAsyncioTestCase):
    async def collect(self, rows, **kwargs):
        select = AsyncMock(return_value=rows)
        with patch.object(service, "sb_select", select):
            result = await service._campaign_analysis_context("tenant-a", START, END, **kwargs)
        return result, select

    async def test_campaigns_are_scoped_by_tenant_period_and_account_even_with_same_names(self):
        result, select = await self.collect([row(), row(stat_date="2026-01-02"),
            row(ad_account_id="account-b"), row(client_id="tenant-b", spend=9000),
            row(stat_date="2026-01-03", spend=9000), row(ad_account_id="")])
        self.assertEqual(len(result["items"]), 2)
        self.assertEqual([item["spend"] for item in result["items"]], [200, 100])
        self.assertNotEqual(result["items"][0]["source_id"], result["items"][1]["source_id"])
        self.assertEqual(result["items"][0]["status"], "available")
        self.assertEqual(result["items"][1]["status"], "partial")
        kwargs = select.await_args.kwargs
        self.assertEqual(kwargs["filters"]["client_id"], "eq.tenant-a")
        self.assertEqual(kwargs["filters"]["and"], "(stat_date.gte.2026-01-01,stat_date.lte.2026-01-02)")
        self.assertNotIn("raw_json", kwargs["select"])

    async def test_pagination_cap_and_sentinel_never_publish_full_period_totals(self):
        pages = [[row()], [row(stat_date="2026-01-02")], [row()]]
        with patch.object(service, "CAMPAIGN_PAGE_SIZE", 1), patch.object(service, "CAMPAIGN_ROW_LIMIT", 2), \
             patch.object(service, "sb_select", AsyncMock(side_effect=pages)) as select:
            result = await service._campaign_analysis_context("tenant-a", START, END)
        self.assertEqual(select.await_count, 3)
        self.assertEqual([call.kwargs["offset"] for call in select.await_args_list], [0, 1, 2])
        self.assertEqual(result["items"][0]["spend"], 200)
        self.assertTrue(result["items"][0]["truncated"])
        self.assertTrue(all(metric["status"] == "partial" for metric in result["metrics"]))

    async def test_read_failure_discards_all_partial_pages(self):
        with patch.object(service, "CAMPAIGN_PAGE_SIZE", 1), \
             patch.object(service, "sb_select", AsyncMock(side_effect=[[row()], RuntimeError("fixture")])):
            result = await service._campaign_analysis_context("tenant-a", START, END)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["items"], [])
        self.assertEqual(result["metrics"], [])

    async def test_missing_values_are_not_zero_and_top_campaigns_are_bounded(self):
        result, _ = await self.collect([row(campaign_id=str(i), revenue=None, conversions=None) for i in range(10)])
        self.assertEqual(len(result["items"]), 5)
        self.assertEqual(len(result["metrics"]), 20)
        self.assertIsNone(result["items"][0]["revenue"])
        self.assertIsNone(result["items"][0]["roas"])
        unavailable = [metric for metric in result["metrics"] if metric["id"].endswith("_revenue")]
        self.assertTrue(all(metric["status"] == "unavailable" for metric in unavailable))

    async def test_campaign_grounding_rejects_wrong_source_and_incompatible_crossings(self):
        campaigns, _ = await self.collect([row()])
        item = campaigns["items"][0]
        metric_id, source_id = item["metric_ids"][0], item["source_id"]
        snapshot = {"period": {"start": START.isoformat(), "end": END.isoformat()},
                    "metrics": campaigns["metrics"] + [{"id": "revenue", "value": 300, "source": "commerce", "status": "confirmed"}],
                    "sources": campaigns["sources"] + [{"id": "commerce", "status": "available", "data_max_available": "2026-01-02"}]}
        valid = content(metric_id, source_id)
        service._validate_analysis_grounding(valid, snapshot, policy={"includes_partial_today": False})
        wrong = copy.deepcopy(valid); wrong["insights"][0]["sources"] = ["commerce"]
        with self.assertRaisesRegex(RuntimeError, "AI_UNGROUNDED_INSIGHT"):
            service._validate_analysis_grounding(wrong, snapshot, policy={"includes_partial_today": False})
        wrong = copy.deepcopy(valid); wrong["actions"][0]["sources"] = ["commerce"]
        with self.assertRaisesRegex(RuntimeError, "AI_UNGROUNDED_ACTION"):
            service._validate_analysis_grounding(wrong, snapshot, policy={"includes_partial_today": False})
        cross = copy.deepcopy(valid); cross["insights"][0].update(metric_ids=[metric_id, "revenue"], sources=[source_id, "commerce"])
        with self.assertRaisesRegex(RuntimeError, "AI_TEMPORALLY_INCOMPATIBLE_SOURCES"), redirect_stdout(io.StringIO()):
            service._validate_analysis_grounding(cross, snapshot, policy={"includes_partial_today": False})

    async def test_live_snapshot_and_generation_receive_campaigns_and_fresh_tenant_context(self):
        business = {"available": True, "context": {"segment": "Moda", "product_description": "Roupas", "goals": "Recompra"},
                    "updated_at": "2026-01-03T12:00:00Z"}
        with patch.object(service, "_read_model_executive_context", AsyncMock(return_value={})), \
             patch.object(service, "resolve_commerce_context", AsyncMock(return_value={})), \
             patch.object(service, "load_business_context", AsyncMock(return_value=business)) as load, \
             patch.object(service, "external_research_context", AsyncMock(return_value={"status": "not_configured"})), \
             patch.object(service, "sb_select", AsyncMock(return_value=[row(), row(stat_date="2026-01-02")])), \
             redirect_stdout(io.StringIO()):
            snapshot = await service.calculate_intelligence_snapshot(client_id="tenant-a", start=START.isoformat(), end=END.isoformat())
            load.assert_awaited_once_with("tenant-a")
        self.assertEqual(len(snapshot["top_campaigns"]), 1)  # Active path, not unreachable legacy collection.
        campaign = snapshot["top_campaigns"][0]
        generated = content(campaign["metric_ids"][0], campaign["source_id"])
        async def save(value, **kwargs): return {"id": "fixture", **value}
        model = AsyncMock(return_value=generated)
        with patch.object(service, "_call_analysis_with_numeric_repair", model), patch.object(service, "_insert_analysis", save), redirect_stdout(io.StringIO()):
            result = await service._generate_with_provider(client_id="tenant-a", snapshot=snapshot,
                period=snapshot["period"], base_row={"client_id": "tenant-a", "data_quality": snapshot["quality"]}, request_id="fixture")
        self.assertEqual(result["analysis"]["client_id"], "tenant-a")
        payload = model.await_args.kwargs["payload"]
        self.assertEqual(payload["business_context"], business["context"])
        self.assertEqual(payload["top_campaigns"], snapshot["top_campaigns"])
        changed = copy.deepcopy(snapshot); changed["business_context"]["context"]["goals"] = "Margem"
        self.assertNotEqual(service.context_fingerprint(snapshot), service.context_fingerprint(changed))
        changed = copy.deepcopy(snapshot); changed["top_campaigns"][0]["name"] = "Outro nome"
        self.assertNotEqual(service.context_fingerprint(snapshot), service.context_fingerprint(changed))

    async def test_light_context_does_not_read_campaigns(self):
        with patch.object(service, "_read_model_executive_context", AsyncMock(return_value={})), \
             patch.object(service, "resolve_commerce_context", AsyncMock(return_value={})), \
             patch.object(service, "load_business_context", AsyncMock(return_value={})), \
             patch.object(service, "_campaign_analysis_context", AsyncMock()) as campaigns, redirect_stdout(io.StringIO()):
            await service.calculate_intelligence_snapshot(client_id="tenant-a", start=START.isoformat(), end=END.isoformat(),
                                                         include_commerce_details=False, include_external_research=False)
            campaigns.assert_not_awaited()


class UpdatedBusinessGenerationTests(unittest.IsolatedAsyncioTestCase):
    async def test_save_then_generate_reloads_context_for_same_tenant_and_changes_fingerprint(self):
        from services import business_context
        persisted = {"client_id": "tenant-a", "segment": "Moda", "product_description": "Roupas", "goals": "Recompra"}
        async def upsert(table, rows, **kwargs): persisted.update(rows[0]); return {}
        async def save_analysis(value, **kwargs): return {"id": "fixture", **value}
        async def model(**kwargs):
            payload = kwargs["payload"]; campaign = payload["top_campaigns"][0]
            return content(campaign["metric_ids"][0], campaign["source_id"])
        with patch.object(business_context, "sb_select", AsyncMock(side_effect=lambda *a, **k: [dict(persisted)])),              patch.object(business_context, "sb_upsert", AsyncMock(side_effect=upsert)),              patch.object(service, "_read_model_executive_context", AsyncMock(return_value={})),              patch.object(service, "resolve_commerce_context", AsyncMock(return_value={})),              patch.object(service, "external_research_context", AsyncMock(return_value={"status": "not_configured"})),              patch.object(service, "sb_select", AsyncMock(return_value=[row(), row(stat_date="2026-01-02")])),              patch.object(service, "provider_configured", return_value=True),              patch.object(service, "_reusable_analysis", AsyncMock(return_value=None)) as reuse,              patch.object(service, "_generation_cooldown_remaining", AsyncMock(return_value=0)),              patch.object(service, "_call_analysis_with_numeric_repair", AsyncMock(side_effect=model)) as provider,              patch.object(service, "_insert_analysis", save_analysis), redirect_stdout(io.StringIO()):
            await service.generate_analysis(client_id="tenant-a", user_id="user-a", start=START.isoformat(), end=END.isoformat())
            await business_context.save_business_context(client_id="tenant-a", user_id="user-a",
                payload={"segment": "Moda", "product_description": "Roupas", "goals": "Margem"})
            await service.generate_analysis(client_id="tenant-a", user_id="user-a", start=START.isoformat(), end=END.isoformat())
        self.assertEqual(provider.await_count, 2)
        self.assertEqual(provider.await_args_list[0].kwargs["payload"]["business_context"]["goals"], "Recompra")
        self.assertEqual(provider.await_args_list[1].kwargs["payload"]["business_context"]["goals"], "Margem")
        self.assertNotEqual(reuse.await_args_list[0].kwargs["fingerprint"], reuse.await_args_list[-1].kwargs["fingerprint"])
        self.assertTrue(all(call.kwargs["client_id"] == "tenant-a" for call in reuse.await_args_list))
