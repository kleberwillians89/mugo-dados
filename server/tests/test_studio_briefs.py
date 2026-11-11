"""Briefing: pedido → briefing curto com o contexto → destinos e tarefa de cada pessoa; cliente vê só a versão curta."""
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import studio_briefs as sb
from services.studio_calendar import StudioError

AI = {"titulo": "Black Friday decant", "resumo": "Campanha de decant na Black Friday.", "objetivo": "Vender decants",
      "mensagem": "Teste o nicho sem pagar o frasco", "publico": "Quem já usa importado", "prazo": "2026-11-27",
      "entregaveis": ["4 Reels", "campanha Meta de vendas"], "nao_fazer": ["Prometer desconto não aprovado"],
      "meta": "120 pedidos de decant em 30 dias", "versao_cliente": "Vamos lançar a campanha de decant até 27/11 e medir pelos pedidos.",
      "destinos": [{"destino": "social_media", "por_que": "conteúdo do mês"}, {"destino": "midia_on", "por_que": "vendas"},
                   {"destino": "inexistente", "por_que": "x"}],
      "funcoes": [{"funcao": "designer", "o_que_fazer": "Capas dos Reels"}, {"funcao": "trafego", "o_que_fazer": "Campanha de vendas"}],
      "midia_objetivo": "vendas", "midia_verba": "R$ 3.000", "clipping_termos": ["decant"], "criadores_tipo": "ugc"}
ROW = {"id": "b1", "client_id": "ruah", "request": "BF de decant com 3 mil", "links": [], "status": "pronto", "tasks": [],
       "destinations": {}, "brief": sb.clean_brief(AI), "created_side": "mugo", "created_at": "2026-11-11T20:00:00Z"}


class CleanTests(unittest.TestCase):
    def test_short_fields_and_valid_destinations(self):
        b = sb.clean_brief(AI)
        self.assertEqual([d["key"] for d in b["destinations"]], ["social_media", "midia_on"])
        self.assertEqual(b["media"], {"objective": "vendas", "budget": 3000.0})
        self.assertEqual(b["deadline"], "2026-11-27")
        self.assertEqual([r["role"] for r in b["roles"]], ["designer", "trafego"])
        self.assertEqual(sb.clean_brief({**AI, "prazo": "sexta"})["deadline"], None)

    def test_client_sees_only_the_short_version(self):
        view = sb.client_view({**ROW, "tasks": [{"task_id": "t1"}]}, {"done": 1, "total": 2})
        self.assertEqual(set(view["brief"]), {"title", "client_summary", "deadline", "goal"})
        self.assertNotIn("destinations", view)
        self.assertNotIn("tasks", view)
        self.assertEqual(view["progress"], {"done": 1, "total": 2})


class FlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_client_request_waits_for_the_team_and_warns_it(self):
        with patch.object(sb, "generate_brief", AsyncMock(return_value=ROW["brief"])), \
             patch.object(sb, "sb_insert", AsyncMock(side_effect=lambda t, row: {**row, "id": "b2", "created_at": "x"})) as insert, \
             patch("services.studio_team.notify_team", AsyncMock()) as notify:
            out = await sb.create_brief("ruah", request="Quero BF", links=["https://x.com/a", "http://inseguro"], user_id="u", author="Gabi", team=False)
        self.assertEqual(insert.await_args.args[1]["status"], "aguardando_equipe")
        self.assertEqual(insert.await_args.args[1]["links"], ["https://x.com/a"])
        self.assertNotIn("destinations", out)
        notify.assert_awaited()

    async def test_cannot_distribute_before_approval(self):
        with patch.object(sb, "get_brief", AsyncMock(return_value={**ROW, "status": "aguardando_equipe"})):
            with self.assertRaises(StudioError) as raised:
                await sb.send_to("ruah", "b1", "redacao", user_id="u")
        self.assertEqual(raised.exception.code, "BRIEF_NOT_APPROVED")

    async def test_social_media_runs_the_agents_with_the_brief_as_focus(self):
        with patch.object(sb, "get_brief", AsyncMock(return_value=ROW)), patch.object(sb, "sb_update", AsyncMock()) as upd, \
             patch("services.studio_agents.start_run", AsyncMock(return_value={"id": "r1"})) as run:
            out = await sb.send_to("ruah", "b1", "social_media", user_id="u")
        self.assertIn("Vender decants", run.await_args.kwargs["focus"])
        self.assertEqual(out["destinations"]["social_media"]["status"], "feito")
        self.assertEqual(upd.await_args.kwargs["patch"]["status"], "distribuido")
        self.assertEqual(run.await_args.kwargs["brief_id"], "b1")
        self.assertIn("weeks", run.await_args.kwargs)  # prazo do briefing vira o período da Matriz
        self.assertIn("Gerar conteúdo", out["destinations"]["social_media"]["detail"])

    async def test_social_media_with_busy_pipeline_says_it_is_queued(self):
        with patch.object(sb, "get_brief", AsyncMock(return_value=ROW)), patch.object(sb, "sb_update", AsyncMock()), \
             patch("services.studio_agents.start_run", AsyncMock(return_value={"id": "r2", "status": "na_fila"})):
            out = await sb.send_to("ruah", "b1", "social_media", user_id="u")
        self.assertEqual(out["destinations"]["social_media"]["status"], "feito")
        self.assertIn("fila", out["destinations"]["social_media"]["detail"])

    async def test_a_failed_destination_is_written_on_it(self):
        with patch.object(sb, "get_brief", AsyncMock(return_value=ROW)), patch.object(sb, "sb_update", AsyncMock()), \
             patch("services.studio_clipping.get_settings", AsyncMock(return_value={"brand_terms": []})):
            out = await sb.send_to("ruah", "b1", "clipping", user_id="u")
        self.assertEqual(out["destinations"]["clipping"]["status"], "falhou")
        self.assertIn("Configure o Clipping", out["destinations"]["clipping"]["detail"])

    async def test_redacao_and_media(self):
        with patch.object(sb, "get_brief", AsyncMock(return_value=ROW)), patch.object(sb, "sb_update", AsyncMock()), \
             patch("services.studio_documents.create_document", AsyncMock(return_value={"id": "d1"})) as doc:
            out = await sb.send_to("ruah", "b1", "redacao", user_id="u")
        self.assertIn("Vender decants", doc.await_args.args[1]["content_html"])
        self.assertEqual(out["destinations"]["redacao"]["ref"], {"document_id": "d1"})
        with patch.object(sb, "get_brief", AsyncMock(return_value=ROW)), patch.object(sb, "sb_update", AsyncMock()), \
             patch("services.media_strategy.build_strategy", AsyncMock(return_value={"month": "2026-11"})) as build, \
             patch("services.media_plan.record_strategy", AsyncMock(return_value={"id": "s1", "saved": True})):
            out = await sb.send_to("ruah", "b1", "midia_on", user_id="u")
        self.assertEqual((build.await_args.kwargs["objective"], build.await_args.kwargs["custom_budget"]), ("vendas", 3000.0))
        self.assertEqual(out["destinations"]["midia_on"]["ref"], {"strategy_id": "s1"})

    async def test_task_for_a_person_carries_their_part(self):
        create = AsyncMock(return_value={"id": "t1"})
        with patch.object(sb, "get_brief", AsyncMock(return_value=ROW)), patch.object(sb, "sb_update", AsyncMock()) as upd, \
             patch("services.studio_tasks.create_task", create):
            out = await sb.create_person_task("ruah", "b1", role="designer", user_id="u", assignee_user_id="u-liliu",
                                              assignee_name="Liliu", due_date=None, note="Usar a paleta nova")
        data = create.await_args.args[1]
        self.assertEqual((data["title"], data["assignee_user_id"]), ("Designer: Black Friday decant", "u-liliu"))
        self.assertIn("Sua parte (Designer): Capas dos Reels", data["notes"])
        self.assertIn("Recado: Usar a paleta nova", data["notes"])
        self.assertEqual(out["tasks"][0]["task_id"], "t1")
        self.assertEqual(upd.await_args.kwargs["patch"]["status"], "distribuido")


if __name__ == "__main__":
    unittest.main()


class MoneyTests(unittest.TestCase):
    def test_brazilian_amounts(self):
        for raw, expected in (("R$ 3.000", 3000.0), ("3000", 3000.0), ("3.000,50", 3000.5), ("3 mil", 3000.0), ("", None), ("1.5", 1.5)):
            self.assertEqual(sb.parse_brl(raw), expected, raw)
