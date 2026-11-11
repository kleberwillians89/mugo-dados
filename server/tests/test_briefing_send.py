"""Enviar o briefing para alguém: tarefa da pessoa, só com o que a função precisa."""
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import studio_briefing_send as bs
from services.studio_calendar import StudioError

ITEM = {"id": "i1", "title": "3 perfumes para o verão", "format": "carrossel", "scheduled_at": "2026-11-20T22:00:00+00:00",
        "hook": "Calor pede perfume diferente", "caption_draft": "Legenda com CTA", "visual_idea": "Frascos no mármore",
        "script": "Slide 1: capa", "pillar": "Educação", "product_tags": [{"product_id": "5", "name": "Decant Nishane"}],
        "signals": {"briefing": {"summary": "Carrossel educativo", "objective": "Gerar pedidos de decant", "target_audience": "Quem já usa importado",
                                 "deliverables": ["Carrossel 4:5 com 6 slides"], "tech_requirements": ["1080 x 1350"], "key_message": "Nicho leve"}}}


class TextTests(unittest.TestCase):
    def test_each_role_gets_only_what_it_needs(self):
        designer = bs.build_text(ITEM, "designer", "Usar a paleta nova")
        self.assertIn("Direção da arte: Frascos no mármore", designer)
        self.assertIn("- Carrossel 4:5 com 6 slides", designer)
        self.assertIn("Pedido: Usar a paleta nova", designer)
        self.assertNotIn("Gerar pedidos de decant", designer)
        traffic = bs.build_text(ITEM, "trafego")
        self.assertIn("Público: Quem já usa importado", traffic)
        self.assertIn("- Decant Nishane", traffic)
        self.assertNotIn("Frascos no mármore", traffic)
        self.assertIn("publica 20/11 às 19:00", traffic)

    def test_due_two_days_before_but_never_in_the_past(self):
        self.assertEqual(bs.default_due(ITEM, today=date(2026, 11, 11)), "2026-11-18")
        self.assertEqual(bs.default_due(ITEM, today=date(2026, 11, 19)), "2026-11-19")


class SendTests(unittest.IsolatedAsyncioTestCase):
    async def test_creates_the_persons_task_and_logs_it_on_the_post(self):
        create = AsyncMock(return_value={"id": "t1"})
        with patch("services.ig_supabase.sb_select", AsyncMock(return_value=[ITEM])), \
             patch("services.studio_tasks.create_task", create), patch("services.studio_history.record", AsyncMock()) as record:
            await bs.send_briefing("ruah", "i1", role="designer", user_id="u-kleber", assignee_user_id="u-liliu",
                                   assignee_name="Liliu", due_date=None, note=None, actor_name="Kleber")
        data = create.await_args.args[1]
        self.assertEqual((data["title"], data["assignee_user_id"], data["assignee_name"], data["category"], data["visible_to_client"]),
                         ("Designer: 3 perfumes para o verão", "u-liliu", "Liliu", "Designer", False))
        self.assertIn("enviou o briefing para Liliu (Designer)", record.await_args.args[2])

    async def test_unknown_role_is_refused(self):
        with self.assertRaises(StudioError):
            await bs.send_briefing("ruah", "i1", role="astronauta", user_id="u", assignee_user_id=None, assignee_name=None,
                                   due_date=None, note=None, actor_name="K")


if __name__ == "__main__":
    unittest.main()
