"""Biblioteca (arquivos/links + arte aprovada) e Planejamento/Evento (plano curto da IA, copiloto, vira Briefing)."""
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import studio_library as lib
from services import studio_projects as pj
from services.studio_calendar import StudioError
from services.team_access import route_module

EVENT_AI = {"titulo": "Lançamento", "resumo": "Evento de lançamento na loja.",
            "cronograma": [{"data": "2026-12-01", "fase": "Pré", "tarefa": "Fechar local"}],
            "equipe": [{"funcao": "Fotógrafo", "quantidade": "2", "observacao": ""}, {"funcao": "Produtor", "quantidade": "x", "observacao": ""}],
            "orcamento": [{"categoria": "equipe", "item": "Fotógrafo", "valor": "R$ 1.500"}, {"categoria": "xpto", "item": "Buffet", "valor": 2000}],
            "riscos": [{"risco": "Chuva", "impacto": "altissimo", "mitigacao": "Tenda"}], "checklist": ["Bateria extra"]}
PLAN_AI = {"titulo": "Natal", "contexto": "c", "desafio": "d", "insight": "i", "estrategia": "e", "grande_ideia": "g",
           "mensagens": ["m1"], "canais": [{"canal": "Instagram", "papel": "alcance"}, {"canal": "", "papel": "x"}],
           "fases": [{"fase": "Teaser", "quando": "1-7/12", "o_que": "aquecer"}], "kpis": [{"kpi": "Vendas", "meta": "200"}], "riscos": ["r"]}
PROJECT = {"id": "p1", "client_id": "ruah", "kind": "evento", "title": "Lançamento", "status": "fila", "inputs": {"idea": "lançar"},
           "plan": {}, "chat": [], "format": "Evento / Ativação", "target_date": "2026-12-10"}


class LibraryTests(unittest.IsolatedAsyncioTestCase):
    async def test_file_must_live_in_this_company_folder(self):
        with self.assertRaises(StudioError):
            await lib.add_item("ruah", {"kind": "arquivo", "url": "https://x.supabase.co/storage/v1/object/public/ig-media/studio-library/outra/a.png"},
                               user_id="u", author="A", side="cliente")
        with patch.object(lib, "sb_insert", AsyncMock(side_effect=lambda t, row: {**row, "id": "l1"})):
            out = await lib.add_item("ruah", {"kind": "arquivo", "category": "xx",
                                              "url": "https://x.supabase.co/storage/v1/object/public/ig-media/studio-library/ruah/a.png"},
                                     user_id="u", author="A", side="cliente")
        self.assertEqual(out["category"], "outro")
        self.assertEqual(out["title"], "a.png")

    async def test_client_deletes_only_what_it_sent(self):
        with patch.object(lib, "sb_select", AsyncMock(return_value=[{"id": "l1", "created_by": "outro"}])), patch.object(lib, "sb_delete", AsyncMock()) as d:
            with self.assertRaises(StudioError):
                await lib.delete_item("ruah", "l1", user_id="u", team=False)
            await lib.delete_item("ruah", "l1", user_id="u", team=True)
        d.assert_awaited_once()

    async def test_approved_posts_split_carousel(self):
        rows = [{"id": "i1", "title": "Post", "art_url": "https://a/1.jpg https://a/2.jpg", "status": "aprovado"}]
        with patch.object(lib, "sb_select", AsyncMock(return_value=rows)):
            out = await lib.approved_posts("ruah")
        self.assertEqual([o["url"] for o in out], ["https://a/1.jpg", "https://a/2.jpg"])

    async def test_unknown_type_rejected(self):
        with self.assertRaises(StudioError):
            await lib.upload_target("ruah", "application/x-msdownload")


class ProjectTests(unittest.IsolatedAsyncioTestCase):
    def test_event_plan_is_clean_and_budget_totals(self):
        plan = pj.clean_plan("evento", EVENT_AI)
        self.assertEqual(plan["budget_total"], 3500.0)
        self.assertEqual(plan["budget"][1]["category"], "outros")
        self.assertEqual([s["qty"] for s in plan["staff"]], [2, 1])
        self.assertEqual(plan["risks"][0]["impact"], "medio")

    def test_planning_drops_empty_channels(self):
        plan = pj.clean_plan("planejamento", PLAN_AI)
        self.assertEqual(len(plan["channels"]), 1)
        self.assertIn("Estratégia: e", pj.plan_text({"kind": "planejamento", "title": "Natal", "plan": plan, "inputs": {}}))

    async def test_generate_moves_from_queue_and_uses_chat(self):
        chat = [{"role": "equipe", "content": "corta o buffet"}]
        with patch.object(pj, "get_project", AsyncMock(return_value={**PROJECT, "chat": chat})), \
             patch("services.studio_engines.throttle"), \
             patch.object(pj, "load_profile", AsyncMock(return_value={"profile": {}})), \
             patch("services.studio_intelligence.build_content_intelligence", AsyncMock(return_value={})), \
             patch("services.studio_intelligence.to_prompt", return_value="{}"), \
             patch("services.studio_llm.llm_json", AsyncMock(return_value=EVENT_AI)) as llm, \
             patch.object(pj, "sb_update", AsyncMock(side_effect=lambda t, filters, patch: [{**PROJECT, **patch}])):
            out = await pj.generate_plan("ruah", "p1", use_chat=True)
        self.assertEqual(out["status"], "em_andamento")
        self.assertIn("corta o buffet", llm.await_args.kwargs["prompt"])

    async def test_brief_needs_a_plan(self):
        with patch.object(pj, "get_project", AsyncMock(return_value=PROJECT)):
            with self.assertRaises(StudioError):
                await pj.to_brief("ruah", "p1", user_id="u", author="A")

    async def test_edited_budget_recomputes_total(self):
        with patch.object(pj, "get_project", AsyncMock(return_value=PROJECT)), \
             patch.object(pj, "sb_update", AsyncMock(side_effect=lambda t, filters, patch: [{**PROJECT, **patch}])):
            out = await pj.update_project("ruah", "p1", {"plan": {"budget": [{"category": "equipe", "item": "A", "value": "1.000"}]}})
        self.assertEqual(out["plan"]["budget_total"], 1000.0)

    def test_permissions(self):
        self.assertEqual(route_module("POST", "/api/clients/x/studio/projects/evento"), ("tasks", "tasks.edit"))
        self.assertEqual(route_module("GET", "/api/clients/x/studio/library"), ("calendar", "calendar.view"))


if __name__ == "__main__":
    unittest.main()
