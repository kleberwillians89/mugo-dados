import json
import httpx
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace

from fastapi import FastAPI
from starlette.testclient import TestClient
from mcp_readonly import tools
from mcp_readonly.transport import install

WINDOW = {"start": "2026-10-01", "end": "2026-10-20"}
PII = {"email": "comprador@example.test", "raw_payload": {"name": "Pessoa Compradora", "cpf": "123.456.789-00"},
       "label": "Pessoa Compradora", "last_error": "segredo", "revenue": 200, "spend": 100}


class ReadonlyToolsTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_company_tool_denies_other_tenant_before_read(self):
        with patch.object(tools, "require_user_client_access", AsyncMock(side_effect=PermissionError)) as access, patch.object(tools, "_read", AsyncMock()) as read:
            for name in tools.TOOLS[1:]:
                with self.subTest(name=name), self.assertRaises(tools.ToolFailure):
                    await tools.dispatch("user-a", name, "company-b", **WINDOW)
            read.assert_not_awaited()
            self.assertTrue(all(c.kwargs == {"fresh": True} for c in access.await_args_list))

    async def test_removed_membership_denies_next_call(self):
        with patch.object(tools, "require_user_client_access", AsyncMock(side_effect=["company-a", PermissionError])), patch.object(tools, "_read", AsyncMock(return_value={"metrics": []})) as read:
            await tools.dispatch("user-a", "get_business_overview", "company-a", **WINDOW)
            with self.assertRaises(tools.ToolFailure):
                await tools.dispatch("user-a", "get_business_overview", "company-a", **WINDOW)
            self.assertEqual(read.await_count, 1)

    async def test_snapshot_is_readonly_and_never_requests_research(self):
        with patch("services.intelligence.calculate_intelligence_snapshot", AsyncMock(return_value={"client": {"id": "company-a"}})) as calculate:
            await tools.snapshot("company-a", WINDOW)
            calculate.assert_awaited_once_with(client_id="company-a", **WINDOW, include_commerce_details=False, include_external_research=False)

    async def test_every_tool_minimizes_planted_pii_without_writes(self):
        sample = {"client": {"id": "company-a"}, "metrics": [{"id": "revenue", "value": 200, "source": "shopify", "format": "currency", "status": "confirmed", **PII}],
                  "sources": [{"id": "shopify", "connected": True, "status": "available", **PII}], "period": WINDOW}
        # All write primitives are forbidden, including accidentally reusing a sync service.
        with patch.object(tools, "require_user_client_access", AsyncMock(return_value="company-a")), \
             patch.object(tools, "snapshot", AsyncMock(return_value=sample)), \
             patch.object(tools, "connected", AsyncMock(return_value=(["meta", "google_ads", "ga4"], []))), \
             patch.object(tools, "sb_select", AsyncMock(return_value=[{"client_id": "company-a", **PII}])), \
             patch("services.clients.list_clients_for_user", AsyncMock(return_value={"clients": [{"client_id": "company-a", "name": "Empresa A", **PII}]})), \
             patch("services.business_context.load_business_context", AsyncMock(return_value={"available": True, "context": PII})), \
             patch("services.ga4_connections.resolve_ga4_connection_context", AsyncMock(return_value=SimpleNamespace(client_id="company-a", property_id="p"))), \
             patch("services.ga4_reporting.build_ga4_report", AsyncMock(return_value={"summary": PII, "channels": [{"source_medium": "Pessoa Compradora", **PII}]})), \
             patch("services.posting_times.sb_select", AsyncMock(return_value=[{"client_id": "company-a", "timestamp": "2026-10-05T15:00:00+0000", "insights_json": {"reach": 10, **PII}, **PII}])), \
             patch("services.goals.list_goals", AsyncMock(return_value={"goals": [PII]})), \
             patch("services.sales_by_origin.build_sales_by_origin", AsyncMock(return_value={"totals": PII, "channels": [{"channel": "direct", **PII}], "campaigns": [{"campaign": "Pessoa Compradora comprador@example.test", **PII}]})), \
             patch("services.dashboard_paid.get_paid_dashboard", AsyncMock(return_value={"totals": PII})), \
             patch("services.dashboard_paid.list_campaigns", AsyncMock(return_value={"campaigns": [PII]})), \
             patch("services.ig_supabase.sb_insert", AsyncMock(side_effect=AssertionError("write"))), \
             patch("services.ig_supabase.sb_upsert", AsyncMock(side_effect=AssertionError("write"))), \
             patch("services.ig_supabase.sb_update", AsyncMock(side_effect=AssertionError("write"))):
            for name in tools.TOOLS:
                with self.subTest(name=name):
                    result = await tools.dispatch("user-a", name, None if name == "list_companies" else "company-a", provider="meta", **WINDOW)
                    encoded = json.dumps(result)
                    for forbidden in ("comprador@example.test", "Pessoa Compradora", "123.456.789-00", "raw_payload", "segredo"):
                        self.assertNotIn(forbidden, encoded)
                    self.assertIn("observacoes", result)

    async def test_period_validation_before_reads(self):
        with patch.object(tools, "_read", AsyncMock()) as read:
            for window in ({"start": "2025-01-01", "end": "2026-10-20"}, {"start": "not-a-date"}, {"start": "2026-10-20", "end": "2026-10-01"}):
                with self.assertRaises(tools.ToolFailure):
                    await tools.dispatch("u", "get_goals", "a", **window)
            read.assert_not_awaited()
        self.assertEqual(tools.period("2025-01-01", "2026-02-04")["start"], "2025-01-01")

    async def test_pilot_and_filter_injection_rejected(self):
        with patch.dict(os.environ, {"MCP_PILOT_CLIENT_IDS": "allowed"}), patch.object(tools, "require_user_client_access", AsyncMock()) as access:
            for company in ("other", "allowed,or(client_id.eq.other)"):
                with self.assertRaises(tools.ToolFailure):
                    await tools.dispatch("u", "get_goals", company, **WINDOW)
            access.assert_not_awaited()

    async def test_safe_errors_timeout_and_response_limit(self):
        with patch.object(tools, "require_user_client_access", AsyncMock()), patch.object(tools, "_read", AsyncMock(side_effect=TimeoutError)):
            with self.assertRaisesRegex(tools.ToolFailure, "tempo"):
                await tools.dispatch("u", "get_goals", "a", **WINDOW)
        with patch.object(tools, "require_user_client_access", AsyncMock()), patch.object(tools, "_read", AsyncMock(side_effect=RuntimeError("secret"))):
            with self.assertRaises(tools.ToolFailure) as error:
                await tools.dispatch("u", "get_goals", "a", **WINDOW)
            self.assertNotIn("secret", str(error.exception))
        with patch.object(tools, "require_user_client_access", AsyncMock()), patch.object(tools, "_read", AsyncMock(return_value={"oversize": "x" * 65537})):
            with self.assertRaisesRegex(tools.ToolFailure, "limite"):
                await tools.dispatch("u", "get_goals", "a", **WINDOW)

    async def test_google_campaigns_reject_wrong_company_account_connection_and_date(self):
        context = SimpleNamespace(client_id="a", connection_id="selected", customer_id="selected-account")
        row = {"client_id": "a", "connection_id": "selected", "customer_id": "selected-account", "campaign_id": "private-campaign", "campaign_name": "pmax_marca",
               "stat_date": "2026-10-10", "cost": 100, "conversion_value": 200}
        rows = [row, {**row, "client_id": "b"}, {**row, "connection_id": "other"}, {**row, "customer_id": "other"}, {**row, "stat_date": "2026-09-01"}]
        with patch.object(tools, "require_user_client_access", AsyncMock()), patch.object(tools, "connected", AsyncMock(return_value=(["google_ads"], []))), \
             patch("services.google_ads.resolve_google_ads_context", AsyncMock(return_value=context)), \
             patch("services.google_ads.build_google_ads_report", AsyncMock(return_value={"totals": {"spend": 100}})), \
             patch.object(tools, "sb_select", AsyncMock(return_value=rows)) as read:
            result = await tools.dispatch("u", "get_paid_media", "a", provider="google_ads", **WINDOW)
            self.assertEqual(result["campaigns"][0]["spend"], 100)
            self.assertEqual(result["campaigns"][0]["revenue"], 200)
            self.assertNotIn("private-campaign", json.dumps(result))
            self.assertEqual(result["campaigns"][0]["name"], "pmax_marca")
            filters = read.await_args.kwargs["filters"]
            self.assertEqual(filters["client_id"], "eq.a")
            self.assertEqual(filters["connection_id"], "eq.selected")
            self.assertEqual(filters["customer_id"], "eq.selected-account")

    async def test_six_generic_tenants_each_read_only_their_snapshot(self):
        async def canonical(**kwargs):
            cid = kwargs["client_id"]
            return {"client": {"id": cid}, "metrics": [{"id": "revenue", "value": int(cid[-1]), "source": "shopify", "format": "currency"}]}
        with patch.object(tools, "require_user_client_access", AsyncMock(side_effect=lambda uid, cid, **kw: cid)), \
             patch("services.intelligence.calculate_intelligence_snapshot", AsyncMock(side_effect=canonical)) as read:
            for index in range(1, 7):
                cid = "tenant-" + str(index)
                result = await tools.dispatch("user-" + str(index), "get_business_overview", cid, **WINDOW)
                self.assertEqual(result["metrics"][0]["value"], index)
                self.assertEqual(read.await_args.kwargs["client_id"], cid)
        with patch("services.intelligence.calculate_intelligence_snapshot", AsyncMock(return_value={"client": {"id": "other"}})):
            with self.assertRaises(tools.ToolFailure):
                await tools.snapshot("a", WINDOW)

    async def test_transport_enforces_rate_and_wire_size_limits(self):
        from mcp_readonly.transport import LocalGateway
        gateway = LocalGateway()
        async def small(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}"})
        async def large(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"x" * 262145})
        async def receive():
            return {"type": "http.request", "body": b""}
        scope = {"type": "http", "method": "POST", "path": "/mcp", "headers": [], "client": ("127.0.0.1", 1), "server": ("localhost", 80)}
        with patch.dict(os.environ, {"MCP_ENABLED": "true", "ALLOW_NO_AUTH": "true", "APP_ENV": "test"}, clear=True):
            gateway.sdk_app = small
            for index in range(61):
                sent = []
                async def send(message): sent.append(message)
                await gateway(scope, receive, send)
                self.assertEqual(sent[0]["status"], 200 if index < 60 else 429)
            gateway.buckets.clear(); gateway.sdk_app = large
            sent = []
            await gateway(scope, receive, send)
            self.assertEqual(sent[0]["status"], 413)

    async def test_supabase_error_logs_are_redacted_only_in_mcp_context(self):
        from services import ig_supabase as sb
        response = httpx.Response(400, text="comprador@example.test Pessoa Compradora", request=httpx.Request("GET", "https://database.example.test"))
        http = AsyncMock(); http.request.return_value = response
        manager = MagicMock(); manager.__aenter__ = AsyncMock(return_value=http)
        manager.__aexit__ = AsyncMock(return_value=False)
        with patch.object(sb, "_assert_env"), patch.object(sb, "_headers", return_value={}), \
             patch.object(sb, "_base_url", return_value="https://database.example.test"), \
             patch.object(sb.httpx, "AsyncClient", return_value=manager), patch("builtins.print") as log:
            privacy = sb.mcp_safe_errors.set(True)
            try:
                with self.assertRaises(httpx.HTTPStatusError):
                    await sb._request("GET", "/aggregate")
            finally:
                sb.mcp_safe_errors.reset(privacy)
            output = str(log.call_args_list)
            self.assertNotIn("comprador@example.test", output)
            self.assertNotIn("Pessoa Compradora", output)
            self.assertIn("omitido no MCP", output)
            self.assertFalse(sb.mcp_safe_errors.get())

    async def test_ga4_bounded_aggregates_filter_tenant_property_and_hide_urls(self):
        base = {"client_id": "a", "property_id": "p", "stat_date": "2026-10-10"}
        samples = {
            "ga4_daily_stats": [{**base, "sessions": 100, "transactions": 2}, {**base, "client_id": "b", "sessions": 999}],
            "ga4_channel_stats": [{**base, "source_medium": "comprador@example.test", "sessions": 25}],
            "ga4_landing_page_stats": [{**base, "landing_page": "/obrigado?email=comprador@example.test", "sessions": 20},
                {**base, "landing_page": "/cliente/123.456.789-00", "sessions": 7},
                {**base, "property_id": "other", "landing_page": "/other", "sessions": 500}],
        }
        async def read(table, **kwargs):
            self.assertEqual(kwargs["filters"]["client_id"], "eq.a")
            self.assertEqual(kwargs["filters"]["property_id"], "eq.p")
            self.assertLessEqual(kwargs["limit"], 2001)
            return samples[table]
        with patch.object(tools, "require_user_client_access", AsyncMock()), patch.object(tools, "connected", AsyncMock(return_value=(["ga4"], []))), \
             patch("services.ga4_connections.resolve_ga4_connection_context", AsyncMock(return_value=SimpleNamespace(client_id="a", property_id="p"))), \
             patch("services.ga4_reporting._select_ga4_rollup", AsyncMock(return_value=None)), \
             patch.object(tools, "sb_select", AsyncMock(side_effect=read)):
            result = await tools.dispatch("u", "get_site_traffic", "a", **WINDOW)
            self.assertEqual(result["summary"]["sessions"], 100)
            self.assertEqual(result["summary"]["transactions"], 2)
            self.assertEqual(result["channels"][0]["sessions"], 25)
            self.assertEqual(result["landing_pages"], [{"path": "/obrigado", "sessions": 20}])
            self.assertIsNone(result["channels"][0]["source_medium"])
            self.assertNotIn("comprador@example.test", json.dumps(result))
            self.assertNotIn("123.456.789-00", json.dumps(result))


    async def test_ga4_rollup_path_keeps_scope_and_privacy(self):
        base = {"client_id": "a", "property_id": "p", "stat_date": "2026-10-10"}
        rollup = {
            "channels": [{"source_medium": "comprador@example.test", "source": "", "medium": "", "sessions": 25, "row_count": 3},
                         {"source_medium": "google / cpc", "source": "google", "medium": "cpc", "sessions": 40,
                          "ecommerce_purchases": 2, "purchase_revenue": 300.5, "row_count": 30}],
            "landing_pages": [{"landing_page": "/obrigado?email=comprador@example.test", "sessions": 20, "row_count": 2},
                              {"landing_page": "/obrigado", "sessions": 5, "row_count": 1},
                              {"landing_page": "/cliente/123.456.789-00", "sessions": 7, "row_count": 1}],
        }
        read_tables = []

        async def read(table, **kwargs):
            read_tables.append(table)
            self.assertEqual(kwargs["filters"]["client_id"], "eq.a")
            return [{**base, "sessions": 100}]

        rollup_call = AsyncMock(return_value=rollup)
        with patch.object(tools, "require_user_client_access", AsyncMock()), patch.object(tools, "connected", AsyncMock(return_value=(["ga4"], []))), \
             patch("services.ga4_connections.resolve_ga4_connection_context", AsyncMock(return_value=SimpleNamespace(client_id="a", property_id="p"))), \
             patch("services.ga4_reporting._select_ga4_rollup", rollup_call), \
             patch.object(tools, "sb_select", AsyncMock(side_effect=read)):
            result = await tools.dispatch("u", "get_site_traffic", "a", **WINDOW)
        self.assertEqual(read_tables, ["ga4_daily_stats"])
        self.assertEqual(rollup_call.await_args.kwargs["client_id"], "a")
        self.assertEqual(rollup_call.await_args.kwargs["property_id"], "p")
        self.assertEqual(rollup_call.await_args.kwargs["parts"], ("channels", "landing_pages"))
        self.assertEqual(result["landing_pages"], [{"path": "/obrigado", "sessions": 25}])
        self.assertEqual(result["channels"][0]["sessions"], 40)
        text = json.dumps(result)
        self.assertNotIn("comprador@example.test", text)
        self.assertNotIn("123.456.789-00", text)


class BusinessTextTests(unittest.IsolatedAsyncioTestCase):
    def test_business_text_keeps_company_data_and_drops_buyer_patterns(self):
        self.assertEqual(tools.business_text("conversao_colecao_verao_2026"), "conversao_colecao_verao_2026")
        self.assertEqual(tools.business_text("  Black   Friday  "), "Black Friday")
        for value in ("promo comprador@example.test", "cliente 123.456.789-00", "(11) 98765-4321", "id 12345678901", 42, None):
            self.assertIsNone(tools.business_text(value))
        self.assertEqual(tools.page_path("https://loja.test/produto/legging?utm_source=x#top"), "/produto/legging")

    async def test_sales_by_origin_returns_campaign_names(self):
        data = {"provider": "shopify", "status": "available", "totals": {"orders": 3},
                "channels": [], "campaigns": [{"campaign": "bf_2026", "source": "facebook", "medium": "cpc", "channel": "paid_social", "orders": 2, "revenue": 150}]}
        with patch.object(tools, "require_user_client_access", AsyncMock()), \
             patch("services.sales_by_origin.build_sales_by_origin", AsyncMock(return_value=data)):
            result = await tools.dispatch("u", "get_sales_by_origin", "a", **WINDOW)
        self.assertEqual(result["campaigns"][0]["campaign"], "bf_2026")
        self.assertEqual(result["campaigns"][0]["source"], "facebook")
        self.assertEqual(result["campaigns"][0]["revenue"], 150)

    async def test_context_and_latest_analysis_return_text_without_buyer_data(self):
        context = {"available": True, "updated_at": "2026-10-01T00:00:00Z",
                   "context": {"segment": "Moda fitness", "audience": "Fale com comprador@example.test", "goals": "Crescer 20%"}}
        analysis = {"client_id": "a", "period_start": "2026-10-01", "period_end": "2026-10-20", "created_at": "2026-10-21T00:00:00Z",
                    "metrics_snapshot": [{"id": "new_customers", "label": "Novos clientes"}], "sources": [],
                    "analysis": {"executive": {"overall": "Vendas subiram. metric_ids: new_customers", "priority_action": "Escalar remarketing"},
                                 "insights": [{"title": "Base nova cresceu", "interpretation": "x", "action": "y", "category": "positive"}],
                                 "actions": [{"recommendation": "Testar frete grátis", "justification": "ticket", "impact_expected": "high"}]}}
        with patch.object(tools, "require_user_client_access", AsyncMock()), \
             patch("services.business_context.load_business_context", AsyncMock(return_value=context)), \
             patch.object(tools, "sb_select", AsyncMock(return_value=[analysis])):
            ctx = await tools.dispatch("u", "get_business_context", "a", **WINDOW)
            latest = await tools.dispatch("u", "get_latest_analysis", "a", **WINDOW)
        self.assertEqual(ctx["context"], {"segment": "Moda fitness", "goals": "Crescer 20%"})
        executive = latest["analysis"]["executive"]
        self.assertEqual(executive["overall"], "Vendas subiram. Novos clientes")
        self.assertEqual(latest["analysis"]["actions"][0]["impact_expected"], "Impacto alto")
        self.assertNotIn("comprador@example.test", json.dumps([ctx, latest]))


class FreshPermissionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_platform_admin_fresh_bypasses_global_cache(self):
        from services.platform_admin import is_platform_admin
        with patch("services.platform_admin.sb_select", AsyncMock(side_effect=[[{"user_id": "u"}], []])), patch("services.platform_admin.get_cached_or_load", AsyncMock()) as cache:
            self.assertTrue(await is_platform_admin("u", fresh=True))
            self.assertFalse(await is_platform_admin("u", fresh=True))
            cache.assert_not_awaited()

    async def test_admin_and_membership_rules_unchanged(self):
        from services.tenant import require_user_client_access
        for platform, agency in ((True, False), (False, True), (False, False)):
            with self.subTest(platform=platform, agency=agency), \
                 patch("services.platform_admin.is_platform_admin", AsyncMock(return_value=platform)), \
                 patch("services.tenant._has_agency_admin_membership", AsyncMock(return_value=agency)), \
                 patch("services.ig_supabase.sb_select", AsyncMock(return_value=[{"id": "c"}])), \
                 patch("services.tenant.sb_get_client_id_for_user", AsyncMock(return_value="c")) as member:
                self.assertEqual(await require_user_client_access("u", "c", fresh=True), "c")
                self.assertEqual(member.await_count, 0 if platform or agency else 1)


class StreamableTransportTests(unittest.TestCase):
    def test_disabled_and_every_production_marker_fail_closed(self):
        variants = [{"MCP_ENABLED": "false"}, *({"MCP_ENABLED": "true", "ALLOW_NO_AUTH": "true", key: value}
            for key, value in (("APP_ENV", "production"), ("ENVIRONMENT", "prod"), ("PYTHON_ENV", "production"), ("RENDER", "true")))]
        for values in variants:
            with self.subTest(values=values), patch.dict(os.environ, values, clear=True):
                app = FastAPI(); gateway = install(app)
                with TestClient(app, base_url="http://localhost") as client:
                    self.assertEqual(client.post("/mcp", json={}).status_code, 404)
                    self.assertIsNone(gateway.sdk)

    def test_real_sdk_initialize_catalog_and_tool_identity(self):
        with patch.dict(os.environ, {"MCP_ENABLED": "true", "ALLOW_NO_AUTH": "true", "APP_ENV": "test", "DEV_USER_ID": "user-a"}, clear=True):
            app = FastAPI(); install(app)
            with TestClient(app, base_url="http://localhost") as client:
                headers = {"Accept": "application/json, text/event-stream"}
                def call(method, params=None):
                    response = client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
                    self.assertEqual(response.status_code, 200, response.text)
                    return response.json()["result"]
                self.assertIn("protocolVersion", call("initialize", {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}))
                catalog = call("tools/list")["tools"]
                self.assertEqual({t["name"] for t in catalog}, set(tools.TOOLS))
                self.assertTrue(all(t["annotations"]["readOnlyHint"] for t in catalog))
                with patch("mcp_readonly.transport.dispatch", AsyncMock(return_value={"observacoes": []})) as read:
                    call("tools/call", {"name": "get_goals", "arguments": {"company_id": "company-a"}})
                    self.assertEqual(read.await_args.args, ("user-a", "get_goals"))
                    invalid = call("tools/call", {"name": "get_goals", "arguments": {"company_id": {"email": "private@example.test"}}})
                    self.assertTrue(invalid["isError"])
                    self.assertNotIn("private@example.test", json.dumps(invalid))
                    with patch.dict(os.environ, {"DEV_USER_ID": "user-b"}):
                        call("tools/call", {"name": "get_goals", "arguments": {"company_id": "company-b"}})
                    self.assertEqual(read.await_args.args, ("user-b", "get_goals"))
                self.assertEqual(client.get("/mcp", headers=headers).status_code, 405)
                hostile = client.post("/mcp", headers={**headers, "Origin": "https://hostile.example"}, json={})
                self.assertIn(hostile.status_code, (400, 403))


class FastCompanyListingTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_companies_is_parallel_and_tolerates_slow_company(self):
        import asyncio as aio
        clients = {"clients": [{"client_id": f"c{i}", "name": f"Empresa {i}"} for i in range(12)]}

        async def connected(cid, window):
            if cid == "c3":
                await aio.sleep(10)  # mais que o limite por empresa
            await aio.sleep(0.05)
            return ["shopify"], []

        with patch("services.clients.list_clients_for_user", AsyncMock(return_value=clients)), \
             patch.object(tools, "connected", connected), \
             patch.object(tools, "_COMPANY_SOURCES_TIMEOUT", 0.3):
            started = aio.get_running_loop().time()
            result = await tools.dispatch("u", "list_companies", **WINDOW)
            elapsed = aio.get_running_loop().time() - started
        self.assertEqual(len(result["companies"]), 12)
        self.assertLess(elapsed, 2)
        by_id = {row["id"]: row for row in result["companies"]}
        self.assertIsNone(by_id["c3"]["sources"])
        self.assertEqual(by_id["c0"]["sources"], ["shopify"])

    async def test_authorized_companies_is_light_and_respects_pilot(self):
        clients = {"clients": [{"client_id": "roove", "name": "Roove"}, {"client_id": "curavino", "name": "Curavino"}]}
        with patch("services.clients.list_clients_for_user", AsyncMock(return_value=clients)) as listing, \
             patch.object(tools, "connected", AsyncMock(side_effect=AssertionError("não deve ler fontes"))):
            everyone = await tools.authorized_companies("u", set())
            pilot = await tools.authorized_companies("u", {"roove"})
        self.assertEqual([c["id"] for c in everyone], ["roove", "curavino"])
        self.assertEqual(pilot, [{"id": "roove", "name": "Roove"}])
        self.assertTrue(all(call.kwargs.get("fresh") is True for call in listing.await_args_list))
