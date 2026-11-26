"""“Ir para o job”: o que nasceu da tarefa, com nome atual, situação e onde abrir; apagado aparece como removido."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import AsyncMock, patch

from services import task_produced as tp

LINKS = [
    {"module": "email_marketing", "record_id": "e1", "deliverable": "E-mail Black", "created_at": "2026-11-20"},
    {"module": "redacao", "record_id": "d1", "deliverable": "Legenda", "created_at": "2026-11-21"},
    {"module": "social_media", "record_id": "m1", "deliverable": "", "created_at": "2026-11-22"},
    {"module": "redacao", "record_id": "d2", "deliverable": "Roteiro", "created_at": "2026-11-23"},
]


class ProducedTests(unittest.IsolatedAsyncioTestCase):
    async def test_items_with_current_names_status_and_where_to_open(self):
        async def select(table, **kw):
            self.assertEqual(kw["filters"]["client_id"], "eq.ruah")  # sempre na mesma empresa
            return {"email_campaigns": [{"id": "e1", "name": "Black começa", "status": "rascunho"}],
                    "studio_documents": [{"id": "d1", "title": "Legenda do Reels", "status": "rascunho"}],
                    "studio_content_matrices": [{"id": "m1", "week_start": "2026-11-23", "status": "ativa"}]}[table]
        with patch.object(tp, "authorized_task", AsyncMock(return_value={"id": "t1"})), \
             patch.object(tp, "links_for", AsyncMock(return_value=LINKS)), patch.object(tp, "sb_select", select):
            out = await tp.produced("ruah", "t1", {})
        items = {i["record_id"]: i for i in out["items"]}
        self.assertEqual((items["e1"]["name"], items["e1"]["status"], items["e1"]["route"], items["e1"]["query"]),
                         ("Black começa", "Rascunho", "email_marketing", "campanha=e1"))
        self.assertEqual((items["d1"]["route"], items["d1"]["query"]), ("redacao", "doc=d1"))
        self.assertEqual(items["m1"]["name"], "Matriz de conteúdo (a partir de 23/11)")
        self.assertEqual((items["d2"]["name"], items["d2"]["removed"], items["d2"]["route"]), ("Removido", True, None))

    async def test_task_the_person_cannot_see_is_refused(self):
        from services.studio_calendar import StudioError
        with patch.object(tp, "authorized_task", AsyncMock(side_effect=StudioError("TASK_NOT_FOUND"))):
            with self.assertRaises(StudioError):
                await tp.produced("ruah", "t1", {"client_view": True})

    async def test_one_source_down_does_not_hide_the_others(self):
        async def select(table, **kw):
            if table == "email_campaigns":
                raise RuntimeError("fora do ar")
            return [{"id": "d1", "title": "Legenda", "status": "rascunho"}] if table == "studio_documents" else []
        with patch.object(tp, "authorized_task", AsyncMock(return_value={"id": "t1"})), \
             patch.object(tp, "links_for", AsyncMock(return_value=LINKS[:2])), patch.object(tp, "sb_select", select), \
             redirect_stdout(io.StringIO()):
            out = await tp.produced("ruah", "t1", {})
        self.assertEqual([i["name"] for i in out["items"]], ["Removido", "Legenda"])


if __name__ == "__main__":
    unittest.main()
