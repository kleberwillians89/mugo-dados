import unittest
from unittest.mock import AsyncMock, patch

from server.services import ig_supabase, studio_calendar


class PublicationGroupTests(unittest.IsolatedAsyncioTestCase):
    def base(self):
        return {
            "channel": "instagram", "format": "imagem", "title": "Campanha",
            "scheduled_at": "2026-11-26T10:00:00-03:00", "caption_draft": "Legenda",
            "art_url": "https://example.com/art.jpg", "collaborators": ["mugo.ag"],
            "publication_group_id": "8a4fc985-2ae3-4e35-ac75-308addcc925d",
        }

    async def test_three_destinations_preserve_shared_media_and_isolate_overrides(self):
        data = {**self.base(), "destinations": [
            {"channel": "facebook"},
            {"channel": "linkedin", "caption_draft": "LinkedIn", "scheduled_at": "2026-11-27T12:00:00-03:00"},
        ]}
        with patch.object(ig_supabase, "sb_rpc", AsyncMock(return_value=[])) as rpc:
            await studio_calendar.create_destinations("tenant", data, user_id="editor")
        args = rpc.await_args.args[1]
        self.assertEqual(args["p_client_id"], "tenant")
        instagram, facebook, linkedin = args["p_rows"]
        self.assertEqual({item["art_url"] for item in args["p_rows"]}, {data["art_url"]})
        self.assertEqual({item["status"] for item in args["p_rows"]}, {"rascunho"})
        self.assertEqual(instagram["collaborators"], ["mugo.ag"])
        self.assertNotIn("collaborators", facebook)
        self.assertEqual(linkedin["caption_draft"], "LinkedIn")
        self.assertNotEqual(linkedin["scheduled_at"], facebook["scheduled_at"])

    async def test_incompatible_format_rejected_before_writing(self):
        with patch.object(ig_supabase, "sb_rpc", AsyncMock()) as rpc:
            with self.assertRaises(studio_calendar.StudioError):
                await studio_calendar.create_destinations(
                    "tenant", {**self.base(), "destinations": [{"channel": "youtube"}]}, user_id="editor",
                )
        rpc.assert_not_awaited()
