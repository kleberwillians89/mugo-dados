import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import io
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI

from services import news_engine as ne
from services import studio_clipping as clip

RSS = """<rss><channel>
<item><title>Curavino lança vinho laranja - Revista Adega</title><link>https://adega.com/a1</link><source>Revista Adega</source>
<description><![CDATA[<p>A Curavino lançou um vinho laranja feito em SP.</p> O post Curavino apareceu primeiro em Adega.]]></description>
<content:encoded><![CDATA[<p>A Curavino lançou um vinho laranja feito em São Paulo, com uvas orgânicas.</p>]]></content:encoded>
<pubDate>Wed, 28 Oct 2026 12:00:00 GMT</pubDate></item>
<item><title>Sem link</title></item>
<item><title>Truncado"""
ATOM = """<feed><entry><title>Evino abre loja</title><link rel="alternate" href="https://blog.com/evino"/>
<updated>2026-10-29T10:00:00Z</updated><summary>Evino inaugura loja física.</summary></entry></feed>"""
PAGE = """<html><head><meta property="og:description" content="A Curavino anunciou expansão nacional em 2027."></head>
<body><script>x()</script><article><p>Assine nossa newsletter para receber novidades toda semana no seu e-mail.</p>
<p>Segundo a empresa, a expansão começa pelo Sul e deve abrir dez pontos de venda até o fim do ano.</p></article></body></html>"""


class EngineTests(unittest.TestCase):
    def test_rss_and_atom_like_the_crm(self):
        items = ne.parse_feed(RSS)
        self.assertEqual(len(items), 1)  # sem link e truncado ficam de fora
        self.assertEqual(items[0]["title"], "Curavino lança vinho laranja")
        self.assertIn("uvas orgânicas", items[0]["excerpt"])  # trecho mais completo (content:encoded)
        self.assertNotIn("apareceu primeiro", items[0]["excerpt"])
        atom = ne.parse_feed(ATOM)[0]
        self.assertEqual((atom["url"], atom["published_at"]), ("https://blog.com/evino", "2026-10-29T10:00:00+00:00"))

    def test_article_text_skips_noise(self):
        text = ne.extract_article_text(PAGE)
        self.assertTrue(text.startswith("A Curavino anunciou expansão"))
        self.assertIn("dez pontos de venda", text)
        self.assertNotIn("newsletter", text)

    def test_dedupe_by_url_and_folded_title(self):
        items = [{"url": "https://a/1", "title": "Curavino lança vinho!"}, {"url": "https://b/2", "title": "curavino lanca vinho"},
                 {"url": "https://a/1", "title": "outro"}, {"url": "https://c/3", "title": "Outra matéria"}]
        self.assertEqual([i["url"] for i in ne.dedupe(items)], ["https://a/1", "https://c/3"])

    def test_balance_limits_one_source(self):
        items = [{"source": "G1", "kind": "marca", "url": f"u{i}"} for i in range(20)] + [{"source": "Folha", "kind": "tema", "url": "f"}]
        out = ne.balance_by_source(items, per_source=5, max_items=10)
        self.assertEqual(sum(1 for i in out if i["source"] == "G1"), 5)
        self.assertIn("f", [i["url"] for i in out])

    def test_evidence_must_exist_in_source(self):
        self.assertEqual(ne.evidence_in(["Curavino lançou um vinho laranja", "inventado pela IA"], "A Curavino lançou um vinho laranja feito em SP."),
                         ["Curavino lançou um vinho laranja"])

    def test_recency_priority(self):
        now = datetime(2026, 10, 30, tzinfo=timezone.utc)
        self.assertEqual(ne.recency_priority("2026-10-29T12:00:00+00:00", now)["priority"], "critical")
        self.assertEqual(ne.recency_priority("2026-10-01T00:00:00+00:00", now)["priority"], "low")

    def test_gdelt_is_prepared_but_disabled(self):
        import asyncio
        self.assertFalse(ne.GdeltProvider.enabled)
        with self.assertRaises(ne.ProviderDisabled):
            asyncio.run(ne.GdeltProvider().search("x", exclude=[]))


SETTINGS = {"brand_terms": ["Curavino"], "competitor_terms": [], "exclude_terms": [], "people": [], "keywords": [], "themes": [],
            "feeds": [], "region": None, "relevance_criteria": None, "min_relevance": 40, "ai_daily_limit": 60, "active": True,
            "last_run_at": None, "saved": True}
ITEM = {"url": "https://adega.com/a1", "url_hash": ne.url_hash("https://adega.com/a1"), "title": "Curavino lança vinho laranja",
        "source": "Adega", "published_at": "2026-10-28T12:00:00+00:00", "kind": "marca", "term": "Curavino"}
LABEL = {"sentiment": "negativo", "summary": "s", "relevance": 80, "criticality": "critica", "main_theme": "crise", "entities": [],
         "opportunities": [], "risks": ["recall"], "justification": "j", "evidence": ["vinho laranja"], "analyzed_at": "t"}


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def run_refresh(self, client_id, settings=SETTINGS, labels=None, budget=60):
        insert, alert = AsyncMock(), AsyncMock(return_value=0)
        classify = AsyncMock(return_value=labels if labels is not None else {0: LABEL})
        with patch.object(clip, "get_settings", AsyncMock(return_value=settings)), patch.object(clip, "fetch_term", AsyncMock(return_value=[dict(ITEM)])), \
             patch.object(clip, "sb_select", AsyncMock(return_value=[])), patch.object(clip, "store_articles", AsyncMock(return_value={})), \
             patch.object(clip, "_ai_budget", AsyncMock(return_value=budget)), patch.object(clip, "_spend", AsyncMock()), \
             patch.object(clip, "_classify", classify), patch.object(clip, "_alert_team", alert), patch.object(clip, "sb_insert_many", insert), \
             patch.object(clip, "sb_update", AsyncMock()), patch("services.studio_messages._client_name", AsyncMock(return_value=client_id.title())), \
             redirect_stdout(io.StringIO()):
            result = await clip.refresh(client_id)
        return result, insert, classify, alert

    async def test_same_article_analyzed_per_client_with_its_context(self):
        _, insert_a, classify_a, _ = await self.run_refresh("cura")
        _, insert_b, classify_b, _ = await self.run_refresh("roove", settings={**SETTINGS, "brand_terms": ["Roove"], "themes": ["vinho"]})
        self.assertEqual(insert_a.await_args.args[1][0]["client_id"], "cura")
        self.assertEqual(insert_b.await_args.args[1][0]["client_id"], "roove")
        self.assertIn("Cura", classify_a.await_args.args[0])
        self.assertIn("TEMAS ESTRATÉGICOS: vinho", classify_b.await_args.args[0])
        self.assertNotIn("Cura", classify_b.await_args.args[0])

    async def test_ai_budget_zero_inserts_without_analysis(self):
        result, insert, classify, _ = await self.run_refresh("cura", budget=0, labels={})
        classify.assert_not_awaited()
        self.assertEqual(result["not_analyzed"], 1)
        self.assertNotIn("sentiment", insert.await_args.args[1][0])

    async def test_relevant_flag_follows_client_threshold(self):
        _, insert, _, _ = await self.run_refresh("cura", settings={**SETTINGS, "min_relevance": 90})
        self.assertFalse(insert.await_args.args[1][0]["relevant"])


class AlertTests(unittest.IsolatedAsyncioTestCase):
    async def test_critical_goes_only_to_team_and_is_idempotent_per_article(self):
        from services import automations
        definition = {"key": "clipping_critico", "owner": "dados", "automation_enabled": True, "audience": "equipe"}
        enqueue = AsyncMock(return_value={"id": "o"})
        rows = [{**ITEM, **LABEL}, {**ITEM, **LABEL, "url_hash": "x" * 40, "criticality": "baixa", "sentiment": "positivo"}]
        with patch.object(automations, "load_definitions", AsyncMock(return_value={"clipping_critico": definition})), \
             patch.object(automations, "team_members", AsyncMock(return_value=[{"id": "t1", "name": "Ana Lima", "phone": "5511911110000"}])), \
             patch.object(automations, "enqueue", enqueue):
            queued = await clip._alert_team("cura", "Curavino", rows)
        self.assertEqual(queued, 1)
        call = enqueue.await_args.kwargs
        self.assertTrue(call["recipient"]["team_member"])
        self.assertEqual((call["source_type"], call["source_id"]), ("clipping", ITEM["url_hash"]))
        self.assertEqual(rows[0]["alert_status"], "enfileirado")


class ReportTests(unittest.IsolatedAsyncioTestCase):
    async def test_report_keeps_only_collected_urls(self):
        rows = [{**ITEM, **LABEL, "relevant": True, "created_at": "2026-10-28T12:00:00+00:00", "status": "novo"}]
        out = {"summary": "Semana com crise.", "highlights": [{"text": "Lançamento", "url": ITEM["url"]}, {"text": "inventado", "url": "https://fake/x"}],
               "risks": [], "opportunities": []}
        with patch.object(clip, "get_settings", AsyncMock(return_value=SETTINGS)), patch.object(clip, "period_rows", AsyncMock(return_value=rows)), \
             patch("services.studio_messages._client_name", AsyncMock(return_value="Curavino")), patch("services.studio_llm.llm_json", AsyncMock(return_value=out)):
            report = await clip.build_report("cura", "semanal", "cobertura")
        self.assertEqual([h["url"] for h in report["highlights"]], [ITEM["url"]])
        self.assertEqual(report["sources"][0]["url"], ITEM["url"])

    def test_insights_and_csv(self):
        now = datetime.now(timezone.utc).isoformat()
        rows = [{**ITEM, **LABEL, "created_at": now, "published_at": now}, {**ITEM, "kind": "concorrente", "term": "Evino", "source": "G1",
                 "sentiment": "neutro", "relevance": 20, "criticality": "baixa", "main_theme": "varejo", "created_at": now, "published_at": now}]
        data = clip.insights_from(rows, 7)
        self.assertEqual(data["total"], 2)
        self.assertEqual({m["key"] for m in data["mentions"]}, {"marca:Curavino", "concorrente:Evino"})
        self.assertEqual(len(data["critical"]), 1)
        self.assertEqual(sum(d["count"] for d in data["timeline"]), 2)
        self.assertIn("https://adega.com/a1", clip.export_csv(rows))


class RouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from routes import content_ops
        self.routes = content_ops
        app = FastAPI()
        app.include_router(content_ops.router)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_client_never_sees_unreviewed_crisis_or_internal_fields(self):
        items = [{**ITEM, **LABEL, "id": "1", "status": "novo", "relevant": True},
                 {**ITEM, **LABEL, "id": "2", "status": "lido", "relevant": True},
                 {**ITEM, "id": "3", "status": "novo", "relevant": True, "sentiment": "positivo", "relevance": 70, "criticality": "baixa"}]
        view = {"items": items, "week": {}, "settings": {"saved": True, "brand_terms": ["x"]}}
        with patch.object(self.routes, "require_client_read", AsyncMock(return_value="cura")), \
             patch.object(self.routes, "is_agency_user", AsyncMock(return_value=False)), \
             patch.object(clip, "list_clippings", AsyncMock(return_value=view)) as listing:
            data = (await self.client.get("/api/clients/cura/studio/clipping", params={"q": "vinho"})).json()
        self.assertEqual([i["id"] for i in data["items"]], ["2", "3"])
        self.assertNotIn("evidence", data["items"][0])
        self.assertEqual(listing.await_args.args[0], "cura")

    async def test_report_and_export_are_agency_only(self):
        role = AsyncMock(return_value="cura")
        with patch.object(self.routes, "require_client_role", role), patch.object(clip, "period_rows", AsyncMock(return_value=[])):
            response = await self.client.get("/api/clients/cura/studio/clipping/export")
        self.assertEqual(response.headers["content-type"].split(";")[0], "text/csv")
        self.assertEqual(role.await_args.kwargs["allowed_roles"], ("agency_admin",))


if __name__ == "__main__":
    unittest.main()
