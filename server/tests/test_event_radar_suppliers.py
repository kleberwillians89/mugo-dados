"""Evento: radar (clima e notícias da região), fornecedores e a ligação com o plano da IA."""
import io
import sys
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import event_radar as er
from services import studio_projects as sp
from services import studio_suppliers as ss
from services.studio_calendar import StudioError

TODAY = date(2026, 11, 11)
PLACE = {"name": "São Paulo", "region": "São Paulo", "country": "Brasil", "latitude": -23.5, "longitude": -46.6}


class PlaceTests(unittest.TestCase):
    def test_city_comes_before_the_address(self):
        self.assertEqual(er.place_candidates("Loja Jardins, Rua Oscar Freire 100, São Paulo - SP")[0], "São Paulo")
        self.assertEqual(er.place_candidates(""), [])


class WeatherTests(unittest.IsolatedAsyncioTestCase):
    async def test_near_date_uses_forecast_and_raises_rain_alert(self):
        daily = {"daily": {"weather_code": [63], "temperature_2m_max": [33.4], "temperature_2m_min": [21], "precipitation_probability_max": [80],
                           "precipitation_sum": [12.5], "wind_speed_10m_max": [25]}}
        er._GEO_CACHE.clear()
        with patch.object(er, "geocode", AsyncMock(return_value=PLACE)), patch.object(er, "_json", AsyncMock(return_value=daily)) as call, \
             patch.object(er, "region_news", AsyncMock(return_value=[{"manchete": "Alerta de temporal em SP"}])):
            radar = await er.build_radar("São Paulo", date(2026, 11, 20), today=TODAY)
        self.assertEqual(call.await_args.args[0], er.FORECAST)
        self.assertEqual(radar["clima"]["tipo"], "previsao")
        self.assertEqual(radar["clima"]["condicao"], "chuva")
        kinds = {a["tipo"]: a["gravidade"] for a in radar["alertas"]}
        self.assertEqual(kinds, {"chuva": "alta", "calor": "media"})
        text = er.radar_text(radar)
        self.assertIn("Previsão para 2026-11-20", text)
        self.assertIn("plano B", text)
        self.assertIn("Alerta de temporal em SP", text)

    async def test_far_date_uses_typical_climate_from_past_years(self):
        hist = {"daily": {"temperature_2m_max": [28, 30], "temperature_2m_min": [18, 20], "precipitation_sum": [0, 5]}}
        with patch.object(er, "geocode", AsyncMock(return_value=PLACE)), patch.object(er, "_json", AsyncMock(return_value=hist)) as call, \
             patch.object(er, "region_news", AsyncMock(return_value=[])):
            radar = await er.build_radar("São Paulo", date(2027, 2, 10), today=TODAY)
        self.assertEqual(call.await_count, 3)  # 3 anos
        self.assertTrue(all(c.args[0] == er.ARCHIVE for c in call.await_args_list))
        self.assertEqual(radar["clima"]["tipo"], "clima_tipico")
        self.assertEqual((radar["clima"]["max"], radar["clima"]["dias_com_chuva_pct"]), (29.0, 50))
        self.assertEqual(radar["alertas"][0]["gravidade"], "media")  # tendência, não previsão
        self.assertIn("não é previsão", er.radar_text(radar))

    async def test_past_date_and_missing_location(self):
        with patch.object(er, "geocode", AsyncMock(return_value=PLACE)), patch.object(er, "region_news", AsyncMock(return_value=[])):
            radar = await er.build_radar("São Paulo", date(2026, 10, 1), today=TODAY)
        self.assertEqual(radar["clima"]["tipo"], "passou")
        self.assertEqual(radar["alertas"], [])
        with self.assertRaises(StudioError) as raised:
            await er.build_radar(" ", None, today=TODAY)
        self.assertEqual(raised.exception.code, "EVENT_LOCATION_REQUIRED")

    async def test_sources_down_become_warnings(self):
        with patch.object(er, "geocode", AsyncMock(side_effect=RuntimeError("fora"))), \
             patch.object(er, "region_news", AsyncMock(side_effect=RuntimeError("fora"))), redirect_stdout(io.StringIO()):
            radar = await er.build_radar("Alicante", None, today=TODAY)
        self.assertEqual(radar["clima"], {})
        self.assertEqual(len(radar["avisos"]), 2)
        self.assertEqual(radar["local"]["name"], "Alicante")

    async def test_region_news_dedupes_and_keeps_only_public_fields(self):
        rss = ("<rss><channel><item><title>Chuva forte em Alicante</title><link>https://n.com/a</link><source>El País</source></item>"
               "<item><title>Chuva forte em Alicante</title><link>https://n.com/b</link></item></channel></rss>")
        with patch("services.news_engine._get", AsyncMock(return_value=rss)) as get:
            news = await er.region_news("Alicante")
        self.assertIn("Alicante", get.await_args_list[0].args[0])
        self.assertEqual(len(news), 1)
        self.assertEqual(set(news[0]), {"tema", "manchete", "fonte", "data", "link"})


class SupplierTests(unittest.IsolatedAsyncioTestCase):
    def test_clean_supplier(self):
        row = ss.clean_supplier({"name": " Buffet Sabor ", "category": "buffet", "email": "Contato@Buffet.com", "website": "buffet.com", "rating": 4})
        self.assertEqual((row["name"], row["email"], row["website"], row["rating"]), ("Buffet Sabor", "contato@buffet.com", "https://buffet.com", 4))
        for bad in ({"name": ""}, {"name": "X", "category": "nave"}, {"name": "X", "email": "sem-arroba"}, {"name": "X", "rating": 9}):
            with self.assertRaises(StudioError):
                ss.clean_supplier(bad)

    async def test_link_only_to_events_and_without_duplicates(self):
        with patch.object(sp, "get_project", AsyncMock(return_value={"id": "p1", "kind": "planejamento"})):
            with self.assertRaises(StudioError) as raised:
                await ss.link_supplier("ruah", "p1", {"supplier_id": "s1"})
        self.assertEqual(raised.exception.code, "PROJECT_KIND_INVALID")
        supplier = {"id": "s1", "name": "Foto Já", "category": "fotografia"}
        with patch.object(sp, "get_project", AsyncMock(return_value={"id": "p1", "kind": "evento"})), \
             patch.object(ss, "sb_select", AsyncMock(side_effect=[[supplier], [{"id": "l0"}]])):
            with self.assertRaises(StudioError) as raised:
                await ss.link_supplier("ruah", "p1", {"supplier_id": "s1"})
        self.assertEqual(raised.exception.code, "SUPPLIER_ALREADY_LINKED")
        with patch.object(sp, "get_project", AsyncMock(return_value={"id": "p1", "kind": "evento"})), \
             patch.object(ss, "sb_select", AsyncMock(side_effect=[[supplier], []])), \
             patch.object(ss, "sb_insert", AsyncMock(side_effect=lambda t, row: {"id": "l1", **row})) as ins:
            link = await ss.link_supplier("ruah", "p1", {"supplier_id": "s1", "item": "Cobertura", "value": "R$ 2.500"})
        self.assertEqual(ins.await_args.args[1]["value"], 2500.0)
        self.assertEqual(ins.await_args.args[1]["status"], "cotando")
        self.assertEqual(link["supplier"]["name"], "Foto Já")

    async def test_push_to_budget_adds_once_and_updates(self):
        links = [{"id": "l1", "supplier_id": "s1", "status": "contratado", "value": 2500, "item": "Cobertura",
                  "supplier": {"name": "Foto Já", "category": "fotografia"}},
                 {"id": "l2", "supplier_id": "s2", "status": "cotando", "value": 900, "supplier": {"name": "Som", "category": "som_luz"}}]
        project = {"id": "p1", "kind": "evento", "plan": {"budget": [{"category": "equipe", "item": "Foto Já (Cobertura)", "value": 2000,
                                                                     "supplier_link_id": "l1"}, {"category": "outros", "item": "Brinde", "value": 300}]}}
        with patch.object(sp, "get_project", AsyncMock(return_value=project)), patch.object(ss, "event_suppliers", AsyncMock(return_value=links)), \
             patch.object(sp, "update_project", AsyncMock(side_effect=lambda cid, pid, data: data)) as upd:
            await ss.push_to_budget("ruah", "p1")
        budget = upd.await_args.args[2]["plan"]["budget"]
        self.assertEqual(len(budget), 2)  # atualizou a linha do l1, não duplicou; l2 ainda cotando fica de fora
        self.assertEqual(budget[0]["value"], 2500.0)
        self.assertEqual(budget[0]["category"], "equipe")

    async def test_suppliers_text_never_carries_contact_data(self):
        everyone = [{"id": "s1", "name": "Buffet Sabor", "category": "buffet", "city": "São Paulo", "price_note": "R$ 90/pessoa", "rating": 5,
                     "phone": "11 99999-0000", "email": "a@b.com", "contact_name": "Fulana"},
                    {"id": "s2", "name": "Foto Já", "category": "fotografia"}]
        linked = [{"supplier_id": "s2", "item": "Cobertura", "status": "contratado", "value": 2500, "supplier": everyone[1]}]
        with patch.object(ss, "event_suppliers", AsyncMock(return_value=linked)), patch.object(ss, "list_suppliers", AsyncMock(return_value=everyone)):
            text = await ss.suppliers_text("ruah", "p1")
        self.assertIn("JÁ NO EVENTO: Foto Já", text)
        self.assertIn("R$ 90/pessoa", text)
        for secret in ("99999", "a@b.com", "Fulana"):
            self.assertNotIn(secret, text)


class PlanLinkTests(unittest.IsolatedAsyncioTestCase):
    async def test_event_plan_reads_radar_and_suppliers_and_keeps_supplier_lines(self):
        radar = {"local": {"name": "São Paulo"}, "clima": {"tipo": "previsao", "data": "2026-11-20", "chance_chuva": 80},
                 "alertas": [{"tipo": "chuva", "texto": "Chance de chuva de 80%: tenha plano B coberto."}], "noticias": []}
        project = {"id": "p1", "kind": "evento", "title": "Ativação", "status": "em_andamento", "inputs": {"idea": "Degustação", "location": "SP"},
                   "radar": radar, "plan": {"budget": [{"category": "equipe", "item": "Foto Já", "value": 2500, "supplier_link_id": "l1"}]}}
        ai = {"resumo": "Ativação.", "cronograma": [{"data": "2026-11-19", "fase": "Pré", "tarefa": "Montagem"}], "equipe": [],
              "orcamento": [{"categoria": "locacao", "item": "Tenda", "valor": "1.000"}], "riscos": [], "checklist": []}
        llm = AsyncMock(return_value=ai)
        with patch.object(sp, "get_project", AsyncMock(return_value=project)), patch.object(sp, "load_profile", AsyncMock(return_value={"profile": {}})), \
             patch("services.studio_engines.throttle"), patch("services.studio_intelligence.build_content_intelligence", AsyncMock(return_value={})), \
             patch("services.studio_suppliers.suppliers_text", AsyncMock(return_value="- JÁ NO EVENTO: Foto Já")), \
             patch("services.studio_llm.llm_json", llm), patch.object(sp, "sb_update", AsyncMock(side_effect=lambda t, filters, patch: [patch])):
            out = await sp.generate_plan("ruah", "p1")
        prompt = llm.await_args.kwargs["prompt"]
        self.assertIn("CLIMA E NOTÍCIAS DA REGIÃO", prompt)
        self.assertIn("plano B coberto", prompt)
        self.assertIn("JÁ NO EVENTO: Foto Já", prompt)
        self.assertEqual([b["item"] for b in out["plan"]["budget"]], ["Foto Já", "Tenda"])
        self.assertEqual(out["plan"]["budget_total"], 3500.0)

    def test_edited_budget_keeps_the_supplier_link(self):
        plan = sp._reclean("evento", {"budget": [{"category": "equipe", "item": "Foto Já", "value": 2500, "supplier_link_id": "l1"}]})
        self.assertEqual(plan["budget"][0]["supplier_link_id"], "l1")


if __name__ == "__main__":
    unittest.main()
