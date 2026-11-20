"""Criadores: achar o @ certo enquanto digita, busca por nome e foto que não expira."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services import creators, creators_providers as providers
from services.integration_errors import IntegrationError


class PeopleItemsTests(unittest.TestCase):
    def test_reads_field_variants_and_drops_invalid(self):
        items = [{"username": "Ana.Treino", "fullName": "Ana", "profilePicUrl": "https://cdn/a.jpg", "followersCount": 1200, "verified": True},
                 {"user": {"username": "bia_fit", "full_name": "Bia", "profile_pic_url": "https://cdn/b.jpg", "follower_count": "300"}},
                 {"username": "ana.treino"}, {"username": "nome inválido"}, "lixo"]
        out = providers.instagram_people_items(items)
        self.assertEqual([p["handle"] for p in out], ["ana.treino", "bia_fit"])
        self.assertEqual((out[0]["followers"], out[0]["verified"], out[1]["followers"]), (1200, True, 300))


class AvatarTests(unittest.IsolatedAsyncioTestCase):
    async def test_copies_photo_to_storage(self):
        resp = MagicMock(status_code=200, headers={"content-type": "image/jpeg"}, content=b"img")
        client = MagicMock(); client.get = AsyncMock(return_value=resp)
        ctx = MagicMock(); ctx.__aenter__ = AsyncMock(return_value=client); ctx.__aexit__ = AsyncMock(return_value=False)
        with patch.object(creators.httpx, "AsyncClient", return_value=ctx), \
             patch.object(creators, "sb_upload_public", AsyncMock(return_value="https://x.supabase.co/storage/v1/object/public/ig-media/creators/instagram/ana.jpg")) as up:
            url = await creators.persist_avatar("instagram", "ana", "https://scontent.cdninstagram.com/a.jpg?oe=123")
        self.assertIn("/storage/v1/object/public/", url)
        up.assert_awaited_once()
        self.assertEqual(up.await_args.args[0], "creators/instagram/ana.jpg")

    async def test_keeps_original_when_not_image_or_already_stored(self):
        stored = "https://x.supabase.co/storage/v1/object/public/ig-media/creators/instagram/ana.jpg"
        self.assertEqual(await creators.persist_avatar("instagram", "ana", stored), stored)
        self.assertIsNone(await creators.persist_avatar("instagram", "ana", None))
        resp = MagicMock(status_code=200, headers={"content-type": "text/html"}, content=b"<html>")
        client = MagicMock(); client.get = AsyncMock(return_value=resp)
        ctx = MagicMock(); ctx.__aenter__ = AsyncMock(return_value=client); ctx.__aexit__ = AsyncMock(return_value=False)
        with patch.object(creators.httpx, "AsyncClient", return_value=ctx):
            self.assertEqual(await creators.persist_avatar("instagram", "ana", "https://cdn/a"), "https://cdn/a")


class ResolveTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        creators._PREVIEW_CACHE.clear()

    async def test_saved_and_exact_preview(self):
        saved = [{"id": "1", "network": "instagram", "handle": "ana.treino", "display_name": "Ana", "avatar_url": "u", "followers": 10}]
        meta = AsyncMock(return_value={"network": "instagram", "handle": "bia_fit", "display_name": "Bia", "avatar_url": "p", "followers": 99, "posts": []})
        with patch.object(creators, "list_creators", AsyncMock(return_value=saved)), patch.object(creators, "_meta_profile", meta), \
                patch.object(creators, "similar_profiles", AsyncMock(return_value=[])):
            out = await creators.resolve("roove", "instagram", "@bia_fit", None)
            again = await creators.resolve("roove", "instagram", "@bia_fit", None)
        self.assertEqual(out["saved"][0]["handle"], "ana.treino")
        self.assertEqual(out["exact"]["handle"], "bia_fit")
        self.assertEqual(again["exact"], out["exact"])
        meta.assert_awaited_once()  # cache: não consulta a Meta de novo a cada tecla

    async def test_name_with_space_does_not_call_meta(self):
        with patch.object(creators, "list_creators", AsyncMock(return_value=[])), patch.object(creators, "_meta_profile", AsyncMock()) as meta:
            out = await creators.resolve("roove", "instagram", "ana treino", None)
        meta.assert_not_awaited()
        self.assertIsNone(out["exact"])

    async def test_not_professional_account(self):
        boom = AsyncMock(side_effect=IntegrationError("x", status_code=404, code="CREATOR_NOT_FOUND", provider="meta"))
        with patch.object(creators, "list_creators", AsyncMock(return_value=[])), patch.object(creators, "_meta_profile", boom):
            out = await creators.resolve("roove", "instagram", "fulano", None)
        self.assertTrue(out["exact"]["missing"])

    async def test_people_search_uses_apify_budget(self):
        with patch.object(creators, "_apify", AsyncMock(return_value=[{"username": "ana.treino", "fullName": "Ana"}])) as run:
            out = await creators.people_search("roove", "Ana Treino")
        self.assertEqual(out["people"][0]["handle"], "ana.treino")
        self.assertEqual(run.await_args.args[1], "instagram_people")
        with self.assertRaises(ValueError):
            await creators.people_search("roove", "a")


if __name__ == "__main__":
    unittest.main()
