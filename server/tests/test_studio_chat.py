import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from services import studio_chat
from services.studio_calendar import StudioError


def run(coro):
    return asyncio.run(coro)


class ChatTests(unittest.TestCase):
    def test_client_cannot_use_team_channel(self):
        with self.assertRaises(StudioError) as ctx:
            studio_chat.check_channel("equipe", agency=False)
        self.assertEqual(ctx.exception.code if hasattr(ctx.exception, "code") else str(ctx.exception), "CHAT_FORBIDDEN")
        self.assertEqual(studio_chat.check_channel("equipe", agency=True), "equipe")
        with self.assertRaises(StudioError):
            studio_chat.check_channel("outro", agency=True)

    def test_author_name(self):
        self.assertEqual(studio_chat.author_name_from_claims({"user_metadata": {"full_name": "Julia  Portela"}}), "Julia Portela")
        self.assertEqual(studio_chat.author_name_from_claims({"email": "danilo@x.com"}), "danilo")
        self.assertEqual(studio_chat.author_name_from_claims({}), "Equipe")

    def test_client_message_notifies_team_and_hides_author_id(self):
        insert = AsyncMock(return_value={"id": "m1", "channel": "cliente", "author_id": "u1", "author_side": "cliente",
                                         "author_name": "Carelle", "body": "oi", "item_id": None})
        notify = AsyncMock()
        with patch.object(studio_chat, "sb_insert", insert), patch.object(studio_chat, "mark_read", AsyncMock()), \
             patch("services.studio_team.notify_team", notify):
            out = run(studio_chat.post_message("latinas", "cliente", " oi ", agency=False, user_id="u1", author_name="Carelle"))
        self.assertNotIn("author_id", out)
        self.assertTrue(out["mine"])
        self.assertEqual(insert.call_args.args[1]["author_side"], "cliente")
        notify.assert_awaited_once()
        self.assertEqual(notify.call_args.args[2], "comentario")

    def test_team_message_does_not_notify(self):
        notify = AsyncMock()
        with patch.object(studio_chat, "sb_insert", AsyncMock(return_value=None)), patch.object(studio_chat, "mark_read", AsyncMock()), \
             patch("services.studio_team.notify_team", notify):
            out = run(studio_chat.post_message("latinas", "equipe", "interno", agency=True, user_id="u2", author_name="Julia"))
        notify.assert_not_awaited()
        self.assertEqual(out["author_side"], "mugo")

    def test_empty_body_rejected(self):
        with self.assertRaises(StudioError):
            run(studio_chat.post_message("latinas", "cliente", "   ", agency=True, user_id="u", author_name="x"))

    def test_timeline_merges_sources_newest_first(self):
        async def fake_select(table, **kw):
            return {
                "studio_team_events": [{"id": "1", "item_id": None, "action": "aprovado", "actor_name": "Carelle",
                                        "payload": {"title": "Post A"}, "created_at": "2026-11-03T10:00:00Z"}],
                "studio_approval_requests": [{"id": "2", "item_ids": ["a", "b"], "contact_name": None, "status": "aberto",
                                              "created_at": "2026-11-02T10:00:00Z", "completed_at": None}],
                "studio_item_comments": [],
                "studio_references": [{"id": "3", "url": "https://x.com/a", "note": None, "created_at": "2026-11-04T10:00:00Z"}],
                "studio_calendar_items": [{"id": "9", "title": "Reels do desafio", "published_permalink": "https://instagram.com/p/x", "updated_at": "2026-11-05T10:00:00Z"}],
            }.get(table, [])
        with patch.object(studio_chat, "sb_select", fake_select):
            events = run(studio_chat.timeline("latinas"))
        self.assertEqual([e["kind"] for e in events], ["publicado", "referencia", "aprovado", "pedido"])
        self.assertEqual(events[0]["link"], "https://instagram.com/p/x")
        self.assertIn("Carelle aprovou “Post A”", events[2]["text"])
        self.assertIn("2 posts", events[3]["text"])

    def test_timeline_survives_missing_source(self):
        async def broken(table, **kw):
            if table == "studio_team_events":
                raise RuntimeError("missing")
            return []
        with patch.object(studio_chat, "sb_select", broken):
            self.assertEqual(run(studio_chat.timeline("latinas")), [])


if __name__ == "__main__":
    unittest.main()
