"""Clipping e Redação de campanha: fonte real, sem duplicar, limites conferidos no servidor, só agência."""
from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from routes import content_ops
from services import studio_campaigns as camp
from services import studio_clipping as clip
from services.studio_calendar import StudioError

RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Curavino lança linha de vinhos naturais - Revista Adega</title><link>https://news.google.com/a1</link>
<pubDate>Wed, 28 Oct 2026 12:00:00 GMT</pubDate><source url="https://adega.com">Revista Adega</source></item>
<item><title>Sorteio de vinho grátis - Spam News</title><link>https://news.google.com/a2</link><source>Spam News</source></item>
<item><title>sem link</title></item>
</channel></rss>"""


class ParseTests(unittest.TestCase):
    def test_title_source_date_and_hash(self):
        items = clip.parse_news_rss(RSS, term="Curavino", kind="marca")
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["title"], "Curavino lança linha de vinhos naturais")
        self.assertEqual(items[0]["source"], "Revista Adega")
        self.assertTrue(items[0]["published_at"].startswith("2026-10-28T12:00"))
        self.assertEqual(len(items[0]["url_hash"]), 40)
        self.assertEqual(clip.parse_news_rss("<xml quebrado", term="x", kind="marca"), [])


class RefreshTests(unittest.IsolatedAsyncioTestCase):
    SETTINGS = {"brand_terms": ["Curavino"], "competitor_terms": ["Wine"], "exclude_terms": ["sorteio"], "active": True,
                "last_run_at": None, "saved": True}

    async def test_dedupes_skips_existing_and_keeps_news_without_ai(self):
        a = clip.parse_news_rss(RSS, term="Curavino", kind="marca")[:1]
        same_title_other_url = [{**a[0], "url": "https://x/2", "url_hash": "b" * 40, "kind": "concorrente", "term": "Wine"}]
        fetched = AsyncMock(side_effect=[a, same_title_other_url])
        insert = AsyncMock()
        with patch.object(clip, "get_settings", AsyncMock(return_value=self.SETTINGS)), patch.object(clip, "fetch_term", fetched), \
             patch.object(clip, "sb_select", AsyncMock(return_value=[])), patch.object(clip, "sb_insert_many", insert), \
             patch.object(clip, "sb_update", AsyncMock()), patch.object(clip, "_classify", AsyncMock(return_value={})), \
             patch("services.studio_messages._client_name", AsyncMock(return_value="Curavino")), redirect_stdout(io.StringIO()):
            result = await clip.refresh("cura")
        self.assertEqual(result["new"], 1)  # mesma manchete por dois termos = uma linha
        row = insert.await_args.args[1][0]
        self.assertEqual(row["url"], "https://news.google.com/a1")
        self.assertNotIn("sentiment", row)  # IA fora: entra sem classificação, nunca inventada

    async def test_existing_news_is_not_inserted_again(self):
        a = clip.parse_news_rss(RSS, term="Curavino", kind="marca")[:1]
        insert = AsyncMock()
        with patch.object(clip, "get_settings", AsyncMock(return_value={**self.SETTINGS, "competitor_terms": []})), \
             patch.object(clip, "fetch_term", AsyncMock(return_value=a)), \
             patch.object(clip, "sb_select", AsyncMock(return_value=[{"url_hash": a[0]["url_hash"]}])), \
             patch.object(clip, "sb_insert_many", insert), patch.object(clip, "sb_update", AsyncMock()), \
             patch.object(clip, "_classify", AsyncMock(return_value={})), \
             patch("services.studio_messages._client_name", AsyncMock(return_value="Curavino")), redirect_stdout(io.StringIO()):
            result = await clip.refresh("cura")
        self.assertEqual(result["new"], 0)
        insert.assert_not_awaited()

    async def test_manual_refresh_has_cooldown_and_needs_terms(self):
        from datetime import datetime, timezone
        with patch.object(clip, "get_settings", AsyncMock(return_value={**self.SETTINGS, "last_run_at": datetime.now(timezone.utc).isoformat()})):
            with self.assertRaises(StudioError) as err:
                await clip.refresh("cura", manual=True)
        self.assertEqual(err.exception.code, "CLIPPING_COOLDOWN")
        with patch.object(clip, "get_settings", AsyncMock(return_value={**self.SETTINGS, "saved": False})):
            with self.assertRaises(StudioError) as err:
                await clip.refresh("cura")
        self.assertEqual(err.exception.code, "CLIPPING_NOT_CONFIGURED")

    async def test_ai_labels_are_validated(self):
        items = clip.parse_news_rss(RSS, term="Curavino", kind="marca")
        out = {"items": [{"index": 0, "sentimento": "positivo", "resumo": "Lançamento — linha natural", "relevante": True},
                         {"index": 9, "sentimento": "positivo", "resumo": "x", "relevante": True}]}
        with patch("services.studio_llm.llm_json", AsyncMock(return_value=out)):
            labels = await clip._classify("Curavino", items)
        self.assertEqual(labels, {0: {"sentiment": "positivo", "summary": "Lançamento, linha natural", "relevant": True}})


class CampaignTests(unittest.TestCase):
    def test_google_and_meta_limits_are_checked_by_the_server(self):
        limits = camp.check_limits("google_ads", {"titulos": ["Vinho natural na Black Friday", "x" * 31], "descricoes": ["y" * 91]})
        self.assertEqual([l["over"] for l in limits], [False, True, True])
        meta = camp.check_limits("meta_ads", [{"titulo": "t" * 41, "descricao": "ok", "texto_principal": "p"}])
        self.assertTrue(meta[0]["over"])

    def test_briefing_needs_name_and_objective_and_valid_dates(self):
        with self.assertRaises(StudioError):
            camp.normalize_briefing({"name": "", "objective": "x"})
        with self.assertRaises(StudioError):
            camp.normalize_briefing({"name": "BF", "objective": "vender", "start": "31/11"})
        brief = camp.normalize_briefing({"name": "BF — Ruah", "objective": "vender", "channels": ["reels", "hack"]})
        self.assertEqual(brief["channels"], ["reels"])
        self.assertEqual(brief["name"], "BF, Ruah")

    def test_only_posts_reels_and_stories_go_to_the_calendar(self):
        campaign = {"name": "BF", "briefing": {"name": "BF", "start": "2026-11-20"}, "package": {"concept": {"ideia": "Oud é presente"}, "pieces": {
            "post": {"content": {"legenda": "Legenda", "cta": "Compre", "ideia_visual": "frasco"}},
            "reels": {"content": {"gancho": "Abre", "cenas": [{"segundos": "0-3s", "visual": "v", "texto_tela": "t", "narracao": "n"}], "cta": "Link"}},
            "meta_ads": {"content": [{"titulo": "x"}]}, "email": {"content": {"assunto": "x"}}}}}
        rows = camp._calendar_rows(campaign)
        self.assertEqual(sorted(r["format"] for r in rows), ["imagem", "reels"])
        self.assertTrue(rows[0]["scheduled_at"].startswith("2026-11-21"))  # post no dia seguinte ao início


class CampaignFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_uses_brand_data_and_flags_cliches(self):
        ai = AsyncMock(return_value={"conceito": {"nome": "Presente certo", "ideia": "x", "por_que": "y"}, "titulos": ["a", "b", "c", "d"],
                                     "google_ads": {"titulos": ["Oud na Black Friday", "z" * 40], "descricoes": ["Imperdível"]}})
        with patch.object(camp, "_context", AsyncMock(return_value={"intel": {"marca": {"nome": "Ruah"}}, "avoid": [], "sales": {}})), \
             patch.object(camp, "llm_json", ai), patch.object(camp, "sb_insert", AsyncMock(side_effect=lambda t, row: row)), \
             patch.object(camp, "throttle", lambda cid: None):
            row = await camp.generate("ruah", {"name": "BF", "objective": "vender", "channels": ["google_ads"]}, user_id="u1")
        piece = row["package"]["pieces"]["google_ads"]
        self.assertEqual(len(row["package"]["titles"]), 3)
        self.assertTrue(any(l["over"] for l in piece["limits"]))
        self.assertIn("imperdível", piece["flags"])
        self.assertIn("google_ads", ai.await_args.kwargs["schema"]["properties"])
        self.assertNotIn("email", ai.await_args.kwargs["schema"]["properties"])

    async def test_to_calendar_does_not_duplicate(self):
        with patch.object(camp, "get_campaign", AsyncMock(return_value={"calendar_item_ids": ["i1"]})), \
             patch.object(camp, "create_item", AsyncMock()) as create:
            result = await camp.to_calendar("ruah", "c1", user_id="u1")
        self.assertTrue(result["already"])
        create.assert_not_awaited()


class AgencyOnlyTests(unittest.TestCase):
    def test_every_route_is_agency_only(self):
        # Exceção única: a leitura do clipping é aberta ao cliente (versão filtrada, ver
        # test_clipping_client_view). Toda escrita e o restante continuam só da agência.
        source = Path(content_ops.__file__).read_text(encoding="utf-8")
        routes = source.split("\n@router.")[1:]
        self.assertGreaterEqual(len(routes), 12)
        for route in routes:
            if route.startswith('get("/clipping")'):
                self.assertIn("require_client_read", route)
                self.assertIn("is_agency_user", route)
                continue
            self.assertIn("allowed_roles=AGENCY_ONLY", route, route.splitlines()[0])
        self.assertEqual(content_ops.AGENCY_ONLY, ("agency_admin",))


if __name__ == "__main__":
    unittest.main()
