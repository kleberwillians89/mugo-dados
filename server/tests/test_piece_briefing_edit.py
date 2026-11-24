"""'Editar peça': a equipe edita o briefing da peça (campos, roteiro, direção da arte) sem perder o resto dos sinais."""
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from routes.studio import ItemPatch
from services import studio_calendar as sc
from services import studio_client as scl
from services.studio_history import describe_patch

SIGNALS = {"engine": "ia", "briefing": {"summary": "Antigo", "objective": "Gerar desejo", "deliverables": ["Reels"]}}


class EditTests(unittest.IsolatedAsyncioTestCase):
    async def test_merges_into_briefing_keeping_other_signals(self):
        select = AsyncMock(return_value=[{"signals": SIGNALS}])
        with patch.object(sc, "sb_select", select), patch.object(sc, "sb_update", AsyncMock(return_value=[{"id": "i1"}])) as update:
            await sc.update_item("ruah", "i1", {"briefing": {"summary": " Novo ", "objective": "", "deliverables": ["Reels", " ", "Capa"]},
                                                "script": " Cena 1 ", "visual_idea": ""}, user_id="u")
        sent = update.await_args.kwargs["patch"]
        self.assertEqual(sent["signals"], {"engine": "ia", "briefing": {"summary": "Novo", "deliverables": ["Reels", "Capa"]}})
        self.assertEqual(sent["script"], "Cena 1")
        self.assertIsNone(sent["visual_idea"])
        self.assertNotIn("briefing", sent)
        self.assertEqual(select.await_args.kwargs["filters"]["client_id"], "eq.ruah")

    async def test_other_edits_do_not_touch_signals(self):
        with patch.object(sc, "sb_select", AsyncMock()) as select, patch.object(sc, "sb_update", AsyncMock(return_value=[{"id": "i1"}])) as update:
            await sc.update_item("ruah", "i1", {"caption_draft": "x"}, user_id="u")
        select.assert_not_awaited()
        self.assertNotIn("signals", update.await_args.kwargs["patch"])

    async def test_missing_item_is_not_found(self):
        with patch.object(sc, "sb_select", AsyncMock(return_value=[])):
            with self.assertRaises(sc.StudioError):
                await sc.update_item("ruah", "i1", {"briefing": {"summary": "x"}}, user_id="u")

    def test_input_model_and_permissions(self):
        body = ItemPatch(briefing={"summary": "a", "deliverables": ["b"]}, script="c").model_dump(mode="json", exclude_none=True)
        self.assertEqual(body, {"briefing": {"summary": "a", "deliverables": ["b"]}, "script": "c"})
        with self.assertRaises(Exception):
            ItemPatch(briefing={"outro": "x"})
        self.assertTrue({"briefing", "script", "visual_idea"}.isdisjoint(scl.CLIENT_FIELDS))  # cliente não edita
        self.assertIn("editou o briefing da peça", describe_patch({"script": "x"}))


if __name__ == "__main__":
    unittest.main()
