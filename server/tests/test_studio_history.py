import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from services import studio_history as h


def run(coro):
    return asyncio.run(coro)


class HistoryTests(unittest.TestCase):
    def test_describe_patch(self):
        out = h.describe_patch({"status": "aprovado", "art_url": "https://x/a.jpg", "caption_draft": "nova", "title": "t",
                                "scheduled_at": "2026-11-07T11:00:00+00:00", "collaborators": ["m2communityrun"]})
        self.assertIn("moveu para Aprovado", out)
        self.assertIn("trocou a arte", out)
        self.assertIn("mudou a data para 07/11 às 08:00", out)
        self.assertIn("marcou colaborador @m2communityrun", out)
        self.assertIn("editou título, legenda", out)
        self.assertEqual(h.describe_patch({"art_url": ""}), ["tirou a arte"])

    def test_record_never_raises_and_skips_without_item(self):
        with patch.object(h, "sb_insert", AsyncMock(side_effect=RuntimeError("tabela não existe"))):
            run(h.record("m2", "i1", "criou a pauta", actor_name="Duda"))
        ins = AsyncMock()
        with patch.object(h, "sb_insert", ins):
            run(h.record("m2", None, "x", actor_name="Duda"))
            run(h.record("m2", "i1", "aprovou", actor_name=None, side="cliente"))
        self.assertEqual(ins.await_count, 1)
        self.assertEqual(ins.call_args.args[1]["actor_name"], "Cliente")

    def test_latest_by_item(self):
        rows = [{"item_id": "a", "action": "publicou", "created_at": "2"}, {"item_id": "a", "action": "agendou", "created_at": "1"},
                {"item_id": "b", "action": "criou", "created_at": "1"}]
        with patch.object(h, "sb_select", AsyncMock(return_value=rows)):
            out = run(h.latest_by_item("m2"))
        self.assertEqual(out["a"]["action"], "publicou")
        self.assertEqual(set(out), {"a", "b"})


if __name__ == "__main__":
    unittest.main()
